"""Large bounded source summaries keep the chunked reader's complete facts."""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.market import MarketStore, panel_read_window
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW


DAYS = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
FIELDS = {"code", "source_id", "first_date", "last_date", "last_fetched_at", "rows",
          "open_rows", "high_rows", "low_rows", "close_rows", "volume_rows", "amount_rows",
          "turnover_rows", "share_rows", "legacy_rows", "missing_receipt_metadata_rows",
          "unresolved_source_rows", "invalid_ohlc"}


@pytest.fixture
def large_summary_store(tmp_path):
    codes = [str(600000 + number) for number in range(1802)]
    with MarketStore(tmp_path / "market.db") as store:
        quotes, receipts = [], []
        for number, code in enumerate(codes):
            for position, day in enumerate(DAYS):
                receipt = f"{code}-{day}" if position else None
                quotes.append((day, code, None if number % 7 == 0 and position == 1 else 10.,
                               9. if position == 2 else 10.2, 9.8,
                               None if number % 11 == 0 and position == 3 else 10.,
                               None if number % 13 == 0 else 1000.,
                               None if position == 1 else 10000.,
                               None if position == 3 else .01, 100000.,
                               "" if number % 3 == 0 else "sina", receipt, day + "T15:30:00"))
                if receipt and position != 2:
                    source = "" if number % 5 == 0 else "tdx"
                    receipts.append((receipt, code, "hist_daily", source, "ok", day + "T15:30:00"))
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,turnover,"
            "outstanding_share,source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", quotes,
        )
        store.conn.executemany(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,generated_at) "
            "VALUES(?,?,?,?,?,?)", receipts,
        )
        store.conn.commit()
        yield store, codes


def _oracle_rows(store, codes, *, start, end, after=None):
    result = []
    for offset in range(0, max(1, len(codes)), 900):
        chunk = codes[offset:offset + 900]
        where, params = store._quote_where(chunk, start=start, end=end, alias="q")
        if after is not None:
            where += " AND q.trade_date > ?" if where else " WHERE q.trade_date > ?"
            params.append(after)
        result.extend(dict(row) for row in store.conn.execute(store._quote_source_summary_sql(where), params))
    return result


def _canonical(rows):
    return json.dumps(sorted((dict(row) for row in rows),
                            key=lambda row: (row["code"], json.dumps(row["source_id"]))),
                      sort_keys=True, separators=(",", ":"))


def _queries(store, request):
    queries = []
    store.conn.set_trace_callback(queries.append)
    try:
        rows = list(store._iter_source_summary_rows(**request))
    finally:
        store.conn.set_trace_callback(None)
    return rows, queries


def _scans(queries):
    return [sql for sql in queries if "GROUP BY q.code, source_id" in sql]


@pytest.mark.parametrize("start,after", [(DAYS[0], None), (None, DAYS[1]), (DAYS[0], DAYS[1])])
def test_one_parameterized_date_scan_matches_every_chunked_field(large_summary_store, start, after):
    store, codes = large_summary_store
    request = {"codes": list(reversed(codes)), "start": start, "end": DAYS[-1], "after": after}
    expected = _oracle_rows(store, **request)
    actual, queries = _queries(store, request)
    scans = _scans(queries)
    assert len(scans) == 1
    assert "INDEXED BY sqlite_autoindex_quotes_daily_1" in scans[0]
    assert "q.code IN (SELECT value FROM json_each(" in scans[0]
    assert _canonical(actual) == _canonical(expected)
    assert all(set(row.keys()) == FIELDS for row in actual)
    assert store._aggregate_quote_rows(actual) == store._aggregate_quote_rows(expected)
    assert store._source_summaries(actual) == store._source_summaries(expected)
    assert any(row["source_id"] is None for row in actual)
    assert sum(row["missing_receipt_metadata_rows"] for row in actual) == len(codes)
    assert sum(row["unresolved_source_rows"] for row in actual) > len(codes)
    assert not any(sql.lstrip().upper().startswith(("CREATE", "INSERT", "UPDATE", "DELETE", "DROP"))
                   for sql in queries)


