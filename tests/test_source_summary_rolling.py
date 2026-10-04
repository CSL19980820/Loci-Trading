"""Rolling summaries reuse interior months without subtracting extrema."""
from __future__ import annotations

import sqlite3

import pytest

from src.market import MarketStore, panel_read_window
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW
from src.market.infrastructure.store_provenance_query import _SourceSummaryMonth, _SourceSummaryMonths


CODES = ["600001", "600002", "300001"]
DAYS = ["2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02",
        "2024-02-28", "2024-02-29", "2024-03-01", "2024-03-04", "2024-03-29",
        "2024-03-31", "2024-04-01", "2024-04-03", "2024-04-30", "2024-06-03"]


@pytest.fixture
def rolling_store(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        for number, code in enumerate(CODES):
            for position, day in enumerate(DAYS):
                receipt = f"{code}-{day}" if position % 4 else None
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
                    "turnover,outstanding_share,source,receipt_id,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (day, code, None if position % 5 == 1 else 10.,
                     9. if position % 5 == 2 else 10.2, 9.8, 10.,
                     None if position % 5 == 3 else 1000.,
                     None if position % 5 == 4 else 10000., .01, 100000.,
                     "" if position % 3 else "sina", receipt,
                     "2025-01-01" if position == number else day + "T15:30:00"),
                )
                if receipt and position % 4 != 3:
                    store.conn.execute(
                        "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,"
                        "generated_at) VALUES(?,?,?,?,?,?)",
                        (receipt, code, "hist_daily", "" if position % 3 else "tdx", "ok", day),
                    )
        store.conn.commit()
        yield store


def _summary(store, codes, start, end):
    return store.source_evidence(codes=codes, start=start, end=end, summary_only=True)


def _canonical(rows):
    return sorted((dict(row) for row in rows), key=lambda row: (row["code"], str(row["source_id"])))


def _scans(queries):
    return [query for query in queries if "GROUP BY q.code, source_id" in query]


def test_rolling_months_preserve_every_field_and_only_read_changed_edges(rolling_store):
    store = rolling_store
    requests = [(CODES[:2], DAYS[0], "2024-03-29"),
                (CODES[:2], DAYS[1], "2024-03-31"),
                (CODES, DAYS[2], "2024-04-01"),
                (CODES[1:], "2024-02-01", "2024-04-03"),
                (CODES, "2024-02-02", "2024-04-30"),
                (CODES, "2024-03-01", "2024-06-03")]
    expected = [_summary(store, *request) for request in requests]
    oracle = [_canonical(store._iter_source_summary_rows(codes, start=start, end=end))
              for codes, start, end in requests]
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        for index, (codes, start, end) in enumerate(requests):
            queries = []
            store.conn.set_trace_callback(queries.append)
            actual = _summary(store, codes, start, end)
            store.conn.set_trace_callback(None)
            assert actual == expected[index]
            assert _canonical(store._cached_source_summary_rows(codes, start=start, end=end)) == oracle[index]
            cache = _ACTIVE_WINDOW.get().source_summary
            assert not _ACTIVE_WINDOW.get().source_summary_declined
            assert cache.bytes_used() <= 64_000_000
            if index >= 1:
                assert isinstance(cache, _SourceSummaryMonths)
            if index == 2:
                # Existing stocks never rescan February/March. New stocks load
                # those months once; January is the moving left edge.
                interior = [query for query in _scans(queries)
                            if "q.trade_date >= '2024-02" in query
                            or "q.trade_date >= '2024-03" in query]
                assert len(interior) == 2
                assert all("'600001'" not in query and "'600002'" not in query for query in interior)
            if index == 3:
                assert len(_scans(queries)) == 1
                assert "q.trade_date > '2024-04-01'" in _scans(queries)[0]
            if index == 5:
                assert "2024-01" not in cache.months and "2024-02" not in cache.months
                assert cache.months["2024-05"].rows == {}
                assert cache.months["2024-05"].codes == set(CODES)


def test_rolling_outputs_are_private_and_same_scope_does_not_scan(rolling_store):
    store = rolling_store
    scope = (CODES, DAYS[1], "2024-03-31")
    expected = _summary(store, *scope)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, CODES, DAYS[0], "2024-03-29")
        _summary(store, *scope)
        rows = store._cached_source_summary_rows(CODES, start=scope[1], end=scope[2])
        rows[0]["rows"] = -1
        queries = []
        store.conn.set_trace_callback(queries.append)
        assert _summary(store, *scope) == expected
        store.conn.set_trace_callback(None)
        assert not _scans(queries)


