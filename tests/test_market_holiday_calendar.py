"""行情库日历覆盖不到的日子按交易所公告休市日程判断：中秋、国庆不再被当成交易日补数。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.market.application.session import build_session_status
from src.market.infrastructure import exchange_calendar
from src.market.infrastructure.exchange_calendar import exchange_open_days

SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def builtin_schedule_only(monkeypatch):
    """只用内置交易所公告日程，不读本机数据目录里的刷新快照。"""
    monkeypatch.setattr(exchange_calendar, "read_calendar", lambda: {})


def db_days(through: str) -> list[str]:
    return exchange_open_days("2026-08-03", through)


def status(now: str, last: str, *, days_through: str | None = None) -> dict:
    return build_session_status(coverage={"rows": 1000, "last_date": last, "first_date": "2026-08-03"},
                                trading_days=db_days(days_through or last),
                                now=datetime.fromisoformat(now))


def test_mid_autumn_is_not_a_trading_day_and_needs_no_backfill():
    s = status("2026-09-25T16:05:00", "2026-09-24")
    assert s["is_trading_day"] is False
    assert s["expected_last_date"] == "2026-09-24"
    assert (s["lag_trading_days"], s["needs_backfill"], s["backfill_kind"]) == (0, False, "none")
    assert s["live_reason"] == "non_trading_day" and s["live_allowed"] is False


def test_holiday_with_lagging_db_backfills_only_real_trading_days():
    s = status("2026-09-25T16:05:00", "2026-09-22")
    assert s["expected_last_date"] == "2026-09-24"
    assert s["lag_trading_days"] == 2
    assert (s["backfill_from"], s["backfill_to"]) == ("2026-09-23", "2026-09-24")


def test_first_day_after_national_day_counts_trading_days_not_calendar_days():
    s = status("2026-10-08T16:05:00", "2026-09-30")
    assert s["is_trading_day"] is True
    assert s["lag_trading_days"] == 1  # 旧逻辑按自然日差报“落后 8 个交易日”
    assert (s["backfill_from"], s["backfill_to"]) == ("2026-10-08", "2026-10-08")


def test_before_close_expects_previous_real_trading_day_even_when_db_lags():
    assert status("2026-10-08T10:00:00", "2026-09-30")["lag_trading_days"] == 0
    s = status("2026-10-08T10:00:00", "2026-09-28")
    # 旧逻辑从行情库日历里找“上一交易日”，缺口日恰好不在里面，于是误判不落后
    assert s["expected_last_date"] == "2026-09-30"
    assert s["lag_trading_days"] == 2
    assert s["live_allowed"] is True


def test_regular_weekday_and_weekend_unchanged():
    s = status("2026-09-24T16:05:00", "2026-09-23")
    assert (s["is_trading_day"], s["lag_trading_days"], s["backfill_to"]) == (True, 1, "2026-09-24")
    weekend = status("2026-09-26T11:00:00", "2026-09-24")
    assert (weekend["is_trading_day"], weekend["expected_last_date"], weekend["needs_backfill"]) == (
        False, "2026-09-24", False)


def test_year_without_published_schedule_falls_back_to_weekdays():
    s = build_session_status(coverage={"rows": 10, "last_date": "2027-03-09"},
                             trading_days=["2027-03-08", "2027-03-09"],
                             now=datetime.fromisoformat("2027-03-10T16:05:00"))
    assert s["is_trading_day"] is True and s["lag_trading_days"] == 1


def test_data_quality_lag_ignores_holidays():
    from src.market.infrastructure.sentinel import _wall_clock_data_lag

    days = db_days("2026-09-24")
    assert _wall_clock_data_lag("2026-09-24", days, now=datetime(2026, 9, 25, 16, 5)) == 0
    assert _wall_clock_data_lag("2026-09-30", db_days("2026-09-30"), now=datetime(2026, 10, 8, 16, 5)) == 1


def test_live_screen_clock_and_auction_window_skip_holidays():
    from src.market.application.screen_live import in_live_screen_clock
    from src.ops.application.skill_watch.auction_confirm import in_auction_window

    assert in_live_screen_clock(datetime(2026, 9, 24, 10, 0, tzinfo=SH)) is True
    assert in_live_screen_clock(datetime(2026, 9, 25, 10, 0, tzinfo=SH)) is False
    assert in_auction_window(datetime(2026, 9, 24, 9, 20, tzinfo=SH)) is True
    assert in_auction_window(datetime(2026, 9, 25, 9, 20, tzinfo=SH)) is False


class FakeStore:
    def __init__(self, days):
        self.days = days

    def trading_days(self):
        return self.days

    def close(self):
        pass


def test_spot_refresh_and_screen_spot_gates_skip_holidays(monkeypatch):
    from src.market.application import screen_spot
    from src.market.infrastructure import sync_spot

    class Holiday(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 25)

    monkeypatch.setattr(sync_spot, "date", Holiday)
    store = FakeStore(db_days("2026-09-24"))
    assert sync_spot._is_current_trading_day(store) is False
    assert screen_spot._is_trading_day(store, date(2026, 9, 25)) is False
    assert screen_spot._is_trading_day(store, date(2026, 9, 28)) is True


def test_paper_quant_gate_blocks_buys_on_holiday():
    from src.ops.application.jobs.paper_quant_support import resolve_trading_day_gate

    store = FakeStore(db_days("2026-09-24"))
    holiday = resolve_trading_day_gate("2026-09-25", market=store)
    assert (holiday["is_trading_day"], holiday["buy_execution_allowed"]) == (False, False)
    reopen = resolve_trading_day_gate("2026-10-08", market=store)
    assert (reopen["is_trading_day"], reopen["calendar_source"]) == (True, "exchange_schedule")
