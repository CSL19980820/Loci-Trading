"""Range reuse must be indistinguishable from independent daily SQL reads."""
from __future__ import annotations

from contextlib import nullcontext
import sqlite3

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from src.market.infrastructure.store_panel import MarketPanelMixin
from src.market.infrastructure.store_panel_window import panel_read_window


class _Store(MarketPanelMixin):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCI_MARKET_DUCKDB", raising=False)
    monkeypatch.delenv("LOCI_MARKET_POLARS", raising=False)
    conn = sqlite3.connect(tmp_path / "panel.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript('''
        CREATE TABLE quotes_daily (
            trade_date TEXT, code TEXT, open REAL, high REAL, low REAL, close REAL,
            volume REAL, amount REAL, turnover REAL, outstanding_share REAL,
            PRIMARY KEY(trade_date, code));
        CREATE TABLE adjust_factors (trade_date TEXT, code TEXT, hfq_factor REAL);
        INSERT INTO quotes_daily VALUES
            ('2026-01-01','000001',10,11,9,10,100,1000,0.1,10000),
            ('2026-01-02','000001',20,22,19,21,200,4200,0.2,20000),
            ('2026-01-02','600519',8,9,7,NULL,0,0,NULL,NULL),
            ('2026-01-03','600519',11,12,10,11,300,3300,0.3,30000),
            ('2026-01-04','000001',NULL,NULL,NULL,22,210,4620,NULL,NULL),
            ('2026-01-05','600519',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
        INSERT INTO adjust_factors VALUES
            ('2025-12-01','600519',1),('2026-01-03','600519',2),
            ('2026-01-08','000001',3);
    ''')
    yield _Store(conn)
    conn.close()


def _equal(actual, expected):
    assert list(actual) == list(expected)
    for field in expected:
        assert_frame_equal(actual[field], expected[field], check_exact=True)


@pytest.mark.parametrize("fields", [("close",), ("volume", "close", "open", "close"),
                                    ("volume",), ("turnover", "amount")])
@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
@pytest.mark.parametrize("min_bars", [0, 2, 10])
def test_rolling_windows_and_changing_universes_are_exact(store, fields, adjust, min_bars):
    requests = [
        dict(codes=None, start="2026-01-01", end="2026-01-02"),
        dict(codes=["sh600519"], start="2026-01-02", end="2026-01-03"),
        dict(codes=["000001", "600519", "000001", "000009"],
             start="2026-01-03", end="2026-01-05"),
        dict(codes=[], start="2026-01-04", end="2026-01-05"),
        dict(codes=["600519"], start="2026-01-05", end="2026-01-05"),
        dict(codes=["000009"], start="2026-01-01", end="2026-01-05"),
    ]
    options = dict(fields=fields, adjust=adjust, min_bars=min_bars)
    expected = [store.load_panel(**options, **request) for request in requests]
    with panel_read_window(store, start="2026-01-01", end="2026-01-05"):
        for request, result in zip(requests, expected, strict=True):
            _equal(store.load_panel(**options, **request), result)


def test_cache_avoids_repeated_quote_reads_and_output_mutation(store):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-05", adjust="none")
    expected = store.load_panel(**options)
    queries = []
    store.conn.set_trace_callback(queries.append)
    with panel_read_window(store, start=options["start"], end=options["end"]):
        mutated = store.load_panel(**options)["close"]
        mutated.iloc[:, :] = -999
        for _ in range(3):
            _equal(store.load_panel(**options), expected)
        assert not store.conn.in_transaction
    quote_reads = [q for q in queries if "FROM quotes_daily" in q]
    assert len(quote_reads) == 4  # Bounded size guard, two axes, one chunked raw read.
    queries.clear()
    store.load_panel(**options)
    assert len([q for q in queries if "FROM quotes_daily" in q]) == 1


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("table", ["quotes_daily", "adjust_factors"])
def test_same_connection_and_external_commits_invalidate(store, external, table):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-04", adjust="hfq")
    path = store.conn.execute("PRAGMA database_list").fetchone()[2]
    writer = sqlite3.connect(path) if external else store.conn
    with panel_read_window(store, start=options["start"], end=options["end"]):
        before = store.load_panel(**options)
        column = "close" if table == "quotes_daily" else "hfq_factor"
        writer.execute(f"UPDATE {table} SET {column} = {column} + 7")
        writer.commit()
        actual = store.load_panel(**options)
    _equal(actual, store.load_panel(**options))
    assert not before["close"].equals(actual["close"])
    if external:
        writer.close()


def test_uncommitted_update_and_rollback_cannot_poison_cache(store):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-05", adjust="none")
    expected = store.load_panel(**options)
    with panel_read_window(store, start=options["start"], end=options["end"]):
        _equal(store.load_panel(**options), expected)
        store.conn.execute("UPDATE quotes_daily SET close = 999")
        assert store.load_panel(**options)["close"].iloc[0, 0] == 999
        store.conn.rollback()
        _equal(store.load_panel(**options), expected)


@pytest.mark.parametrize("max_cells", [0, 8, 15])
def test_memory_budget_falls_back_without_retaining_panels(store, max_cells):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-05", adjust="none")
    expected = store.load_panel(**options)
    queries = []
    store.conn.set_trace_callback(queries.append)
    with panel_read_window(store, start=options["start"], end=options["end"], max_cells=max_cells):
        _equal(store.load_panel(**options), expected)
        queries.clear()
        _equal(store.load_panel(**options), expected)
        assert len([q for q in queries if "FROM quotes_daily" in q]) == 1


def test_context_is_store_local_nested_and_bounds_are_respected(store):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-05", adjust="none")
    expected = store.load_panel(**options)
    other = _Store(store.conn)
    with panel_read_window(store, start="2026-01-02", end="2026-01-04"):
        _equal(store.load_panel(**options), expected)
        with panel_read_window(other, start=options["start"], end=options["end"]):
            _equal(other.load_panel(**options), expected)
            _equal(store.load_panel(**options), expected)
        _equal(store.load_panel(**options), expected)


@pytest.mark.parametrize("cached", [False, True])
def test_empty_fields_and_empty_database_preserve_contract(store, cached):
    ctx = panel_read_window(store, start="2026-01-01", end="2026-01-09") if cached else nullcontext()
    with ctx:
        assert store.load_panel(fields=[], start="2026-01-01", end="2026-01-05") == {}
        with pytest.raises(StopIteration):
            store.load_panel(fields=[], start="2026-01-01", end="2026-01-05", min_bars=1)
        assert store.load_panel(fields=[], start="2026-01-08", end="2026-01-09", min_bars=1) == {}
        result = store.load_panel(fields=["close"], start="2026-01-08", end="2026-01-09")
        assert_frame_equal(result["close"], pd.DataFrame())


def test_new_fields_fall_back_and_do_not_replace_first_field_cache(store):
    bounds = dict(start="2026-01-01", end="2026-01-05", adjust="none")
    expected = store.load_panel(fields=["open", "volume"], **bounds)
    with panel_read_window(store, start=bounds["start"], end=bounds["end"]):
        store.load_panel(fields=["close"], **bounds)
        _equal(store.load_panel(fields=["open", "volume"], **bounds), expected)
        queries = []
        store.conn.set_trace_callback(queries.append)
        store.load_panel(fields=["close"], **bounds)
        assert not any("FROM quotes_daily" in q for q in queries)


def test_empty_database_cache_and_cross_connection_isolation(store):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-05", adjust="none")
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        store.conn.backup(conn)
        other = _Store(conn)
        conn.execute("DELETE FROM quotes_daily")
        conn.commit()
        with panel_read_window(other, start=options["start"], end=options["end"]):
            assert_frame_equal(other.load_panel(**options)["close"], pd.DataFrame())
            assert not store.load_panel(**options)["close"].empty


def test_chunked_preload_preserves_values_across_chunk_boundaries(store):
    rows = [(f"2026-01-{day:02d}", f"{code:06d}", float(day * code))
            for day in range(1, 8) for code in range(10, 3010)]
    store.conn.executemany("INSERT INTO quotes_daily(trade_date,code,close) VALUES(?,?,?)", rows)
    store.conn.commit()
    options = dict(fields=["close", "volume"], start="2026-01-01", end="2026-01-07", adjust="none")
    expected = store.load_panel(**options)
    with panel_read_window(store, start=options["start"], end=options["end"]):
        _equal(store.load_panel(**options), expected)


def test_external_write_between_guard_and_preload_falls_back(store):
    options = dict(fields=["close"], start="2026-01-01", end="2026-01-05", adjust="none")
    path = store.conn.execute("PRAGMA database_list").fetchone()[2]
    changed = []
    with sqlite3.connect(path) as writer:
        def concurrent_write(sql):
            if not changed and sql.startswith("SELECT trade_date, code, close FROM"):
                changed.append(True)
                writer.execute("INSERT INTO quotes_daily(trade_date,code,close) "
                               "VALUES('2026-01-01','000009',999)")
                writer.commit()

        store.conn.set_trace_callback(concurrent_write)
        with panel_read_window(store, start=options["start"], end=options["end"]):
            actual = store.load_panel(**options)
        store.conn.set_trace_callback(None)
        assert changed
        _equal(actual, store.load_panel(**options))
