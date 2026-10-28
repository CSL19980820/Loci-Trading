"""Exact task-local receipt/attempt reuse, including cold archive changes."""
from __future__ import annotations

from datetime import date, timedelta
import os
import shutil

import pytest

from src.market import MarketStore, panel_read_window
from src.market.application import provenance_archive as archive
from src.market.infrastructure.store_panel_window import _ACTIVE_WINDOW, _PanelWindow
from src.shared.evidence_compact import compact_source_evidence


DAYS = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(20)]
CODES = [str(600001 + i) for i in range(5)]


@pytest.fixture
def archive_store(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        for c, code in enumerate(CODES):
            for group in range(5):
                receipt = f"receipt-{c}-{group}"
                stamp = f"2024-01-{group + 1:02}T15:00:{c:02}"
                store.conn.execute(
                    "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,"
                    "unresolved,coverage_start,coverage_end,generated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (receipt, code, "hist_daily", "tdx", "failed" if c == 4 else "selected",
                     int(c == 4), DAYS[0], DAYS[-1], stamp),
                )
                if not (c == 1 and group == 0):
                    for number in range(2):
                        store.conn.execute(
                            "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,"
                            "checked_at,rows,fields_json,payload_sha256) VALUES(?,?,?,?,?,?,?,?)",
                            (receipt, number, "tdx", "selected", stamp, 4, '["close"]',
                             f"{receipt}-{number}"),
                        )
                for day in DAYS[group * 4:group * 4 + 4]:
                    store.conn.execute(
                        "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,"
                        "amount,source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (day, code, 10, 11, 9, 10, 100, 1000, "tdx", receipt, stamp),
                    )
        # One linked receipt intentionally has no metadata.
        store.conn.execute("UPDATE quotes_daily SET receipt_id='orphan' WHERE code=? AND trade_date=?",
                           (CODES[0], DAYS[1]))
        store.conn.commit()
        archive.archive_selected_batch(store.conn, archive.default_archive_root(store.db_path),
                                       cutoff="2025-01-01")
        yield store


def _scope(end, *, include_details=False):
    return dict(codes=CODES, start=DAYS[0], end=end, include_details=include_details)


@pytest.mark.parametrize("include_details", [False, True])
def test_daily_results_equal_uncached_full_and_compact_and_reuse_cold_queries(
        archive_store, monkeypatch, include_details):
    store = archive_store
    scopes = [_scope(day, include_details=include_details) for day in DAYS[:17]]
    expected = [store.source_evidence(**scope) for scope in scopes]
    for result in expected:
        compact_source_evidence(result)
    uncached_compact = [store.source_evidence(**scope, mode="compact") for scope in scopes]
    assert uncached_compact == expected
    calls = {name: 0 for name in ("query_archived_receipt_metadata", "query_archived_attempt_counts",
                                   "query_archived_attempts", "query_archived_attempt_sample")}
    for name in calls:
        original = getattr(archive, name)

        def tracked(*args, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(archive, name, tracked)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        actual = [store.source_evidence(**scope, mode="compact") for scope in scopes]
        state = _ACTIVE_WINDOW.get()
        assert 0 < state.provenance_bytes <= state.max_provenance_bytes
    assert actual == expected
    assert calls["query_archived_receipt_metadata"] <= 6
    assert calls["query_archived_attempt_counts"] <= 5
    assert calls["query_archived_attempts"] <= 5
    assert calls["query_archived_attempt_sample"] == 0


@pytest.mark.parametrize("budget", [0, 1, 4000])
def test_small_cache_budget_falls_back_without_losing_evidence(archive_store, budget):
    store = archive_store
    scope = _scope(DAYS[8], include_details=True)
    expected = store.source_evidence(**scope, mode="compact")
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_provenance_bytes=budget):
        state = _ACTIVE_WINDOW.get()
        assert store.source_evidence(**scope, mode="compact") == expected
        assert store.source_evidence(**scope, mode="compact") == expected
        assert state.provenance_bytes <= budget
        if budget < 100:
            assert not state.provenance_cache
    assert not state.provenance_cache


