"""Task-local panel/provenance reads use exact codes and preserve point-in-time factors."""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from src.market import MarketStore, panel_read_window
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW


CODES = ["300001", "300002", "600001", "600002"]
DAYS = pd.bdate_range("2024-01-02", periods=12).strftime("%Y-%m-%d").tolist()


@pytest.fixture
def window_store(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        for code in CODES:
            for position, day in enumerate(DAYS):
                null = code == CODES[0] and position == 3
                missing = code == CODES[1] and position < 2
                if missing:
                    continue
                receipt_id = f"receipt-{code}"
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,source,"
                    "receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (day, code, None if null else 10 + position, None if null else 10.5 + position,
                     None if null else 9.5 + position, None if null else 10.1 + position,
                     None if null else 100 + position, "legacy", receipt_id, day + "T15:30:00"),
                )
            store.conn.execute(
                "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,"
                "coverage_start,coverage_end,generated_at) VALUES(?,?,?,?,?,?,?,?)",
                (receipt_id, code, "hist_daily", "tdx", "ok", DAYS[0], DAYS[-1], DAYS[-1]),
            )
            store.conn.execute(
                "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,checked_at,rows) "
                "VALUES(?,?,?,?,?,?)", (receipt_id, 1, "tdx", "ok", DAYS[-1], 12),
            )
        for code, day, factor in [(CODES[0], "2023-12-28", 1.0),
                                  (CODES[0], DAYS[5], 2.0), (CODES[0], "2024-02-01", 4.0),
                                  (CODES[1], DAYS[8], 3.0), (CODES[1], "2024-02-01", 5.0)]:
            store.conn.execute(
                "INSERT INTO adjust_factors(code,trade_date,hfq_factor,source,fetched_at) "
                "VALUES(?,?,?,?,?)", (code, day, factor, "fixture", day),
            )
        store.conn.commit()
        store.rebuild_calendar()
        yield store


def _panel(store, codes=CODES[:1], fields=("open", "close"), *, start=None, end=None,
           adjust="none", min_bars=0):
    return store.load_panel(codes=codes, fields=fields, start=start or DAYS[0],
                            end=end or DAYS[-1], adjust=adjust, min_bars=min_bars)


def _assert_panels(actual, expected):
    assert list(actual) == list(expected)
    for field in actual:
        pd.testing.assert_frame_equal(actual[field], expected[field], check_exact=True)


def _quote_queries(queries):
    return [query for query in queries if "FROM quotes_daily" in query
            and query.lstrip().upper().startswith("SELECT")]


def test_first_read_is_code_scoped_without_market_count_or_code_axis_scan(window_store):
    store = window_store
    expected = _panel(store)
    queries = []
    store.conn.set_trace_callback(queries.append)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_cells=36):
        _assert_panels(_panel(store), expected)
        assert _ACTIVE_WINDOW.get().loaded_codes == frozenset(CODES[:1])
    store.conn.set_trace_callback(None)
    scans = _quote_queries(queries)
    assert len(scans) == 2
    assert all("code IN ('300001')" in query for query in scans)
    assert not any("COUNT(" in query or "DISTINCT code" in query for query in scans)
    assert expected["close"].loc[DAYS[3]].isna().all()  # An all-NULL row still creates axes.


