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
    "LOCI_CONFIG_JSON",
    "PALACE_DATA_DIR",
    "PALACE_DB",
    "PALACE_MARKET_DB",
    "PALACE_MARKET_HOT_DB",
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
    "LOCI_OBSERVABILITY",
    "LOCI_OBSERVABILITY_OTEL",
    "LOCI_OBSERVABILITY_EXPOSE",
    "LOCI_MARKET_DUCKDB",
    "LOCI_MARKET_POLARS",
    "LOCI_RESEARCH_POLARS",
    "LOCI_MCP_TOOL_TIMEOUT_SEC",
    # 行情主源（通达信）与线路并发的运行时开关：开发机导出过就会让
    # 同步测试在「另一套服务器名单 / 另一档并发」上跑绿。
    "LOCI_TDX_SERVERS",
    "LOCI_ADAPTER_CONCURRENCY",
    "LOCI_CROSS_CHECK_EVERY",
    "LOCI_EM_INDUSTRY_TTL_DAYS",
    "LOCI_SKIP_EM_INDUSTRY",
    "LOCI_MARKET_WRITE_WAIT_SEC",
    # 这两条经 write_lock._env_seconds 间接读取，正则扫不到（它只认
    # environ.get("字面量")），但导出值一样会改锁的行为，必须一起清。
    "LOCI_MARKET_WRITE_STUCK_SEC",
    "LOCI_MARKET_WRITE_DEAD_PID_GRACE_SEC",
    # 下面这些漏掉过：开发机导出过就会让整套测试在「另一条实现」上跑绿。
    # LOCI_BACKTEST_FAST 会让回测套走旁路引擎，
    # LOCI_PAPER_ALLOW_BYPASS_GATES 会让闸门测试在闸门已被绕过的状态下通过。
    "LOCI_BACKTEST_FAST",
    "LOCI_PAPER_ALLOW_BYPASS_GATES",
    "LOCI_SKIP_EM_INDUSTRY",
    "LOCI_SKIP_WEBVIEW_CACHE_PURGE",
    "LOCI_PURGE_WEBVIEW_CACHE",
    "LOCI_WEBVIEW_DISABLE_GPU",
    "PALACE_WRITE_TOKEN_ISSUED_AT",
    "PALACE_STATIC_DIR",
    # v2 群龙：身份 / 多租户 / 第三方登录 / 邮件。导出过任何一条都会让
    # 「首启种子出哪个管理员」「登录页显示哪些 provider」在另一套配置上跑绿。
    "LOCI_IDENTITY_DB",
    "LOCI_COMMUNITY_DB",
    "LOCI_ADMIN_USERNAME",
    "LOCI_ADMIN_PASSWORD",
    "LOCI_ADMIN_EMAIL",
    "LOCI_AUTH_PROVIDERS",
    # 自助注册开关：默认关。用例若开了它必须还原，否则后面的用例会以为站点开放注册。
    "LOCI_ALLOW_SIGNUP",
    "LOCI_PUBLIC_BASE_URL",
    "LOCI_WECHAT_APPID",
    "LOCI_WECHAT_SECRET",
    "LOCI_QQ_APPID",
    "LOCI_QQ_APPKEY",
    "LOCI_SMTP_HOST",
 "LOCI_SMTP_PORT",
    "LOCI_SMTP_SSL",
  "LOCI_SMTP_USER",
  "LOCI_SMTP_PASSWORD",
    "LOCI_SMTP_FROM",
    # 多租户调度开关：导出过就会让「子租户任务到底装不装」在另一套配置上跑绿。
    "LOCI_ENSURE_TENANT_JOBS",
 "LOCI_TENANT_JOB_CONCURRENCY",
    "LOCI_MAX_SCHEDULED_TENANTS",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _freeze_live_screen_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认关掉盘中实时 overlay，避免选股用例在 09:15–15:00 真去打行情源。

    显式传入 ``now=`` 的用例走真实时钟判断，不受这里影响。
    """
    from src.market.application import screen_live
    import src.market as market

    real_clock = screen_live.in_live_screen_clock
    real_should = screen_live.should_overlay_live

    def _clock(now=None):
        return False if now is None else real_clock(now)

    def _should(trade_date=None, *, now=None):
        return False if now is None else real_should(trade_date, now=now)

    monkeypatch.setattr(screen_live, "in_live_screen_clock", _clock)
    monkeypatch.setattr(screen_live, "should_overlay_live", _should)
    monkeypatch.setattr(market, "in_live_screen_clock", _clock)
    monkeypatch.setattr(market, "should_overlay_live", _should)
    yield
    screen_live.reset_live_spot_cache()


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
    # loci.config.json 里存着 data_dir 与线路策略。不隔离它，测试既会读到开发机
    # 的真实配置（同一套用例在不同机器上结论不同），也可能被一次忘了 mock 的
    # save_config 改写掉用户的数据目录。
    monkeypatch.setenv("LOCI_CONFIG_JSON", str(tmp_path / "loci.config.json"))
    monkeypatch.setenv("PALACE_DB", str(data_root / "palace.db"))
    monkeypatch.setenv("PALACE_MARKET_DB", str(data_root / "market.db"))
    monkeypatch.setenv("PALACE_MARKET_HOT_DB", str(data_root / "market_hot.db"))
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

    # AkShare 目录在进程内缓存一份反射结果；跨用例复用会让注入的假目录串味。
    try:
        from src.market.infrastructure.akshare_tools import clear_catalog_cache

        clear_catalog_cache()
    except Exception:
        pass

    # Screen skill 引擎注册表同样是模块级全局（现在按租户分片）：某个用例注册的
    # 自定义 slug 会跟着进程流进下一个测试模块（tests/app 建的 python-screen 曾被
    # tests/strategy 的目录断言看到）。整张分片表快照 + 还原，让结果不依赖模块
    # 执行顺序，也不让 A 租户的分片漏进下一个用例。
    screen_state = None
    try:
        from src.strategy.application import catalog as strategy_catalog

        screen_state = strategy_catalog.snapshot_screen_state()
    except Exception:
        strategy_catalog = None

    yield data_root

    if strategy_catalog is not None:
        try:
            strategy_catalog.restore_screen_state(screen_state)
        except Exception:
            pass

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
