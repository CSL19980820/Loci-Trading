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


def test_live_window_allows():
    now = datetime(2026, 7, 24, 10, 0)
    days = ["2026-07-22", "2026-07-23", "2026-07-24"]
    s = build_session_status(
        coverage={"rows": 100, "last_date": "2026-07-23", "first_date": "2025-01-01"},
        trading_days=days,
        now=now,
    )
    assert s["live_allowed"] is True
    assert s["needs_backfill"] is True  # last_date behind today trading day
