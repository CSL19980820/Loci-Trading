"""Unit tests for market session gate."""
from __future__ import annotations

from datetime import datetime

from src.market.application.session import build_session_status


def test_weekend_no_live():
    # 2026-07-25 Saturday
    now = datetime(2026, 7, 25, 10, 30)
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-24", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["is_trading_day"] is False
    assert s["live_allowed"] is False
    assert s["needs_backfill"] is False
    assert s["last_trading_day"] == "2026-07-24"


def test_weekend_stale_needs_catchup():
    now = datetime(2026, 7, 26, 11, 0)  # Sunday, last trading Fri 24
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-22", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["needs_backfill"] is True
    assert s["backfill_kind"] == "catchup"
    assert s["lag_trading_days"] >= 1
    assert s["coverage_last_date"] == "2026-07-22"
    assert s["backfill_from"] == "2026-07-23"
    assert s["backfill_to"] == "2026-07-24"


def test_empty_backfill_window_has_target_only():
    # 盘中空库：目标只到上一已收盘日，不催补「今日」
    now = datetime(2026, 7, 24, 10, 0)
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 0, "last_date": "", "first_date": ""},
        trading_days=days,
        now=now,
    )
    assert s["backfill_kind"] == "empty"
    assert s["backfill_from"] is None
    assert s["backfill_to"] == "2026-07-23"
    assert s["expected_last_date"] == "2026-07-23"


def test_after_close_db_current_no_live():
    now = datetime(2026, 7, 24, 15, 30)  # Fri after close
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-24", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["is_trading_day"] is True
    assert s["live_allowed"] is False
    assert s["db_is_current"] is True
    assert s["live_reason"] == "after_close_db_current"


def test_live_window_allows_without_catching_today():
    """盘中库已有昨收日线：可刷实时，但不应触发补「今日」日 K。"""
    now = datetime(2026, 7, 24, 10, 0)
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-23", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["live_allowed"] is True
    assert s["expected_last_date"] == "2026-07-23"
    assert s["needs_backfill"] is False
    assert s["backfill_kind"] == "none"


def test_before_close_does_not_expect_today():
    """盘前/盘中（含凌晨）：库到昨收即视为日 K 新鲜，不补未结束的今日。"""
    now = datetime(2026, 7, 29, 0, 56)
    days = ["2026-07-27", "2026-07-28", "2026-07-29"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-28", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["is_trading_day"] is True
    assert s["expected_last_date"] == "2026-07-28"
    assert s["needs_backfill"] is False
    assert s["backfill_to"] is None


def test_after_close_stale_expects_today():
    """收盘后库仍停在昨收：应补今日日线。"""
    now = datetime(2026, 7, 29, 15, 30)
    days = ["2026-07-27", "2026-07-28", "2026-07-29"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-28", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["needs_backfill"] is True
    assert s["expected_last_date"] == "2026-07-29"
    assert s["backfill_from"] == "2026-07-29"
    assert s["backfill_to"] == "2026-07-29"
    assert s["live_reason"] == "after_close_db_stale"


def test_stale_calendar_weekday_not_mislabelled_as_holiday():
    """日历最大日落后于今天时，工作日不得误报「非交易日」。"""
    now = datetime(2026, 7, 28, 23, 40)  # Tue after close; calendar stuck at Fri
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-24", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["is_trading_day"] is True
    assert s["live_allowed"] is False
    assert s["live_reason"] == "after_close_db_stale"
    assert s["live_reason"] != "non_trading_day"


def test_calendar_covers_today_but_holiday():
    """日历已覆盖今天及之后，且今天不在日历中 → 真休市。"""
    now = datetime(2026, 10, 1, 10, 0)  # National Day
    days = ["2026-09-30", "2026-10-09", "2026-10-10"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-09-30", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["is_trading_day"] is False
    assert s["live_reason"] == "non_trading_day"


def test_board_phase_names_every_intraday_segment():
    """大屏时段词表。**午休必须是午休**——12:00 说「已收盘」正是用户拍下来的那张图。"""
    from src.market.application.session import board_phase

    cases = {
        "09:00": "pre_open",
        "09:20": "pre_market",
        "09:29": "pre_market",
        "10:30": "morning",
        "12:00": "noon_break",
        "13:30": "afternoon",
        "14:58": "closing_auction",
        "15:30": "closed",
    }
    for text, expected in cases.items():
        hour, minute = (int(part) for part in text.split(":"))
        assert board_phase(datetime(2026, 8, 31, hour, minute)) == expected, text


def test_board_session_adds_phase_and_live_to_the_gate():
    """SSE / REST 共用的 session 形状：闸门键之外还得有 phase 与 live。"""
    from src.market.application.session import board_session

    gate = {"live_allowed": True, "is_trading_day": True}
    morning = board_session(gate, now=datetime(2026, 8, 31, 10, 30))
    assert morning["phase"] == "morning" and morning["live"] is True

    # 午休：闸门还开着（in_live_clock 判到 15:00），但没在撮合。
    noon = board_session(gate, now=datetime(2026, 8, 31, 12, 0))
    assert noon["phase"] == "noon_break" and noon["live"] is False

    # 非交易日：时钟不知道今天休市，闸门知道 —— 一律 closed。
    weekend = board_session(
        {"live_allowed": False, "is_trading_day": False}, now=datetime(2026, 8, 29, 10, 30)
    )
    assert weekend["phase"] == "closed" and weekend["live"] is False


def test_board_session_survives_a_missing_gate():
    """闸门读不出来时只能保守：相位照报，live 判 False，不是整块崩掉。"""
    from src.market.application.session import board_session

    degraded = board_session(None, now=datetime(2026, 8, 31, 10, 30))
    assert degraded["phase"] == "morning"
    assert degraded["live"] is False