@pytest.mark.parametrize("external_writer", [False, True])
def test_database_receipt_and_attempt_writes_invalidate_cache(archive_store, external_writer):
    store = archive_store
    scope = _scope(DAYS[0])
    with MarketStore(store.db_path) as other:
        with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
            before = store.source_evidence(**scope, mode="compact")
            writer = other if external_writer else store
            writer.persist_source_receipt({
                "receipt_id": "orphan", "code": CODES[0], "lane": "hist_daily",
                "selected_source": "new", "state": "selected", "generated_at": DAYS[0],
                "attempts": [{"source_id": "new", "state": "selected"}],
            })
            writer.conn.execute("UPDATE quotes_daily SET receipt_id='orphan' WHERE code=? AND trade_date=?",
                                (CODES[0], DAYS[0]))
            writer.conn.commit()
            expected = other.source_evidence(**scope, mode="compact")
            actual = store.source_evidence(**scope, mode="compact")
            assert actual == expected
            assert actual != before


def test_archive_replacement_addition_and_removal_invalidate_cached_results(archive_store):
    store = archive_store
    root = archive.default_archive_root(store.db_path)
    scope = _scope(DAYS[0])
    receipts_file = next((root / "receipts").rglob("*.parquet"))
    attempts_file = next((root / "attempts").rglob("*.parquet"))
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        before = store.source_evidence(**scope, mode="compact")
        # Preserve mtime to exercise identity/ctime rather than only timestamp checks.
        stat = receipts_file.stat()
        import duckdb
        frame = duckdb.sql("SELECT * FROM read_parquet(?)", params=[str(receipts_file)]).df()
        frame.loc[frame["receipt_id"] == "receipt-0-0", "selected_source"] = "new"
        archive._write_parquet(receipts_file, frame.to_dict("records"), frame.columns.tolist())
        os.utime(receipts_file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replaced = store.source_evidence(**scope, mode="compact")
        assert replaced != before
        with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_provenance_bytes=0):
            assert store.source_evidence(**scope, mode="compact") == replaced
        copy = attempts_file.with_name("extra.parquet")
        shutil.copy2(attempts_file, copy)
        added = store.source_evidence(**scope, mode="compact")
        assert added != replaced
        with panel_read_window(store, start=DAYS[0], end=DAYS[-1], max_provenance_bytes=0):
            assert store.source_evidence(**scope, mode="compact") == added
        copy.unlink()
        assert store.source_evidence(**scope, mode="compact") == replaced
    assert store.source_evidence(**scope, mode="compact") == replaced


