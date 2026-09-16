"""ops 测试夹具：短缓存不得跨用例污染。"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _verified_notification_calendar(monkeypatch, request):
    """非日历用例固定在已验证交易日，避免测试随真实周末或外部缓存漂移。"""
    if request.node.path.name == 'test_calendar_silence.py':
        return
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.market.infrastructure import exchange_calendar
    from src.market.domain.exchange_schedule import HOLIDAYS
    from src.ops.application import notify_calendar
    monkeypatch.setattr(exchange_calendar, 'read_calendar', lambda: {'checked_at': time.time(), 'years': {str(y): v for y, v in HOLIDAYS.items()}})
    real = notify_calendar.notification_silence_reason
    monkeypatch.setattr(notify_calendar, 'notification_silence_reason', lambda now=None: real(now or datetime(2026,9,14,10,tzinfo=ZoneInfo('Asia/Shanghai'))))


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


@pytest.fixture(autouse=True)
def _reset_notify_global_state() -> None:
    """通知侧的三张进程级表：限流指纹、企微令牌桶、社区信号去重。

    它们都是模块级全局，不清就会跨用例互相顶掉——而且症状是「某个用例单跑绿、
    全量跑红」，最难查的那一类。加限流之后受影响的用例比以前多得多，所以放在
    ops 的公共 conftest 里，而不是让每个通知测试文件各写一遍。
    """
    from src.ops.application.notify_registry import reset_rate_limiter
    from src.ops.application.notify_send_queue import reset_rate_limits
    from src.ops.application.notify_subscribers import reset_signal_dedup

    reset_rate_limiter()
    reset_rate_limits()
    reset_signal_dedup()
    yield
    reset_rate_limiter()
    reset_rate_limits()
    reset_signal_dedup()
