"""Hot preparation keeps exact quote/receipt repairs with one orphan sweep."""
from __future__ import annotations

import pytest

from src.market import MarketStore
from src.market.infrastructure import store_hot


DAYS = [f"2024-01-{day:02d}" for day in range(2, 10)]


@pytest.fixture
def mirrors(tmp_path):
    with MarketStore(tmp_path / "full.db") as full, MarketStore(
        tmp_path / "hot.db", keep_receipt_index=True,
    ) as hot:
        full.upsert_instruments([
            {"code": "600001", "name": "测试", "market": "sh", "board": "main"},
        ])
        for day in DAYS:
            full.conn.execute(
                "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,"
                "source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (day, "600001", 10., 11., 9., 10., 1000., "tdx", day, day),
            )
            full.conn.execute(
                "INSERT INTO trading_calendar VALUES(?,?)", (day, day),
            )
            full.conn.execute(
                "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,"
                "state,generated_at) VALUES(?,?,?,?,?,?)",
                (day, "600001", "hist_daily", "tdx", "ok", day),
            )
            full.conn.execute(
                "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state)"
                " VALUES(?,?,?,?)", (day, 1, "tdx", "ok"),
            )
        full.conn.commit()
        store_hot.mirror_to_hot(full, hot, window_trading_days=4)
        yield full, hot


def assert_window_matches(full, hot):
    cutoff = DAYS[-4]
    for table in ("quotes_daily", "trading_calendar"):
        expected = [tuple(row) for row in full.conn.execute(
            f"SELECT * FROM {table} WHERE trade_date >= ? ORDER BY trade_date", (cutoff,),
        )]
        actual = [tuple(row) for row in hot.conn.execute(
            f"SELECT * FROM {table} ORDER BY trade_date",
        )]
        assert actual == expected
    ids = [row[0] for row in hot.conn.execute(
        "SELECT DISTINCT receipt_id FROM quotes_daily WHERE receipt_id IS NOT NULL",
    )]
    placeholders = ",".join("?" for _ in ids)
    for table in ("source_route_receipts", "source_route_attempts"):
        expected = [tuple(row) for row in full.conn.execute(
            f"SELECT * FROM {table} WHERE receipt_id IN ({placeholders}) ORDER BY receipt_id",
            ids,
        )]
        actual = [tuple(row) for row in hot.conn.execute(
            f"SELECT * FROM {table} ORDER BY receipt_id",
        )]
        assert actual == expected


@pytest.mark.parametrize("rebuild", [False, True])
def test_each_mirror_sweeps_once_after_copy_and_trim(mirrors, monkeypatch, rebuild):
    full, hot = mirrors
    # Includes pre-existing orphan metadata, an orphan attempt without metadata,
    # and a stale quote whose receipt only becomes orphaned at the final trim.
    hot.conn.execute(
        "INSERT INTO source_route_receipts(receipt_id,code,lane,state,generated_at)"
        " VALUES('orphan','600001','hist_daily','ok','old')",
    )
    hot.conn.executemany(
        "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state)"
        " VALUES(?,1,'tdx','ok')", [("orphan",), ("missing-metadata",)],
    )
    hot.conn.execute(
        "INSERT INTO quotes_daily(trade_date,code,close,receipt_id,fetched_at)"
        " VALUES(?,'600001',10,'old-linked','old')", (DAYS[0],),
    )
    hot.conn.execute(
        "INSERT INTO source_route_receipts(receipt_id,code,lane,state,generated_at)"
        " VALUES('old-linked','600001','hist_daily','ok','old')",
    )
    hot.conn.commit()
    sweeps = []
    original = store_hot._purge_orphan_receipts

    def count_sweep(cursor):
        sweeps.append(1)
        original(cursor)

    monkeypatch.setattr(store_hot, "_purge_orphan_receipts", count_sweep)
    mirror = store_hot.mirror_to_hot if rebuild else store_hot.mirror_recent_to_hot
    mirror(full, hot, window_trading_days=4)
    assert sweeps == [1]
    assert_window_matches(full, hot)


def test_unchanged_quotes_still_refresh_receipt_corrections(mirrors):
    full, hot = mirrors
    full.conn.execute(
        "UPDATE source_route_receipts SET selected_source='corrected' WHERE receipt_id=?",
        (DAYS[-1],),
    )
    full.conn.execute(
        "UPDATE source_route_attempts SET error='corrected metadata' WHERE receipt_id=?",
        (DAYS[-1],),
    )
    full.conn.commit()
    result = store_hot.mirror_recent_to_hot(full, hot, buffer_trading_days=2, window_trading_days=4)
    assert result["quotes"] == 0
    assert_window_matches(full, hot)


def test_bypass_quote_edits_and_hot_gaps_are_repaired(mirrors):
    full, hot = mirrors
    # Direct SQL deliberately does not bump a revision: value comparison remains
    # the source of truth for both edits and missing quote/calendar rows.
    full.conn.execute(
        "UPDATE quotes_daily SET close=10.5,receipt_id=? WHERE trade_date=?",
        (DAYS[-1], DAYS[-2]),
    )
    full.conn.commit()
    hot.conn.execute("DELETE FROM quotes_daily WHERE trade_date=?", (DAYS[-3],))
    hot.conn.execute("DELETE FROM trading_calendar WHERE trade_date=?", (DAYS[-3],))
    hot.conn.commit()
    result = store_hot.mirror_recent_to_hot(full, hot, window_trading_days=4)
    assert result["quotes"] > 0
    assert_window_matches(full, hot)


def test_failed_quote_copy_keeps_the_previous_complete_window(mirrors, monkeypatch):
    full, hot = mirrors
    tables = ("quotes_daily", "trading_calendar", "source_route_receipts", "source_route_attempts")
    before = {table: [tuple(row) for row in hot.conn.execute(f"SELECT * FROM {table}")]
              for table in tables}
    full.conn.execute("UPDATE quotes_daily SET close=10.5 WHERE trade_date=?", (DAYS[-1],))
    full.conn.commit()

    def failed_copy(source, cursor, insert_sql, batch_rows=None):
        row = source.fetchone()
        cursor.execute(insert_sql, tuple(row))
        raise RuntimeError("copy interrupted")

    monkeypatch.setattr(store_hot, "_stream_copy", failed_copy)
    with pytest.raises(RuntimeError, match="copy interrupted"):
        store_hot.mirror_recent_to_hot(full, hot, window_trading_days=4)
    after = {table: [tuple(row) for row in hot.conn.execute(f"SELECT * FROM {table}")]
             for table in tables}
    assert after == before
