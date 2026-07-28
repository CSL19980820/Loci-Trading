"""全局测试隔离与清理。

目标：
1. 每个用例使用独立临时数据目录，禁止碰真实 ``data/`` / 用户 loci.config。
2. 用例结束后还原环境变量，并尽量删掉临时目录。
3. 会话结束时清掉仓库内残留的测试垃圾（若有）。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# 测试期间可能污染进程环境的键；结束后必须还原。
_ENV_KEYS = (
    "LOCI_DATA_DIR",
    "PALACE_DATA_DIR",
    "PALACE_DB",
    "PALACE_MARKET_DB",
    "PALACE_OPS_DB",
    "PALACE_SKILL_ROOT",
    "PALACE_MCP_JSON",
    "PALACE_AI_MASTER_KEY",
    "PALACE_ENABLE_SCHEDULER",
    "PALACE_ENV",
    "PALACE_WRITE_TOKEN",
    "PALACE_AUTH_USERNAME",
    "PALACE_AUTH_PASSWORD",
    "PALACE_SESSION_SECRET",
    "PALACE_INSECURE_HTTP",
    "PALACE_ALLOWED_HOSTS",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolate_loci_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """每个测试：独立 data 根 + 清空相关环境变量副作用。"""
    data_root = tmp_path / "loci-data"
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "skills").mkdir(exist_ok=True)

    # 先清掉可能指向真实用户数据的键，再写入隔离路径。
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("LOCI_DATA_DIR", str(data_root))
    monkeypatch.setenv("PALACE_DB", str(data_root / "palace.db"))
    monkeypatch.setenv("PALACE_MARKET_DB", str(data_root / "market.db"))
    monkeypatch.setenv("PALACE_OPS_DB", str(data_root / "ops.db"))
    monkeypatch.setenv("PALACE_SKILL_ROOT", str(data_root / "skills"))
    monkeypatch.setenv("PALACE_MCP_JSON", str(data_root / "mcp.json"))
    # 禁止测试顺手拉起进程内调度器。
    monkeypatch.delenv("PALACE_ENABLE_SCHEDULER", raising=False)

    # 若业务代码缓存了 import 期路径，尽量刷新（skills 已改为每次解析）。
    try:
        import src.ops.application.skills as skills_mod

        if hasattr(skills_mod, "DEFAULT_SKILL_ROOT"):
            monkeypatch.setattr(
                skills_mod,
                "DEFAULT_SKILL_ROOT",
                data_root / "skills",
                raising=False,
            )
    except Exception:
        pass

    yield data_root

    # monkeypatch 会还原环境变量；这里再尽力清临时树（Windows 下偶发文件锁则忽略）。
    try:
        shutil.rmtree(data_root, ignore_errors=True)
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """会话结束：清掉仓库内不该长期留下的测试产物。"""
    leftovers = [
        _REPO_ROOT / ".coverage",
        _REPO_ROOT / "htmlcov",
        _REPO_ROOT / "tests" / ".tmp",
        _REPO_ROOT / "output" / "_pytest",
    ]
    for path in leftovers:
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    # __pycache__ 可留；.pytest_cache 由本地忽略，不在此强制删除（加速二次运行）。
    # 但禁止把测试 db 写进仓库 data/ —— 若发现测试命名残留则清掉。
    data_dir = _REPO_ROOT / "data"
    if data_dir.is_dir():
        for pattern in ("*pytest*", "*test_tmp*", ".tmp*"):
            for junk in data_dir.glob(pattern):
                if junk.is_file():
                    try:
                        junk.unlink()
                    except OSError:
                        pass
                else:
                    shutil.rmtree(junk, ignore_errors=True)