@pytest.mark.parametrize("cold", [False, True])
def test_attempt_samples_batch_complete_prefix_and_limit_overflow_receipt(archive_store, monkeypatch, cold):
    from src.market.infrastructure.store_provenance_compact import _attempt_counts, _receipt_metadata

    store = archive_store
    target = "receipt-1-2" if cold else "receipt-4-2"
    if cold:
        import duckdb
        path = next((archive.default_archive_root(store.db_path) / "attempts").rglob("*.parquet"))
        frame = duckdb.sql("SELECT * FROM read_parquet(?)", params=[str(path)]).df()
        template = frame[frame["receipt_id"] == target].iloc[0].to_dict()
        rows = frame.to_dict("records")
        rows.extend({**template, "attempt_no": number, "payload_sha256": f"extra-{number}"}
                    for number in range(2, 82))
        archive._write_parquet(path, rows, frame.columns.tolist())
    else:
        for number in range(2, 82):
            store.conn.execute(
                "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,checked_at,"
                "rows,fields_json,payload_sha256) VALUES(?,?,?,?,?,?,?,?)",
                (target, number, "tdx", "selected", DAYS[0], 4, '["close"]', f"extra-{number}"),
            )
        store.conn.commit()
    scope = _scope(DAYS[-1])
    expected = store.source_evidence(**scope)
    compact_source_evidence(expected)
    ids = store._linked_receipt_ids(CODES, start=DAYS[0], end=DAYS[-1])
    metadata = _receipt_metadata(store, ids)
    counts = _attempt_counts(store, [str(row["receipt_id"]) for row in metadata])
    original_sample = []
    prefix_ids = []
    prefix_count = 0
    for row in metadata:
        receipt_id = str(row["receipt_id"])
        remaining = 50 - len(original_sample)
        if not remaining:
            break
        if counts[receipt_id]:
            if prefix_count + counts[receipt_id] <= 50:
                prefix_ids.append(receipt_id)
                prefix_count += counts[receipt_id]
            sample = store._attempts_by_receipt([receipt_id], max_rows=remaining)[receipt_id]
            original_sample.extend({"receipt_id": receipt_id, "code": str(row["code"]), **item}
                                   for item in sample)
    calls = []
    original = store._attempts_by_receipt

    def tracked(receipt_ids, **kwargs):
        result = original(receipt_ids, **kwargs)
        calls.append((list(receipt_ids), kwargs.get("max_rows"), sum(map(len, result.values()))))
        return result

    monkeypatch.setattr(store, "_attempts_by_receipt", tracked)
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        actual = store.source_evidence(**scope, mode="compact")
        again = store.source_evidence(**scope, mode="compact")
    assert actual == expected == again
    assert actual["attempts"] == original_sample
    assert len(actual["attempts"]) == 50
    assert len(prefix_ids) > 1
    assert [(ids, rows) for ids, limit, rows in calls if ids == prefix_ids and limit is None] == [
        (prefix_ids, prefix_count)
    ]
    assert prefix_count <= 50
    assert any(ids == [target] and 0 < limit < 50 and rows == limit for ids, limit, rows in calls)
    assert len([1 for ids, limit, _rows in calls if ids == [target] and limit is not None]) == 1


def test_archive_change_during_load_discards_partial_cache(archive_store, monkeypatch):
    import src.market.infrastructure.store_provenance_compact as compact

    store = archive_store
    scope = _scope(DAYS[0])
    original = compact._receipt_metadata
    called = 0

    def changing(store_arg, ids):
        nonlocal called
        rows = original(store_arg, ids)
        called += 1
        if called == 1:
            store.persist_source_receipt({
                "receipt_id": "orphan", "code": CODES[0], "lane": "hist_daily",
                "selected_source": "new", "state": "selected", "generated_at": DAYS[0],
                "attempts": [{"source_id": "new", "state": "selected"}],
            })
        return rows

    monkeypatch.setattr(compact, "_receipt_metadata", changing)
    scope = _scope(DAYS[1])
    with panel_read_window(store, start=DAYS[0], end=DAYS[-1]):
        actual = store.source_evidence(**scope, mode="compact")
        assert called >= 2
    assert actual == store.source_evidence(**scope, mode="compact")


def test_requests_outside_window_do_not_populate_provenance_cache(archive_store):
    store = archive_store
    scope = _scope(DAYS[0])
    expected = store.source_evidence(**scope, mode="compact")
    with panel_read_window(store, start=DAYS[1], end=DAYS[-1]):
        assert store.source_evidence(**scope, mode="compact") == expected
        assert not _ACTIVE_WINDOW.get().provenance_cache


def test_postgres_market_revision_change_invalidates_task_provenance():
    class Connection:
        def execute(self, sql):
            return type("Cursor", (), {"fetchone": lambda self: {
                "own_xid": None, "snapshot": "10:10:",
            }})()

    class Store:
        _use_postgres = True
        db_path = __file__
        revision = "1"

        def market_revision(self):
            return self.revision

    store = Store()
    state = _PanelWindow(store, Connection(), DAYS[0], DAYS[-1], 100)
    assert state.refresh_provenance()
    state.provenance_cache["counts"] = {"r": 1}
    state.provenance_bytes = 123
    store.revision = "2"
    assert state.refresh_provenance()
    assert not state.provenance_cache and state.provenance_bytes == 0