def test_new_codes_and_fields_extend_without_losing_axes_or_existing_values(window_store):
    store = window_store
    requests = [dict(codes=CODES[:1], fields=("close",), end=DAYS[5]),
                dict(codes=CODES[:2], fields=("close",), start=DAYS[1]),
                dict(codes=CODES[:2], fields=("open", "close", "volume")),
                dict(codes=CODES[1:2], fields=("volume", "close"), min_bars=9)]
    expected = [_panel(store, **request) for request in requests]
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        for request, reference in zip(requests, expected, strict=True):
            _assert_panels(_panel(store, **request), reference)
        assert set(_ACTIVE_WINDOW.get().panels) == {"close", "open", "volume"}
        assert _ACTIVE_WINDOW.get().loaded_codes == frozenset(CODES[:2])


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
def test_new_code_reads_only_missing_quotes_and_merges_null_date_axis(window_store, adjust):
    store = window_store
    extra_day = "2024-01-18"
    # Quote existence must extend the axis even when every requested value is NULL.
    store.conn.execute(
        "INSERT INTO quotes_daily(trade_date,code,fetched_at) VALUES(?,?,?)",
        (extra_day, CODES[1], extra_day),
    )
    store.conn.commit()
    expected = _panel(store, codes=CODES[:2], end=extra_day, adjust=adjust)
    filtered = _panel(store, codes=CODES[:2], end=extra_day, adjust=adjust, min_bars=10)
    with panel_read_window(store, start=DAYS[0], end=extra_day):
        first = _panel(store, end=extra_day, adjust=adjust)
        first["close"].iloc[:, :] = -1
        queries = []
        store.conn.set_trace_callback(queries.append)
        actual = _panel(store, codes=CODES[:2], end=extra_day, adjust=adjust)
        store.conn.set_trace_callback(None)
        _assert_panels(actual, expected)
        scans = _quote_queries(queries)
        assert len(scans) == 2
        assert all("code IN ('300002')" in query for query in scans)
        assert extra_day in actual["close"].index
        assert actual["close"].loc[extra_day].isna().all()
        assert _ACTIVE_WINDOW.get().loaded_codes == frozenset(CODES[:2])
        _assert_panels(_panel(store, codes=CODES[:2], end=extra_day, adjust=adjust, min_bars=10), filtered)


def test_incremental_extension_over_merged_axis_budget_keeps_narrow_cache(window_store):
    store = window_store
    extra_day = "2024-01-18"
    store.conn.execute(
        "INSERT INTO quotes_daily(trade_date,code,close,fetched_at) VALUES(?,?,?,?)",
        (extra_day, CODES[1], 77, extra_day),
    )
    store.conn.commit()
    expected = _panel(store, codes=CODES[:2], end=extra_day)
    # The original axis would fit two stocks, but the newly introduced date does not.
    with panel_read_window(store, start=DAYS[0], end=extra_day, max_cells=72):
        narrow = _panel(store, end=extra_day)
        state = _ACTIVE_WINDOW.get()
        original = state.present
        _assert_panels(_panel(store, codes=CODES[:2], end=extra_day), expected)
        assert state.present is original
        assert state.loaded_codes == frozenset(CODES[:1])
        assert state.declined
        queries = []
        store.conn.set_trace_callback(queries.append)
        _assert_panels(_panel(store, end=extra_day), narrow)
        store.conn.set_trace_callback(None)
        assert not _quote_queries(queries)


def test_external_commit_during_incremental_read_discards_both_cached_parts(window_store):
    store = window_store
    changed = False

    def changing(query):
        nonlocal changed
        if (not changed and query.startswith("SELECT trade_date, code,")
                and "code IN ('300002')" in query):
            changed = True
            with sqlite3.connect(store.db_path) as writer:
                writer.execute("UPDATE quotes_daily SET close=44 WHERE code=? AND trade_date=?",
                               (CODES[0], DAYS[-1]))

    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _panel(store)
        store.conn.set_trace_callback(changing)
        actual = _panel(store, codes=CODES[:2])
        store.conn.set_trace_callback(None)
        assert changed
        assert actual["close"].loc[DAYS[-1], CODES[0]] == 44
        assert _ACTIVE_WINDOW.get().present is None
    _assert_panels(actual, _panel(store, codes=CODES[:2]))


def test_failed_expansion_retains_bounded_narrow_cache_and_falls_back_exactly(window_store):
    store = window_store
    expected = _panel(store, codes=CODES)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_cells=36):
        _panel(store)
        _assert_panels(_panel(store, codes=CODES), expected)
        queries = []
        store.conn.set_trace_callback(queries.append)
        _panel(store)
        store.conn.set_trace_callback(None)
        assert not _quote_queries(queries)
        assert _ACTIVE_WINDOW.get().loaded_codes == frozenset(CODES[:1])


def test_requesting_all_codes_after_narrow_cache_and_mutating_outputs_is_safe(window_store):
    store = window_store
    expected = _panel(store, codes=None)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        first = _panel(store)
        first["close"].iloc[:, :] = -1
        _assert_panels(_panel(store, codes=None), expected)
        assert _ACTIVE_WINDOW.get().loaded_codes is None


