"""ops 测试夹具：短缓存不得跨用例污染。"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_skill_watch_short_caches() -> None:
    from src.ops.application.jobs.paper_quant_support import clear_market_gate_cache
    from src.ops.application.skill_watch.market_regime import clear_market_snapshot_cache

    clear_market_snapshot_cache()
    clear_market_gate_cache()
    yield
    clear_market_snapshot_cache()
    clear_market_gate_cache()



@pytest.fixture(autouse=True)
def _freeze_out_of_tail_protect_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认把时钟钉在尾盘保护窗之外。

    `skip_reason_for_intraday_sync` 会在工作日 14:35-15:00 把 kind="sync" 判成
    skipped。大量用例只是**顺手**拿 sync 当个假任务跑生命周期,并不关心尾盘窗;
    不钉时钟的话它们在每天那 25 分钟里集体变红、过了 15:00 又自己变绿——
    这种红既不能证明代码坏了,也挡不住真的坏,只会训练人忽略红灯。

    真正测这个窗口的用例(`test_market_gate.py`)一律**显式传 now**,走的是另一条
    分支,不受这里影响。
    """
    from src.ops.application.jobs import market_gate

    real = market_gate.in_tail_screen_protect_window

    def _outside_window(now=None):
        # 只接管「没给 now」这一种:给了 now 说明用例在有意测窗口。
        return False if now is None else real(now)

    monkeypatch.setattr(market_gate, "in_tail_screen_protect_window", _outside_window)
