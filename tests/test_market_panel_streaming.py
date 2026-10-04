"""The native reader preserves the pivot contract without materializing a long table."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.market import MarketStore, panel_read_window
from src.market.infrastructure import store_panel as panel_module
from src.market.infrastructure.store_codes import MarketError
from src.market.infrastructure.store_schema import PANEL_FIELDS


DAYS = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
CODES = ["000001", "600001", "600002"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCI_MARKET_POLARS", "0")
    monkeypatch.setenv("LOCI_MARKET_DUCKDB", "0")
    with MarketStore(tmp_path / "market.db") as store:
        for row, day in enumerate(DAYS):
            for column, code in enumerate(CODES):
                if code == "600002" and row != 2:
                    continue
                values = (None,) * len(PANEL_FIELDS) if code == "600002" else (
                    10 + row + column, 11 + row + column, 9 + row + column,
                    10.5 + row + column, 100 + row, None, .01 + row / 100, 10000,
                )
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code," + ",".join(PANEL_FIELDS)
                    + ",fetched_at) VALUES(" + ",".join("?" for _ in range(11)) + ")",
                    (day, code, *values, day),
                )
        store.conn.execute(
            "INSERT INTO adjust_factors(code,trade_date,hfq_factor,source,fetched_at) "
            "VALUES(?,?,?,?,?)", ("000001", DAYS[2], 2, "fixture", DAYS[2]),
        )
        store.conn.commit()
        yield store


def pivot_oracle(store, *, fields=("open", "high", "low", "close", "volume", "turnover"),
                 codes=None, start=None, end=None,
                 adjust="none", min_bars=0):
    fields = list(dict.fromkeys(fields))
    if not fields:
        return {}
    params, where = [], "1=1"
    if start:
        where += " AND trade_date >= ?"
        params.append(start)
    if end:
        where += " AND trade_date <= ?"
        params.append(end)
    if codes:
        wanted = [panel_module.normalize_code(code) for code in codes]
        where += " AND code IN (" + ",".join("?" for _ in wanted) + ")"
        params.extend(wanted)
    frame = pd.read_sql_query(
        "SELECT trade_date,code," + ",".join(fields) + " FROM quotes_daily WHERE " + where,
        store.conn, params=params,
    )
    if frame.empty:
        return {field: pd.DataFrame() for field in fields}
    wide = frame.pivot(index="trade_date", columns="code", values=fields)
    panels = {field: wide[field] for field in fields}
    if min_bars > 0:
        reference = panels.get("close", next(iter(panels.values())))
        kept = reference.columns[reference.notna().sum(axis=0) >= min_bars]
        panels = {field: panel[kept] for field, panel in panels.items()}
    if adjust != "none" and any(field in ("open", "high", "low", "close") for field in fields):
        prices = [field for field in fields if field in ("open", "high", "low", "close")]
        ratio = panel_module._consolidate(store._factor_panel(panels[prices[0]], adjust))
        panels.update({field: panels[field] * ratio for field in prices})
    return {field: panel_module._consolidate(panel) for field, panel in panels.items()}


def assert_panels(actual, expected):
    assert list(actual) == list(expected)
    for field in actual:
        pd.testing.assert_frame_equal(actual[field], expected[field], check_exact=True)


@pytest.mark.parametrize("kwargs", [
    dict(start=DAYS[0]),
    dict(end=DAYS[2]),
    dict(codes=["000001", "000001", "999999"]),
    dict(codes=[], start=DAYS[0], end=DAYS[-1]),
    dict(fields=("volume", "close", "volume"), codes=CODES, min_bars=3),
    dict(fields=("volume", "amount"), codes=CODES, min_bars=100),
    dict(fields=("amount",), codes=CODES, min_bars=1),
    dict(codes=["999999"]),
    dict(start="2028-01-01"),
    dict(start=DAYS[-1], end=DAYS[0]),
    dict(start=DAYS[0], fields=("close",), adjust="qfq"),
    dict(start=DAYS[0], fields=("close", "volume"), adjust="hfq"),
])
def test_native_and_cache_fallback_equal_old_pivot_contract(store, kwargs):
    expected = pivot_oracle(store, **kwargs)
    assert_panels(store.load_panel(**kwargs), expected)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_cells=1):
        assert_panels(store.load_panel(**kwargs), expected)


def test_large_read_streams_every_row_and_never_uses_flat_pandas_pipeline(store, monkeypatch):
    last = "2027-01-04"
    count = 16385
    store.conn.executemany(
        "INSERT INTO quotes_daily(trade_date,code,close,fetched_at) VALUES(?,?,?,?)",
        ((last, str(code).zfill(6), float(code), last) for code in range(count)),
    )
    store.conn.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("native reader must not materialize a flat DataFrame or pivot")

    monkeypatch.setattr(pd, "read_sql_query", forbidden)
    monkeypatch.setattr(pd.DataFrame, "pivot", forbidden)
    actual = store.load_panel(fields=("close",), start=last, adjust="none")["close"]
    assert actual.shape == (1, count)
    np.testing.assert_array_equal(actual.to_numpy()[0], np.arange(count, dtype=float))
    assert len(actual._mgr.blocks) == 1


@pytest.mark.parametrize("polars,duckdb,success", [
    (True, True, "polars"), (True, True, "duckdb"), (True, True, None),
    (False, True, "duckdb"), (False, False, None),
])
def test_optional_readers_keep_order_and_native_fallback(store, monkeypatch, polars, duckdb, success):
    calls = []
    flat = pd.read_sql_query(
        "SELECT trade_date,code,close FROM quotes_daily WHERE trade_date=?", store.conn,
        params=[DAYS[0]],
    )
    expected = pivot_oracle(store, fields=("close",), start=DAYS[0], end=DAYS[0])
    monkeypatch.setattr(panel_module, "polars_panel_enabled", lambda: polars)
    monkeypatch.setattr(panel_module, "duckdb_panel_enabled", lambda: duckdb)

    def optional(name):
        def read(*args, **kwargs):
            calls.append(name)
            return flat if name == success else None
        return read

    monkeypatch.setattr(panel_module, "read_quotes_flat_polars", optional("polars"))
    monkeypatch.setattr(panel_module, "read_quotes_flat_duckdb", optional("duckdb"))
    assert_panels(store.load_panel(fields=("close",), start=DAYS[0], end=DAYS[0], adjust="none"), expected)
    assert calls == (["polars"] if success == "polars" else
                     (["polars"] if polars else []) + (["duckdb"] if duckdb else []))


def test_native_read_retries_axis_and_quote_changes_without_mixing_versions(store):
    changed = False

    def committing(query):
        nonlocal changed
        if not changed and query.startswith("SELECT trade_date, code,"):
            changed = True
            with sqlite3.connect(store.db_path) as writer:
                writer.execute(
                    "INSERT INTO quotes_daily(trade_date,code,close,fetched_at) VALUES(?,?,?,?)",
                    ("2026-01-08", "600003", 44, "2026-01-08"),
                )
    store.conn.set_trace_callback(committing)
    actual = store.load_panel(fields=("close",), start=DAYS[0], adjust="none")["close"]
    store.conn.set_trace_callback(None)
    assert changed
    assert actual.loc["2026-01-08", "600003"] == 44
    assert_panels({"close": actual}, pivot_oracle(store, fields=("close",), start=DAYS[0]))


def test_continuous_commits_fail_instead_of_returning_a_mixed_panel(store):
    def committing(query):
        if query.startswith("SELECT trade_date, code,"):
            with sqlite3.connect(store.db_path) as writer:
                writer.execute("UPDATE quotes_daily SET close=close+1 WHERE code='000001'")

    store.conn.set_trace_callback(committing)
    with pytest.raises(MarketError, match="连续发生变化"):
        store.load_panel(fields=("close",), start=DAYS[0], adjust="none")
    store.conn.set_trace_callback(None)


def test_bulk_cursor_does_not_change_connection_row_factory_or_private_cache(store):
    store.load_panel(fields=("close",), start=DAYS[0], adjust="none")
    assert store.conn.row_factory is sqlite3.Row
    assert isinstance(store.conn.execute("SELECT 1").fetchone(), sqlite3.Row)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        first = store.load_panel(fields=("close",), start=DAYS[0], end=DAYS[-1], adjust="none")
        first["close"].iloc[:, :] = -1
        second = store.load_panel(fields=("close",), start=DAYS[0], end=DAYS[-1], adjust="none")
        assert_panels(second, pivot_oracle(store, fields=("close",), start=DAYS[0], end=DAYS[-1]))


def test_validation_and_empty_field_contract_are_preserved(store):
    with pytest.raises(MarketError, match="load_panel"):
        store.load_panel()
    with pytest.raises(MarketError, match="不支持"):
        store.load_panel(fields=("untrusted_sql",), codes=["1"])
    with pytest.raises(MarketError, match="非法证券代码"):
        store.load_panel(codes=["1"])
    assert store.load_panel(fields=(), codes=["000001"]) == {}
    with pytest.raises(StopIteration):
        store.load_panel(fields=(), codes=["000001"], min_bars=1)
    assert store.load_panel(fields=(), codes=["999999"], min_bars=1) == {}


def test_normalize_codes_once_and_cache_version_checks_are_not_duplicated(store, monkeypatch):
    original = panel_module.normalize_code
    calls = []

    def normalized(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(panel_module, "normalize_code", normalized)
    queries = []
    store.conn.set_trace_callback(queries.append)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        store.load_panel(fields=("close",), codes=["000001"], start=DAYS[0], end=DAYS[-1], adjust="none")
    store.conn.set_trace_callback(None)
    assert calls == ["000001"]
    assert sum(query == "PRAGMA data_version" for query in queries) == 3