@pytest.mark.parametrize("external", [False, True])
def test_quote_changes_and_transactions_invalidate_cached_panels(window_store, external):
    store = window_store
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _panel(store)
        writer = sqlite3.connect(store.db_path) if external else store.conn
        try:
            writer.execute("UPDATE quotes_daily SET close=22 WHERE code=? AND trade_date=?",
                           (CODES[0], DAYS[-1]))
            writer.commit()
        finally:
            if external:
                writer.close()
        assert _panel(store)["close"].iloc[-1, 0] == 22
        store.conn.execute("UPDATE quotes_daily SET close=33 WHERE code=? AND trade_date=?",
                           (CODES[0], DAYS[-1]))
        assert _panel(store)["close"].iloc[-1, 0] == 33
        assert _ACTIVE_WINDOW.get().present is None
        store.conn.rollback()
        assert _panel(store)["close"].iloc[-1, 0] == 22


def test_read_during_external_commit_discards_private_partial_arrays(window_store):
    store = window_store
    changed = False

    def changing(query):
        nonlocal changed
        if not changed and query.startswith("SELECT trade_date, code,"):
            changed = True
            with sqlite3.connect(store.db_path) as writer:
                writer.execute("UPDATE quotes_daily SET close=44 WHERE code=? AND trade_date=?",
                               (CODES[0], DAYS[-1]))

    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        store.conn.set_trace_callback(changing)
        actual = _panel(store)
        store.conn.set_trace_callback(None)
        assert changed
        assert actual["close"].iloc[-1, 0] == 44
        assert _ACTIVE_WINDOW.get().present is None


@pytest.mark.parametrize("adjust", ["qfq", "hfq"])
def test_sparse_factors_are_reused_but_request_adjustment_anchors_stay_exact(window_store, adjust):
    store = window_store
    scopes = [(DAYS[1], DAYS[4]), (DAYS[1], DAYS[7]), (DAYS[6], DAYS[10])]
    expected = [_panel(store, codes=CODES[:2], start=start, end=end, adjust=adjust)
                for start, end in scopes]
    queries = []
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        store.conn.set_trace_callback(queries.append)
        for (start, end), reference in zip(scopes, expected, strict=True):
            _assert_panels(_panel(store, codes=CODES[:2], start=start, end=end, adjust=adjust), reference)
        store.conn.set_trace_callback(None)
        assert len([query for query in queries if "FROM adjust_factors" in query]) == 1


def test_factor_revision_change_and_budget_preserve_fallback_values(window_store):
    store = window_store
    expected = _panel(store, codes=CODES[:2], adjust="qfq")
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_factor_bytes=1):
        _assert_panels(_panel(store, codes=CODES[:2], adjust="qfq"), expected)
        assert _ACTIVE_WINDOW.get().factor_declined
        assert not _ACTIVE_WINDOW.get().factor_rows
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _panel(store, adjust="qfq")
        with sqlite3.connect(store.db_path) as writer:
            writer.execute("UPDATE adjust_factors SET hfq_factor=4 WHERE code=? AND trade_date=?",
                           (CODES[0], DAYS[5]))
        actual = _panel(store, adjust="qfq")
    _assert_panels(actual, _panel(store, adjust="qfq"))


def test_full_source_receipts_and_attempts_remain_exact_and_preloads_are_code_scoped(window_store):
    store = window_store
    scopes = [(CODES[:1], DAYS[5]), (CODES[:2], DAYS[8]), (CODES[1:2], DAYS[-1])]
    expected = [store.source_evidence(codes=codes, start=DAYS[0], end=end) for codes, end in scopes]
    queries = []
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        store.conn.set_trace_callback(queries.append)
        actual = [store.source_evidence(codes=codes, start=DAYS[0], end=end) for codes, end in scopes]
        store.conn.set_trace_callback(None)
        assert _ACTIVE_WINDOW.get().evidence.scope_codes == frozenset(CODES[:2])
    assert actual == expected
    assert actual[-1]["receipts"] and actual[-1]["attempts"]
    assert all("code IN (" in query for query in _quote_queries(queries))
    assert not any("600001" in query or "600002" in query for query in _quote_queries(queries))


def test_all_empty_and_nonexistent_codes_return_same_axes_as_uncached_reader(window_store):
    store = window_store
    expected = _panel(store, codes=["999999"])
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        _assert_panels(_panel(store, codes=["999999"]), expected)
        _assert_panels(_panel(store), _panel(store))
        state = _ACTIVE_WINDOW.get()
    assert state.present is None
    assert not state.factor_rows
    assert state.evidence is None
