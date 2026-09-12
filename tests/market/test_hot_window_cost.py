"""热库完整性检查应按交易日跳跃，不能随股票行数全表扫描。"""
from datetime import date, timedelta

import pytest

from src.market import MarketStore, hot_window_shallow


@pytest.fixture
def stores(tmp_path):
    with MarketStore(tmp_path / "full.db") as full, MarketStore(tmp_path / "hot.db") as hot:
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(100)]
        for store in (full, hot):
            store.conn.executemany(
                "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, '')",
                [(day,) for day in days],
            )
        hot.conn.executemany(
            "INSERT INTO quotes_daily(trade_date, code, close, source, fetched_at)"
            " VALUES(?, ?, 10, 'fixture', '')",
            [(day, f"{code:06}") for day in days for code in range(500)],
        )
        hot.conn.commit()
        full.conn.commit()
        yield full, hot, days


def test_window_check_does_not_scan_every_stock_row(stores):
    full, hot, _ = stores
    steps = 0

    def budget():
        nonlocal steps
        steps += 100
        return int(steps > 80_000)

    hot.conn.set_progress_handler(budget, 100)
    try:
        assert not hot_window_shallow(full, hot, window_trading_days=100)
    finally:
        hot.conn.set_progress_handler(None, 0)


def test_calendar_cannot_hide_missing_quote_dates(stores):
    full, hot, days = stores
    hot.conn.execute(
        "DELETE FROM quotes_daily WHERE trade_date > ? AND trade_date < ?",
        (days[0], days[20]),
    )
    hot.conn.commit()
    assert len(hot.trading_days()) == 100
    assert hot_window_shallow(full, hot, window_trading_days=100)


def test_empty_quotes_with_populated_calendar_is_shallow(stores):
    full, hot, _ = stores
    hot.conn.execute("DELETE FROM quotes_daily")
    hot.conn.commit()
    assert hot_window_shallow(full, hot, window_trading_days=100)
