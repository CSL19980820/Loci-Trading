"""Windowed evidence must retain the entire uncached evidence contract."""
from __future__ import annotations

import sqlite3

import pytest

from src.market import MarketStore
from src.market.infrastructure.store_panel_window import panel_read_window, _ACTIVE_WINDOW
from src.market.infrastructure import store_provenance_window as window
from tests.market.test_provenance_single_scan import _seed


@pytest.mark.parametrize("compact", [False, True])
def test_full_evidence_equal_for_overlapping_windows_and_changed_codes(tmp_path, compact):
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        cases = [
            {"codes": None, "start": "2025-01-01", "end": "2025-01-07"},
            {"codes": ["600004", "600000", "missing", "600004"], "start": "2025-01-02", "end": "2025-01-05"},
            {"codes": ["600006"], "start": "2025-01-03", "end": "2025-01-07"},
            {"codes": ["600099"], "start": "2025-01-03", "end": "2025-01-07"},
            {"codes": None, "start": "2025-01-20", "end": "2025-01-21"},
        ]
        expected = [store.source_evidence(**case, include_details=not compact) for case in cases]
        with panel_read_window(store, start="2025-01-01", end="2025-01-31"):
            state = _ACTIVE_WINDOW.get()
            statements = []
            store.conn.set_trace_callback(statements.append)
            for case, original in zip(cases, expected):
                actual = store.source_evidence(**case, include_details=not compact)
                assert actual == original
            store.conn.set_trace_callback(None)
            # One bounded count guard and one quote preload, independent of requests.
            assert sum("FROM quotes_daily" in sql for sql in statements) == 2
            assert state.evidence.rows.nbytes == 49 * 14
            assert state.evidence is not None
        assert state.evidence is None


@pytest.mark.parametrize("budget", [0, 48, 49 * 48 + 100])
def test_budget_declines_once_and_keeps_complete_fallback(tmp_path, budget):
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        kwargs = {"start": "2025-01-01", "end": "2025-01-07", "codes": ["600001"]}
        expected = store.source_evidence(**kwargs)
        with panel_read_window(store, start=kwargs["start"], end=kwargs["end"], max_evidence_bytes=budget):
            assert store.source_evidence(**kwargs) == expected
            assert _ACTIVE_WINDOW.get().evidence is None
            statements = []
            store.conn.set_trace_callback(statements.append)
            assert store.source_evidence(**kwargs) == expected
            store.conn.set_trace_callback(None)
            assert sum("FROM quotes_daily" in sql for sql in statements) == 1


def test_writes_rollback_and_other_store_never_reuse_stale_evidence(tmp_path):
    with MarketStore(tmp_path / "market.db") as store, MarketStore(tmp_path / "other.db") as other_store:
        _seed(store)
        _seed(other_store)
        kwargs = {"start": "2025-01-01", "end": "2025-01-07", "codes": ["600001"]}
        with panel_read_window(store, start=kwargs["start"], end=kwargs["end"]):
            original = store.source_evidence(**kwargs)
            assert window.cached_quote_evidence(other_store, **kwargs) is None
            store.conn.execute("UPDATE quotes_daily SET high=7 WHERE code='600001'")
            assert window.cached_quote_evidence(store, **kwargs) is None
            assert store.source_evidence(**kwargs)["invalid_ohlc_rows"] > original["invalid_ohlc_rows"]
            store.conn.rollback()
            assert store.source_evidence(**kwargs) == original
            with sqlite3.connect(store.db_path) as other:
                other.execute("UPDATE source_route_receipts SET selected_source='revision' WHERE receipt_id='r1'")
            updated = store.source_evidence(**kwargs)
            assert updated != original
            assert "revision" in {item["source_id"] for item in updated["sources"]}
            store.conn.execute("DELETE FROM quotes_daily WHERE code='600001'")
            store.conn.commit()
            assert store.source_evidence(**kwargs)["observed_codes"] == []


def test_commit_during_preload_discards_candidate(tmp_path, monkeypatch):
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        kwargs = {"start": "2025-01-01", "end": "2025-01-07", "codes": ["600001"]}
        original_load = window._load
        def racing_load(state):
            candidate = original_load(state)
            with sqlite3.connect(store.db_path) as other:
                other.execute("DELETE FROM quotes_daily WHERE code='600001'")
            return candidate
        monkeypatch.setattr(window, "_load", racing_load)
        with panel_read_window(store, start=kwargs["start"], end=kwargs["end"]):
            actual = store.source_evidence(**kwargs)
            assert actual["observed_codes"] == []
            assert _ACTIVE_WINDOW.get().evidence is None


def test_missing_dates_and_out_of_scope_use_normal_reader(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        with panel_read_window(store, start="2025-01-03", end="2025-01-05"):
            for start, end in ((None, None), ("2025-01-01", "2025-01-04"), ("2025-01-04", "2025-01-07")):
                assert window.cached_quote_evidence(store, [], start=start, end=end) is None


def test_empty_window_is_cached_and_results_are_independent(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        kwargs = {"start": "2025-01-01", "end": "2025-01-07", "codes": ["600001"]}
        expected = store.source_evidence(**kwargs)
        with panel_read_window(store, start=kwargs["start"], end=kwargs["end"]):
            assert store.source_evidence(**kwargs) == expected
            assert _ACTIVE_WINDOW.get().evidence is not None
            assert len(_ACTIVE_WINDOW.get().evidence.rows) == 0
        _seed(store)
        expected = store.source_evidence(**kwargs)
        with panel_read_window(store, start=kwargs["start"], end=kwargs["end"]):
            first = store.source_evidence(**kwargs)
            first["sources"][0]["rows"] = -1
            first["field_coverage"]["open"]["rows"] = -1
            assert store.source_evidence(**kwargs) == expected


def test_commit_during_aggregation_discards_result(tmp_path, monkeypatch):
    with MarketStore(tmp_path / "market.db") as store:
        _seed(store)
        kwargs = {"start": "2025-01-01", "end": "2025-01-07", "codes": ["600001"]}
        original_aggregate = window._EvidenceWindow.aggregate
        def racing_aggregate(cache, codes, start, end):
            result = original_aggregate(cache, codes, start, end)
            with sqlite3.connect(store.db_path) as other:
                other.execute("DELETE FROM quotes_daily WHERE code='600001'")
            return result
        monkeypatch.setattr(window._EvidenceWindow, "aggregate", racing_aggregate)
        with panel_read_window(store, start=kwargs["start"], end=kwargs["end"]):
            assert store.source_evidence(**kwargs)["observed_codes"] == []
            assert _ACTIVE_WINDOW.get().evidence is None