@pytest.mark.parametrize("count,start,end,after", [
    (900, DAYS[0], DAYS[-1], None),
    (901, None, DAYS[-1], None),
    (901, DAYS[0], None, None),
    (901, None, None, DAYS[1]),
    (0, DAYS[0], DAYS[-1], None),
])
def test_small_or_unbounded_scopes_do_not_probe_or_force_date_scans(
        large_summary_store, monkeypatch, count, start, end, after):
    store, codes = large_summary_store
    request = {"codes": codes[:count], "start": start, "end": end, "after": after}
    expected = _oracle_rows(store, **request)

    def unexpected():
        raise AssertionError("Ineligible scope must keep the original query")

    monkeypatch.setattr(store, "_date_source_summary_available", unexpected)
    actual, queries = _queries(store, request)
    scans = _scans(queries)
    assert len(scans) == max(1, (count + 899) // 900)
    assert all("json_each" not in sql and "INDEXED BY" not in sql for sql in scans)
    assert _canonical(actual) == _canonical(expected)


class CapabilityConnection:
    def __init__(self, conn, missing):
        self.conn, self.missing = conn, missing

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, sql, parameters=()):
        if self.missing == "json" and sql.startswith("SELECT value FROM json_each"):
            raise sqlite3.OperationalError("no such table: json_each")
        if self.missing == "index" and sql.startswith("SELECT 1 FROM quotes_daily INDEXED BY"):
            raise sqlite3.OperationalError("no such index: sqlite_autoindex_quotes_daily_1")
        return self.conn.execute(sql, parameters)


@pytest.mark.parametrize("missing", ["json", "index"])
def test_unavailable_capability_preserves_all_original_chunks(large_summary_store, missing):
    store, codes = large_summary_store
    request = {"codes": codes, "start": DAYS[0], "end": DAYS[-1], "after": None}
    expected = _oracle_rows(store, **request)
    conn = store.conn
    store.conn = CapabilityConnection(conn, missing)
    try:
        actual, queries = _queries(store, request)
    finally:
        store.conn = conn
    assert _canonical(actual) == _canonical(expected)
    scans = _scans(queries)
    assert len(scans) == 3
    assert all("json_each" not in sql and "INDEXED BY" not in sql for sql in scans)


@pytest.mark.parametrize("limit,after", [(3, None), (4, DAYS[1])])
def test_large_scope_fits_a_small_sqlite_variable_limit(large_summary_store, limit, after):
    store, codes = large_summary_store
    request = {"codes": codes, "start": DAYS[0], "end": DAYS[-1], "after": after}
    expected = _oracle_rows(store, **request)
    before = store.conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, limit)
    try:
        actual, queries = _queries(store, request)
    finally:
        store.conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, before)
    assert len(_scans(queries)) == 1
    assert _canonical(actual) == _canonical(expected)


def test_incremental_cache_refreshes_known_and_new_codes_without_repeating_history(
        large_summary_store, monkeypatch):
    store, codes = large_summary_store
    requests = [(codes[:901], DAYS[0]), (codes, DAYS[1]), (codes[901:], DAYS[2]), (codes, DAYS[3])]
    with monkeypatch.context() as legacy:
        legacy.setattr(store, "_date_source_summary_available", lambda: False)
        expected = [store.source_evidence(codes=scope, start=DAYS[0], end=end, summary_only=True)
                    for scope, end in requests]
    queries = []
    store.conn.set_trace_callback(queries.append)
    try:
        with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
            actual = [store.source_evidence(codes=scope, start=DAYS[0], end=end, summary_only=True)
                      for scope, end in requests]
            cache = _ACTIVE_WINDOW.get().source_summary
            assert cache is not None and cache.codes == set(codes)
            assert cache.bytes_used() <= 16_000_000
    finally:
        store.conn.set_trace_callback(None)
    assert actual == expected
    scans = _scans(queries)
    assert len(scans) == 5
    assert all("INDEXED BY sqlite_autoindex_quotes_daily_1" in sql for sql in scans)
    assert sum("q.trade_date > " in sql for sql in scans) == 3
    assert all("q.trade_date >= " not in sql for sql in scans if "q.trade_date > " in sql)


def test_large_public_summary_preserves_legacy_missing_and_coverage_counts(large_summary_store, monkeypatch):
    store, codes = large_summary_store
    with monkeypatch.context() as legacy:
        legacy.setattr(store, "_date_source_summary_available", lambda: False)
        expected = store.source_evidence(codes=codes, start=DAYS[0], end=DAYS[-1], summary_only=True)
    actual = store.source_evidence(codes=codes, start=DAYS[0], end=DAYS[-1], summary_only=True)
    assert actual == expected
    assert actual["rows"] == len(codes) * 4
    assert actual["legacy_quote_rows"] == len(codes)
    assert actual["missing_receipt_metadata_rows"] == len(codes)
    assert actual["source_summary_incomplete"]
    assert actual["invalid_ohlc_rows"] == len(codes)
