"""Real SQLite aggregates above 16 MB and task-local rolling-window fallback."""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.market import MarketStore, panel_read_window
from src.market.infrastructure import store_provenance_query as summary_module
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW


DAYS = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]


@pytest.fixture
def capacity_store(tmp_path):
    codes = [str(600000 + number) for number in range(5002)]
    with MarketStore(tmp_path / "market.db") as store:
        quotes, receipts = [], []
        for code in codes:
            for position, day in enumerate(DAYS):
                receipt = f"{code}-{day}" if position else None
                quotes.append((day, code, 10., 9. if position == 2 else 10.2, 9.8, 10.,
                               None if position == 3 else 1000., None if position == 1 else 10000.,
                               None if position == 3 else .01, 100000., "sina", receipt, day + "T15:30:00"))
                if receipt:
                    receipts.append((receipt, code, "hist_daily", "tdx", "ok", day + "T15:30:00"))
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


def _summary(store, codes, *, start=DAYS[0], end=DAYS[-1]):
    return store.source_evidence(codes=codes, start=start, end=end, summary_only=True)


def _oracle_rows(store, codes, *, start, end):
    rows = []
    for offset in range(0, len(codes), 900):
        where, params = store._quote_where(codes[offset:offset + 900], start=start, end=end, alias="q")
        rows.extend(dict(row) for row in store.conn.execute(store._quote_source_summary_sql(where), params))
    return rows


def _canonical(rows):
    return json.dumps(sorted(rows, key=lambda row: (row["code"], json.dumps(row["source_id"]))),
                      sort_keys=True, separators=(",", ":"))


def _scans(queries):
    return [sql for sql in queries if "GROUP BY q.code, source_id" in sql]


def test_more_than_ten_thousand_groups_fit_and_fixed_origin_remains_incremental(capacity_store):
    store, codes = capacity_store
    expected = [_summary(store, codes, end=end) for end in DAYS[1:]]
    oracle = _oracle_rows(store, codes, start=DAYS[0], end=DAYS[-1])
    assert len(oracle) == 10004
    queries = []
    store.conn.set_trace_callback(queries.append)
    try:
        with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
            actual = [_summary(store, codes, end=end) for end in DAYS[1:]]
            state = _ACTIVE_WINDOW.get()
            assert not state.source_summary_declined
            cache = state.source_summary
            assert cache is not None
            assert 16_000_000 < cache.bytes_used() <= 64_000_000
            assert len(cache.rows) == 10004
            assert _canonical(list(cache.rows.values())) == _canonical(oracle)
    finally:
        store.conn.set_trace_callback(None)
    assert actual == expected
    scans = _scans(queries)
    assert len(scans) == 3
    assert sum("q.trade_date > " in sql for sql in scans) == 2
    assert all("q.trade_date >= " not in sql for sql in scans if "q.trade_date > " in sql)


@pytest.mark.parametrize("first_request", [(DAYS[1], DAYS[1]), (DAYS[0], DAYS[0])])
def test_reverse_window_declines_without_add_and_runs_one_complete_query(
        capacity_store, monkeypatch, first_request):
    store, codes = capacity_store
    requests = [first_request, (DAYS[1], DAYS[3]), (DAYS[0], DAYS[3])]
    expected = [_summary(store, codes, start=start, end=end) for start, end in requests]
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, codes, end=DAYS[2])
        assert _ACTIVE_WINDOW.get().source_summary.bytes_used() > 16_000_000

        def no_add(*args, **kwargs):
            raise AssertionError("An unusable aggregate window must not be rebuilt")

        monkeypatch.setattr(summary_module._SourceSummaryWindow, "add", no_add)
        queries = []
        store.conn.set_trace_callback(queries.append)
        try:
            actual = [_summary(store, codes, start=start, end=end) for start, end in requests]
        finally:
            store.conn.set_trace_callback(None)
        assert actual == expected
        assert _ACTIVE_WINDOW.get().source_summary is None
        assert _ACTIVE_WINDOW.get().source_summary_declined
        scans = _scans(queries)
        assert len(scans) == len(requests)
        assert all("q.trade_date >= " in sql and "q.trade_date > " not in sql for sql in scans)


@pytest.mark.parametrize("external", [False, True])
def test_revision_reenables_cache_after_reverse_decline(capacity_store, external):
    store, codes = capacity_store
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, codes, end=DAYS[1])
        _summary(store, codes, end=DAYS[0])
        state = _ACTIVE_WINDOW.get()
        assert state.source_summary_declined
        writer = sqlite3.connect(store.db_path) if external else store.conn
        try:
            writer.execute("UPDATE quotes_daily SET source='corrected' WHERE code=? AND receipt_id IS NULL",
                           (codes[0],))
            writer.commit()
        finally:
            if external:
                writer.close()
        oracle = _oracle_rows(store, codes, start=DAYS[0], end=DAYS[-1])
        _summary(store, codes)
        assert not state.source_summary_declined
        assert state.source_summary is not None
        assert _canonical(list(state.source_summary.rows.values())) == _canonical(oracle)
        assert "corrected" in {row["source_id"] for row in state.source_summary.rows.values()}


def test_read_transaction_and_rollback_reset_declined_without_caching_the_snapshot(capacity_store):
    store, codes = capacity_store
    expected = _summary(store, codes)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, codes, end=DAYS[1])
        _summary(store, codes, end=DAYS[0])
        state = _ACTIVE_WINDOW.get()
        assert state.source_summary_declined
        store.conn.execute("BEGIN")
        assert _summary(store, codes) == expected
        assert state.source_summary is None
        assert not state.source_summary_declined
        store.conn.rollback()
        assert _summary(store, codes) == expected
        assert state.source_summary is not None
        assert not state.source_summary_declined


def test_small_caller_budget_still_declines_and_falls_back_to_exact_values(capacity_store, monkeypatch):
    store, codes = capacity_store
    expected = _summary(store, codes)
    original_add = summary_module._SourceSummaryWindow.add
    budgets = set()

    def bounded_add(self, row, *, budget):
        budgets.add(budget)
        return original_add(self, row, budget=budget)

    monkeypatch.setattr(summary_module._SourceSummaryWindow, "add", bounded_add)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_evidence_bytes=8_000_000):
        assert _summary(store, codes) == expected
        state = _ACTIVE_WINDOW.get()
        assert state.source_summary is None
        assert state.source_summary_declined
        assert budgets == {8_000_000}
        queries = []
        store.conn.set_trace_callback(queries.append)
        try:
            assert _summary(store, codes) == expected
        finally:
            store.conn.set_trace_callback(None)
        assert len(_scans(queries)) == 1
