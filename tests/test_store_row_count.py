from __future__ import annotations

import sqlite3

import pandas as pd

from src.market import MarketStore
from src.market.infrastructure.store_row_count import (
    rebuild_quote_row_count,
    read_base,
)


def _store_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "CREATE TABLE quotes_daily(trade_date TEXT NOT NULL, code TEXT NOT NULL,"
        "PRIMARY KEY(trade_date, code)) WITHOUT ROWID;"
    )
    conn.executemany(
        "INSERT INTO quotes_daily(trade_date, code) VALUES (?, ?)",
        [("2024-01-01", "000001"), ("2024-01-02", "000001"),
         ("2024-01-02", "000002")],
    )
    return conn


def test_rebuild_quote_row_count_replaces_corrupt_cache():
    conn = _store_connection()
    try:
        conn.execute(
            "INSERT INTO meta VALUES ('quotes_daily_rows_v2', '2024-01-02|881490958', '')"
        )
        result = rebuild_quote_row_count(conn)
        assert result == {
            "base_date": "2024-01-02",
            "base_rows": 1,
            "tail_rows": 2,
            "total_rows": 3,
        }
        assert read_base(conn) == ("2024-01-02", 1)
    finally:
        conn.close()


def test_frame_upsert_does_not_count_dates_ignored_by_history_floor(tmp_path):
    frame = pd.DataFrame([
        {"date": day, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0}
        for day in ("2022-12-30", "2023-01-03", "2023-01-04")
    ])
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.execute(
            "CREATE TRIGGER quotes_daily_floor BEFORE INSERT ON quotes_daily "
            "WHEN NEW.trade_date < '2023-01-01' BEGIN SELECT RAISE(IGNORE); END"
        )
        store.conn.commit()
        assert store.upsert_quotes("000001", frame, source="tdx") == 2
        assert store.coverage()["rows"] == 2
        for _ in range(3):
            assert store.upsert_quotes("000001", frame, source="tdx") == 2
            assert store.coverage()["rows"] == 2
        assert store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0] == 2
        assert store.conn.execute(
            "SELECT COUNT(*) FROM trading_calendar WHERE trade_date < '2023-01-01'"
        ).fetchone()[0] == 0


def test_new_market_schema_does_not_create_obsolete_attempt_index(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        assert store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_source_attempts_source",),
        ).fetchone() is None


def test_stricter_database_floor_never_counts_ignored_rows(tmp_path):
    frame = pd.DataFrame([
        {"date": day, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0}
        for day in ("2023-01-03", "2024-01-02")
    ])
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.execute(
            "CREATE TRIGGER quotes_daily_floor BEFORE INSERT ON quotes_daily "
            "WHEN NEW.trade_date < '2024-01-01' BEGIN SELECT RAISE(IGNORE); END"
        )
        store.conn.commit()
        assert store.upsert_quotes("000001", frame, source="tdx") == 1
        assert store.coverage()["rows"] == 1
        for _ in range(3):
            assert store.upsert_quotes("000001", frame, source="tdx") == 1
            assert store.coverage()["rows"] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM trading_calendar WHERE trade_date < '2024-01-01'"
        ).fetchone()[0] == 0