@pytest.mark.parametrize("external", [False, True])
def test_rolling_cache_invalidates_quote_and_receipt_corrections(rolling_store, external):
    store = rolling_store
    scope = (CODES, DAYS[1], "2024-03-31")
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, CODES, DAYS[0], "2024-03-29")
        old = _summary(store, *scope)
        writer = sqlite3.connect(store.db_path) if external else store.conn
        try:
            writer.execute("UPDATE quotes_daily SET close=NULL WHERE trade_date='2024-02-28'")
            writer.execute("UPDATE source_route_receipts SET selected_source='corrected' WHERE code=?", (CODES[0],))
            writer.commit()
        finally:
            if external:
                writer.close()
        actual = _summary(store, *scope)
        assert actual != old
    assert actual == _summary(store, *scope)


def test_rolling_cache_transaction_and_rollback_do_not_reuse_snapshot(rolling_store):
    store = rolling_store
    scope = (CODES, DAYS[1], "2024-03-31")
    expected = _summary(store, *scope)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, CODES, DAYS[0], "2024-03-29")
        assert _summary(store, *scope) == expected
        store.conn.execute("UPDATE quotes_daily SET close=NULL")
        assert _summary(store, *scope) != expected
        assert _ACTIVE_WINDOW.get().source_summary is None
        store.conn.rollback()
        assert _summary(store, *scope) == expected


def test_version_change_while_loading_months_discards_all_segments(rolling_store, monkeypatch):
    store = rolling_store
    scope = (CODES, DAYS[1], "2024-03-31")
    original = store._iter_source_summary_rows
    changed = False

    def changing_reader(*args, **kwargs):
        nonlocal changed
        yield from original(*args, **kwargs)
        if not changed:
            changed = True
            with sqlite3.connect(store.db_path) as writer:
                writer.execute("UPDATE quotes_daily SET source='corrected' WHERE receipt_id IS NULL")

    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, CODES, DAYS[0], "2024-03-29")
        monkeypatch.setattr(store, "_iter_source_summary_rows", changing_reader)
        actual = _summary(store, *scope)
        assert _ACTIVE_WINDOW.get().source_summary is None
    assert actual == _summary(store, *scope)


@pytest.mark.parametrize("reverse", [(DAYS[0], "2024-04-03"), (DAYS[2], "2024-03-29")])
def test_reverse_window_after_month_cache_falls_back(rolling_store, reverse):
    store = rolling_store
    expected = _summary(store, CODES, *reverse)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, CODES, DAYS[0], "2024-03-29")
        _summary(store, CODES, DAYS[1], "2024-03-31")
        assert _summary(store, CODES, *reverse) == expected
        assert _ACTIVE_WINDOW.get().source_summary_declined
        assert _ACTIVE_WINDOW.get().source_summary is None


def test_month_cache_budget_overflow_falls_back_without_partial_results(rolling_store, monkeypatch):
    store = rolling_store
    scope = (CODES, DAYS[1], "2024-03-31")
    expected = _summary(store, *scope)
    original = _SourceSummaryMonth.add
    loaded_rows = 0

    def counted_add(self, row):
        nonlocal loaded_rows
        loaded_rows += 1
        original(self, row)

    monkeypatch.setattr(_SourceSummaryMonth, "add", counted_add)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _summary(store, CODES, DAYS[0], "2024-03-29")
        state = _ACTIVE_WINDOW.get()
        state.max_evidence_bytes = 4000
        assert _summary(store, *scope) == expected
        assert loaded_rows > 0
        assert state.source_summary_declined and state.source_summary is None


def test_whole_market_nine_months_fit_budget_and_keep_interior_months(tmp_path):
    codes = [str(600000 + number) for number in range(4401)]
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ((f"2024-{month:02}-15", code, 10., 11., 9., 10., 1000., "tdx", "2024-10-01")
             for month in range(1, 10) for code in codes),
        )
        store.conn.commit()
        expected = _summary(store, codes, "2024-01-03", "2024-09-17")
        with panel_read_window(store, start="2024-01-01", end="2024-09-30"):
            _summary(store, codes, "2024-01-01", "2024-09-15")
            _summary(store, codes, "2024-01-02", "2024-09-16")
            state = _ACTIVE_WINDOW.get()
            assert isinstance(state.source_summary, _SourceSummaryMonths)
            assert 16_000_000 < state.source_summary.bytes_used() <= 64_000_000
            queries = []
            store.conn.set_trace_callback(queries.append)
            assert _summary(store, codes, "2024-01-03", "2024-09-17") == expected
            store.conn.set_trace_callback(None)
            assert len(_scans(queries)) == 2
            assert any("q.trade_date > '2024-09-16'" in query for query in _scans(queries))
            assert not state.source_summary_declined
