"""尾盘筛选只能使用已声明的交易日窗口，休市/补跑不得产生候选。"""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from src.ops.application.eod_catchup import jobs_due_for_eod_catchup
from src.ops.application.jobs.context import JobError, JobSkipped
from src.ops.application.jobs.screen import execute_screen
from src.ops.application.jobs.screen_schedule_guard import guard_screen_schedule

TZ = ZoneInfo("Asia/Shanghai")
CONFIG = {
    "strategy": "test-tail",
    "snapshot_time": "14:50",
    "snapshot_grace_minutes": 2,
    "trading_days_only": True,
    "catch_up": False,
}


def context(days: list[str]) -> SimpleNamespace:
    @contextmanager
    def market():
        yield SimpleNamespace(trading_days=lambda: days, list_instruments=lambda **_: [])
    return SimpleNamespace(market=market, palace_db="unused-test-palace.db")


def test_trading_window_records_shanghai_time() -> None:
    meta = guard_screen_schedule(
        CONFIG, context(["2026-09-11", "2026-09-14"]),
        now=datetime(2026, 9, 11, 6, 51, tzinfo=timezone.utc),
    )
    assert meta["checked_at"] == "2026-09-11T14:51:00+08:00"
    assert meta["calendar_source"] == "market_db"
    assert meta["window_end"] == "2026-09-11T14:52:00+08:00"


@pytest.mark.parametrize("minute,second,allowed", [(24, 59, False), (25, 0, True), (26, 59, True), (27, 0, False)])
def test_auction_0925_window(minute, second, allowed):
    config = {**CONFIG, "snapshot_time": "09:25"}
    stamp = datetime(2026, 9, 14, 9, minute, second)
    if allowed:
        result = guard_screen_schedule(config, context(["2026-09-14"]), now=stamp)
        assert result["snapshot_time"] == "09:25"
    else:
        with pytest.raises(JobSkipped):
            guard_screen_schedule(config, context(["2026-09-14"]), now=stamp)


@pytest.mark.parametrize("hour,minute,second", [(14, 49, 59), (14, 52, 0), (15, 40, 0)])
def test_outside_window_skips_before_reading_market(hour: int, minute: int, second: int) -> None:
    ctx = SimpleNamespace(market=Mock(side_effect=AssertionError("must not load market")))
    with pytest.raises(JobSkipped, match="快照窗口.*实际检查时间"):
        guard_screen_schedule(CONFIG, ctx, now=datetime(2026, 9, 11, hour, minute, second))
    ctx.market.assert_not_called()


@pytest.mark.parametrize(
    "day,days,reason",
    [
        ("2026-09-12", [], "周末"),
        ("2026-10-01", ["2026-09-30", "2026-10-09"], "交易日历休市"),
        ("2026-09-11", [], "未明确覆盖"),
        ("2026-09-11", ["2026-09-10"], "未明确覆盖"),
    ],
)
def test_nontrading_or_unknown_calendar_fails_closed(day: str, days: list[str], reason: str) -> None:
    with pytest.raises(JobSkipped, match=reason):
        guard_screen_schedule(CONFIG, context(days), now=datetime.fromisoformat(day + "T14:50:00"))


def test_calendar_read_failure_skips_without_exposing_error_contents() -> None:
    ctx = SimpleNamespace(market=Mock(side_effect=RuntimeError("private database path")))
    with pytest.raises(JobSkipped, match="交易日历读取失败") as exc:
        guard_screen_schedule(CONFIG, ctx, now=datetime(2026, 9, 11, 14, 50))
    assert "private database path" not in str(exc.value)


def test_historical_date_cannot_replace_live_snapshot() -> None:
    with pytest.raises(JobSkipped, match="不允许使用历史日期"):
        guard_screen_schedule({**CONFIG, "date": "2026-09-10"}, context([]), now=datetime(2026, 9, 11, 14, 50))


@pytest.mark.parametrize("changes", [{"snapshot_time": "25:00"}, {"snapshot_grace_minutes": 0}, {"snapshot_time": "15:30"}])
def test_invalid_snapshot_configuration_fails(changes: dict) -> None:
    with pytest.raises(JobError):
        guard_screen_schedule({**CONFIG, **changes}, context([]), now=datetime(2026, 9, 11, 14, 50))


def test_legacy_job_is_unchanged_and_reads_no_calendar() -> None:
    assert guard_screen_schedule({}, SimpleNamespace(), now=datetime(2026, 9, 12, 20)) == {}


