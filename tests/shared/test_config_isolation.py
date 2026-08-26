"""配置文件与环境变量的测试隔离。

这两条是「审计结论本身可不可信」的地基：配置不隔离，同一套用例在不同机器上
结论不同；环境变量漏清，整套测试可能跑在另一条实现上还全绿。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.shared import paths
from tests.conftest import _ENV_KEYS

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_READ = re.compile(
    r"""environ(?:\.get\(\s*|\[)["'](LOCI_[A-Z0-9_]+|PALACE_[A-Z0-9_]+)["']"""
)


def test_config_path_follows_the_test_override() -> None:
    """conftest 已把 LOCI_CONFIG_JSON 指向临时目录。"""
    resolved = paths.config_path()

    assert resolved.name == "loci.config.json"
    assert _REPO_ROOT not in resolved.parents, "测试不得读写仓库里的真实配置"


def test_save_config_round_trips_under_the_override() -> None:
    paths.save_config({"lane_routes": {"hist_daily": {"mode": "auto"}}})

    assert paths.load_config()["lane_routes"]["hist_daily"]["mode"] == "auto"


def test_save_config_leaves_no_half_written_file() -> None:
    """原地截断覆盖崩在中途 → load_config 静默返回 {}，设置无声重置。"""
    paths.save_config({"setup_done": True})
    target = paths.config_path()

    assert json.loads(target.read_text(encoding="utf-8"))["setup_done"] is True
    assert not target.with_name(f"{target.name}.tmp").exists()


def test_a_real_config_on_disk_is_not_visible_to_tests(tmp_path: Path) -> None:
    """开发机上的 lane_routes / wudao 开关不得渗进测试结论。"""
    assert paths.load_config().get("data_dir") is None


def _env_keys_used_in_src() -> set[str]:
    found: set[str] = set()
    for path in (_REPO_ROOT / "src").rglob("*.py"):
        found.update(_ENV_READ.findall(path.read_text(encoding="utf-8", errors="replace")))
    return found


def test_every_runtime_env_switch_is_reset_between_tests() -> None:
    """新增环境开关却忘了加进 conftest，会让本机导出值静默改变测试行为。"""
    missing = sorted(_env_keys_used_in_src() - set(_ENV_KEYS))

    assert not missing, (
        f"这些环境变量被 src/ 读取但没有在 tests/conftest.py 的 _ENV_KEYS 里清理：{missing}"
    )


@pytest.mark.parametrize(
    "key", ["LOCI_BACKTEST_FAST", "LOCI_PAPER_ALLOW_BYPASS_GATES", "LOCI_CONFIG_JSON"]
)
def test_the_switches_that_silently_change_which_code_runs_are_covered(key: str) -> None:
    assert key in _ENV_KEYS
