"""Range source summaries keep exact daily facts without re-reading old quotes."""
from __future__ import annotations

import sqlite3

import pytest

from src.market import MarketStore, panel_read_window
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW


CODES = ["300001", "301001", "300002"]
DAYS = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]


@pytest.fixture
def summary_store(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        for code in CODES:
            for position, day in enumerate(DAYS):
                receipt_id = f"{code}-{day}" if position else None
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
                    "turnover,outstanding_share,source,receipt_id,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (day, code, 10.0, 9.0 if position == 2 else 10.2, 9.8, 10.0, 1000.0,
                     None if position == 1 else 10000.0, None if position == 3 else 0.01,
                     100000.0, "sina", receipt_id, day + "T15:30:00"),
                )
                if receipt_id and position != 3:
                    store.conn.execute(
                        "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,"
                        "coverage_start,coverage_end,generated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (receipt_id, code, "hist_daily", "tdx" if position == 1 else "tencent",
                         "ok", day, day, day + "T15:30:00"),
                    )
        store.conn.commit()
        store.rebuild_calendar()
        yield store


def _summary(store, codes=CODES, *, start=DAYS[0], end=DAYS[-1]):
    return store.source_evidence(codes=codes, start=start, end=end, summary_only=True)


def _summary_queries(queries):
    return [sql for sql in queries if "GROUP BY q.code, source_id" in sql]


def test_incremental_summaries_match_full_reads_when_codes_leave_and_return(summary_store):
    store = summary_store
    requests = [(CODES[:1], DAYS[0]), (CODES[1:2], DAYS[1]),
                (CODES[:2], DAYS[2]), (CODES, DAYS[3])]
    expected = [_summary(store, codes, end=end) for codes, end in requests]
    queries = []
    store.conn.set_trace_callback(queries.append)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        actual = [_summary(store, codes, end=end) for codes, end in requests]
        cached = _ACTIVE_WINDOW.get().source_summary
        assert cached.codes == set(CODES)
        assert cached.bytes_used() <= _ACTIVE_WINDOW.get().max_evidence_bytes
    store.conn.set_trace_callback(None)
    assert actual == expected
    scans = _summary_queries(queries)
    assert len(scans) == 6  # Three first reads, plus three incremental reads.
    assert sum("q.trade_date > " in sql for sql in scans) == 3
    assert all("q.trade_date >= '2024-01-02'" not in sql
               for sql in scans if "q.trade_date > " in sql)
    assert actual[-1]["rows"] == 12
    assert actual[-1]["missing_receipt_metadata_rows"] == 3
    assert actual[-1]["attempt_observation_status"] == "not_evaluated"


def test_repeated_same_scope_does_no_quote_scan_and_outputs_do_not_mutate_cache(summary_store):
    store = summary_store
    expected = _summary(store)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        result = _summary(store)
        result["sources"][0]["rows"] = -1
        result["field_coverage"]["close"]["rows"] = -1
        queries = []
        store.conn.set_trace_callback(queries.append)
        assert _summary(store) == expected
        store.conn.set_trace_callback(None)
        assert not _summary_queries(queries)


def test_reverse_dates_and_changed_start_reload_exact_scope(summary_store):
    store = summary_store
    scopes = [(DAYS[0], DAYS[3]), (DAYS[0], DAYS[1]), (DAYS[1], DAYS[2])]
    expected = [_summary(store, start=start, end=end) for start, end in scopes]
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        assert [_summary(store, start=start, end=end) for start, end in scopes] == expected


def test_scope_outside_window_and_unscoped_requests_use_normal_reader(summary_store):
    store = summary_store
    expected = _summary(store)
    with panel_read_window(store, start=DAYS[1], end=DAYS[2]):
        assert _summary(store) == expected
        assert _ACTIVE_WINDOW.get().source_summary is None
        assert _summary(store, codes=None)["rows"] == 12
        assert _ACTIVE_WINDOW.get().source_summary is None


@pytest.mark.parametrize("external", [False, True])
def test_committed_quote_and_receipt_changes_invalidate_cached_facts(summary_store, external):
    store = summary_store
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        old = _summary(store)
        writer = sqlite3.connect(store.db_path) if external else store.conn
        try:
            writer.execute("UPDATE source_route_receipts SET selected_source='corrected' "
                           "WHERE code=?", (CODES[0],))
            writer.execute("UPDATE quotes_daily SET volume=NULL WHERE code=? AND trade_date=?",
                           (CODES[1], DAYS[0]))
            writer.commit()
        finally:
            if external:
                writer.close()
        actual = _summary(store)
        assert actual != old
    assert actual == _summary(store)


def test_transaction_and_rollback_never_reuse_transaction_snapshot(summary_store):
    store = summary_store
    expected = _summary(store)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        assert _summary(store) == expected
        store.conn.execute("UPDATE quotes_daily SET close=NULL WHERE code=?", (CODES[0],))
        assert _summary(store) != expected
        assert _ACTIVE_WINDOW.get().source_summary is None
        store.conn.rollback()
        assert _summary(store) == expected


def test_version_change_during_aggregate_read_discards_partial_cache(summary_store, monkeypatch):
    store = summary_store
    original = store._iter_source_summary_rows
    changed = False

    def changing_reader(*args, **kwargs):
        nonlocal changed
        yield from original(*args, **kwargs)
        if not changed:
            changed = True
            with sqlite3.connect(store.db_path) as writer:
                writer.execute("UPDATE quotes_daily SET source='corrected' WHERE receipt_id IS NULL")

    monkeypatch.setattr(store, "_iter_source_summary_rows", changing_reader)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        actual = _summary(store)
        assert changed
        assert _ACTIVE_WINDOW.get().source_summary is None
    assert actual == _summary(store)
    assert "corrected" in {source["source_id"] for source in actual["sources"]}


def test_tiny_budget_declines_and_exiting_scope_clears_all_summary_state(summary_store):
    store = summary_store
    expected = _summary(store)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_evidence_bytes=1):
        state = _ACTIVE_WINDOW.get()
        assert _summary(store) == expected
        assert state.source_summary is None
        assert state.source_summary_declined
    assert _ACTIVE_WINDOW.get() is None
    assert state.source_summary is None
    assert not state.source_summary_declined


def test_source_group_budget_stops_loading_and_falls_back_to_exact_summary(summary_store):
    store = summary_store
    expected = _summary(store)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_evidence_bytes=4000):
        assert _summary(store) == expected
        assert _ACTIVE_WINDOW.get().source_summary is None
        assert _ACTIVE_WINDOW.get().source_summary_declined