def test_execute_screen_stops_before_engine_or_candidate_write(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.ops.application.jobs.screen_schedule_guard as module
    import src.strategy

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 11, 15, 30, tzinfo=TZ)

    monkeypatch.setattr(module, "datetime", Clock)
    compute = Mock(side_effect=AssertionError("must not screen"))
    monkeypatch.setattr(src.strategy, "screen", compute)
    with pytest.raises(JobSkipped, match="禁止用盘后日 K 补跑"):
        execute_screen({**CONFIG, "record_candidates": True}, SimpleNamespace())
    compute.assert_not_called()


def test_catchup_opt_out_preserves_other_jobs() -> None:
    base = {"kind": "screen", "cron": "50 14 * * mon-fri", "enabled": True, "last_run_at": ""}
    rows = [
        {**base, "id": "tail", "config": {"catch_up": False}},
        {**base, "id": "legacy"},
        {**base, "id": "explicit", "config": {"catch_up": True}},
    ]
    due = jobs_due_for_eod_catchup(rows, last_trading_day="2026-09-11", now=datetime(2026, 9, 11, 16, tzinfo=TZ))
    assert {row["id"] for row in due} == {"legacy", "explicit"}


def test_screen_finishing_after_deadline_does_not_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.market
    import src.strategy
    import src.strategy.application.persist as persistence
    import src.ops.application.jobs.screen_schedule_guard as guard_module

    checks = Mock(side_effect=[
        {"checked_at": "2026-09-11T14:50:00+08:00"},
        {"checked_at": "2026-09-11T14:50:10+08:00"},
        JobSkipped("快照窗口之外；实际检查时间 2026-09-11T14:52:01+08:00"),
    ])
    monkeypatch.setattr(guard_module, "guard_screen_schedule", checks)
    monkeypatch.setattr(src.market, "should_overlay_live", lambda _: True)
    monkeypatch.setattr(src.strategy, "get", lambda _: SimpleNamespace(requires_full_history=True))
    compute = Mock(return_value=src.strategy.ScreenResult(
        strategy_slug="test-tail", trade_date="2026-09-11", picks=[{"code": "000001"}],
    ))
    monkeypatch.setattr(src.strategy, "screen", compute)
    persist = Mock(side_effect=AssertionError("late result must not be persisted"))
    monkeypatch.setattr(persistence, "persist_screen_candidates", persist)

    with pytest.raises(JobSkipped, match="14:52:01"):
        execute_screen({**CONFIG, "record_candidates": True}, context([]))
    assert checks.call_count == 3
    compute.assert_called_once()
    persist.assert_not_called()


@pytest.mark.parametrize("record_candidates", [True, False])
def test_postprocessing_crossing_deadline_is_checked_before_persist_or_return(
    monkeypatch: pytest.MonkeyPatch, record_candidates: bool,
) -> None:
    import src.market
    import src.strategy
    import src.strategy.application.persist as persistence
    import src.ops.application.jobs.screen_schedule_guard as guard_module

    clock = {"now": datetime(2026, 9, 11, 14, 51, 59, tzinfo=TZ)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    def slow_names(**kwargs):
        clock["now"] = datetime(2026, 9, 11, 14, 52, 1, tzinfo=TZ)
        return [{"code": "300084", "name": "fixture"}]

    @contextmanager
    def market():
        yield SimpleNamespace(trading_days=lambda: ["2026-09-11"], list_instruments=slow_names)

    ctx = SimpleNamespace(market=market, palace_db="unused-test-palace.db")
    calls = 0

    def get_engine(slug):
        nonlocal calls
        calls += 1
        if calls == 2 and not record_candidates:
            # 不入库时不查名字；模拟筛选后的策略名称解析耗时。
            clock["now"] = datetime(2026, 9, 11, 14, 52, 1, tzinfo=TZ)
        return SimpleNamespace(requires_full_history=True, name="fixture")

    monkeypatch.setattr(guard_module, "datetime", Clock)
    checks = Mock(wraps=guard_module.guard_screen_schedule)
    monkeypatch.setattr(guard_module, "guard_screen_schedule", checks)
    monkeypatch.setattr(src.market, "should_overlay_live", lambda _: True)
    monkeypatch.setattr(src.strategy, "get", get_engine)
    compute = Mock(return_value=src.strategy.ScreenResult(
        strategy_slug="test-tail", trade_date="2026-09-11", picks=[{"code": "300084"}],
    ))
    monkeypatch.setattr(src.strategy, "screen", compute)
    persist = Mock(side_effect=AssertionError("must not persist after deadline"))
    monkeypatch.setattr(persistence, "persist_screen_candidates", persist)
    with pytest.raises(JobSkipped, match="14:52:01"):
        execute_screen({**CONFIG, "record_candidates": record_candidates}, ctx)
    assert checks.call_count == 4
    compute.assert_called_once()
    persist.assert_not_called()
