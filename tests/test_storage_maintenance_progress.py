"""存储维护的有界进度、孤儿扫描与增量回收回归。"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from src.market import MarketStore
from src.market.application import provenance_archive
from src.market.application import storage_governance
from src.market.application.reclaim import reclaim_market_db
from src.market.application.storage_governance import (
    StoragePolicy,
    _delete_orphan_attempts,
    _incremental_reclaim,
    run_storage_maintenance,
)


def _orphan_store():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE source_route_receipts(receipt_id TEXT PRIMARY KEY);"
        "CREATE TABLE source_route_attempts(receipt_id TEXT, attempt_no INTEGER,"
        "PRIMARY KEY(receipt_id, attempt_no)) WITHOUT ROWID;"
    )
    conn.executemany("INSERT INTO source_route_receipts VALUES (?)",
                     [(f"kept-{n:05}",) for n in range(3000)])
    conn.executemany("INSERT INTO source_route_attempts VALUES (?, ?)",
                     [(f"kept-{n:05}", 0) for n in range(3000)]
                     + [("orphan", n) for n in range(200)])
    conn.commit()
    return conn


def test_orphan_batches_scan_retained_prefix_once_and_preserve_linked_attempts():
    def count_steps(run):
        conn = _orphan_store()
        calls = []
        conn.set_progress_handler(lambda: calls.append(1) or 0, 100)
        deleted = run(conn)
        conn.set_progress_handler(None, 0)
        assert deleted == 200
        assert conn.execute("SELECT COUNT(*) FROM source_route_attempts").fetchone()[0] == 3000
        assert _delete_orphan_attempts(conn, batch_size=10) == 0
        conn.close()
        return len(calls)

    def old_scan(conn):
        total = 0
        while rows := conn.execute(
            "SELECT a.receipt_id,a.attempt_no FROM source_route_attempts a "
            "WHERE NOT EXISTS (SELECT 1 FROM source_route_receipts r "
            "WHERE r.receipt_id=a.receipt_id) LIMIT 10"
        ).fetchall():
            conn.executemany("DELETE FROM source_route_attempts WHERE receipt_id=? AND attempt_no=?",
                             rows)
            conn.commit()
            total += len(rows)
        return total

    previous_steps = count_steps(old_scan)
    current_steps = count_steps(lambda conn: _delete_orphan_attempts(conn, batch_size=10))
    assert current_steps < previous_steps / 5


def test_orphan_delete_rechecks_receipt_created_after_candidate_read():
    class ReceiptArrives(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                super().execute("INSERT OR IGNORE INTO source_route_receipts VALUES ('restored')")
                self.commit()
            return super().execute(sql, parameters)

    conn = sqlite3.connect(":memory:", factory=ReceiptArrives)
    conn.executescript(
        "CREATE TABLE source_route_receipts(receipt_id TEXT PRIMARY KEY);"
        "CREATE TABLE source_route_attempts(receipt_id TEXT, attempt_no INTEGER,"
        "PRIMARY KEY(receipt_id, attempt_no)) WITHOUT ROWID;"
        "INSERT INTO source_route_attempts VALUES ('orphan',0),('restored',0);"
    )
    try:
        assert _delete_orphan_attempts(conn, batch_size=10) == 1
        assert conn.execute("SELECT receipt_id FROM source_route_attempts").fetchone()[0] == "restored"
    finally:
        conn.close()


def _market_with_free_pages(tmp_path, *, journal="WAL"):
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    with MarketStore(path) as store:
        store.conn.executemany(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,state,generated_at) "
            "VALUES (?, '000001', 'hist_daily', 'selected', '2024-01-01T00:00:00+00:00')",
            [("receipt-a",), ("receipt-b",)],
        )
        store.conn.executemany(
            "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state) "
            "VALUES (?,0,'fixture','selected')", [("receipt-a",), ("receipt-b",)],
        )
        store.conn.execute("CREATE TABLE space_fixture (id INTEGER PRIMARY KEY, payload BLOB)")
        store.conn.executemany("INSERT INTO space_fixture VALUES (?, zeroblob(4096))",
                               [(n,) for n in range(200)])
        store.conn.commit()
        store.conn.execute("DELETE FROM space_fixture WHERE id % 2 = 0")
        store.conn.commit()
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA journal_mode={journal}")
    return path


@pytest.mark.parametrize("journal", ["WAL", "DELETE"])
def test_incremental_reclaim_consumes_all_pages_and_preserves_live_rows(tmp_path, journal):
    path = _market_with_free_pages(tmp_path, journal=journal)
    size_before = path.stat().st_size
    report = _incremental_reclaim(path, StoragePolicy(incremental_vacuum_pages=7))
    assert report["vacuumed"] is True
    assert report["batches"] > 1
    assert report["freelist_pages_before"] > 7
    assert report["freelist_pages_after"] == 0
    assert path.stat().st_size < size_before
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*), SUM(LENGTH(payload)) FROM space_fixture").fetchone() == (100, 409600)
        assert conn.execute("SELECT COUNT(*) FROM source_route_receipts").fetchone()[0] == 2


def test_incremental_reclaim_honors_budget_and_resumes(tmp_path):
    path = _market_with_free_pages(tmp_path)
    report = _incremental_reclaim(path, StoragePolicy(incremental_vacuum_pages=7,
                                                     max_incremental_batches=1))
    assert report["batches"] == 1
    assert report["freelist_pages_before"] - report["freelist_pages_after"] == 7
    assert report["freelist_pages_after"] > 0
    assert "批次上限" in report["skipped_reason"]
    resumed = _incremental_reclaim(path, StoragePolicy())
    assert resumed["freelist_pages_after"] == 0


def test_incremental_reclaim_defers_without_batch_headroom(tmp_path, monkeypatch):
    path = _market_with_free_pages(tmp_path)
    size_before = path.stat().st_size
    monkeypatch.setattr(storage_governance.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1))
    report = _incremental_reclaim(path, StoragePolicy())
    assert report["vacuumed"] is False
    assert report["batches"] == 0
    assert report["freelist_pages_before"] == report["freelist_pages_after"]
    assert "可用空间不足" in report["skipped_reason"]
    assert path.stat().st_size == size_before


def test_ordinary_maintenance_does_not_migrate_existing_auto_vacuum_mode(tmp_path):
    path = tmp_path / "market.db"
    with MarketStore(path) as store:
        assert store.conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0
    report = run_storage_maintenance(path)
    assert report["errors"] == []
    assert report["sqlite_pages"]["auto_vacuum"] == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0


def test_full_vacuum_rejects_less_than_two_copies_of_headroom(tmp_path):
    path = _market_with_free_pages(tmp_path)
    report = reclaim_market_db(path, free_bytes=int(path.stat().st_size * 1.5))
    assert report.vacuumed is False
    assert "不足" in report.skipped_reason


def test_reclaim_drops_obsolete_source_attempt_index(tmp_path):
    path = tmp_path / "market.db"
    with MarketStore(path) as store:
        store.conn.execute(
            "CREATE INDEX idx_source_attempts_source "
            "ON source_route_attempts(source_id, state)"
        )
        store.conn.commit()
    report = reclaim_market_db(path, vacuum=False)
    assert report.dropped_indexes == ["idx_source_attempts_source"]
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_source_attempts_source",),
        ).fetchone() is None


def test_archive_budget_reports_backlog_and_still_reclaims_committed_free_pages(tmp_path):
    path = _market_with_free_pages(tmp_path)
    policy = StoragePolicy(batch_size=1, max_archive_batches=1)
    report = run_storage_maintenance(path, policy=policy)
    assert report["errors"] == []
    assert report["remaining"] == {"selected_receipts": 1}
    assert len(report["warnings"]) == 1
    assert report["completed"] is False
    assert report["deleted"]["selected_receipts"] == 1
    assert report["deleted"]["selected_attempts"] == 1
    assert report["vacuum"]["mode"] == "incremental"
    assert report["vacuum"]["vacuumed"] is True
    archived = provenance_archive.query_archived_receipts(path.parent / "archives" / "market-provenance",
                                                          ["receipt-a"])
    assert archived[0]["receipt_id"] == "receipt-a"
    resumed = run_storage_maintenance(path, policy=policy)
    assert resumed["errors"] == resumed["warnings"] == []
    assert resumed["remaining"] == {"selected_receipts": 0}
    assert resumed["completed"] is True


def test_archive_failure_preserves_rows_and_blocks_compaction(tmp_path, monkeypatch):
    path = _market_with_free_pages(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("archive storage unavailable")

    monkeypatch.setattr(provenance_archive, "_write_parquet", fail)
    report = run_storage_maintenance(path)
    assert "archive storage unavailable" in report["errors"][0]
    assert report["completed"] is False
    assert report["vacuum"]["vacuumed"] is False
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_route_receipts").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM source_route_attempts").fetchone()[0] == 2
