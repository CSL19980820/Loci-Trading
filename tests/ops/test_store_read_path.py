"""Settings reads must not rerun migrations or compete with a trading writer."""
import sqlite3

import pytest

from src.ops import OpsStore
from src.ops.infrastructure import store as store_module


def test_reopening_current_store_is_read_only(tmp_path):
    path = tmp_path / "ops.db"
    with OpsStore(path):
        pass
    with OpsStore(path) as reader:
        assert reader.conn.total_changes == 0
        assert not reader.conn.in_transaction


def test_reader_does_not_wait_for_writer(tmp_path, monkeypatch):
    path = tmp_path / "ops.db"
    real_connect = sqlite3.connect

    class BoundedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("PRAGMA busy_timeout="):
                sql = "PRAGMA busy_timeout=100"
            return super().execute(sql, parameters)

    with OpsStore(path) as writer:
        writer.conn.execute("BEGIN IMMEDIATE")
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: real_connect(
            *a, **{**kw, "factory": BoundedConnection}))
        try:
            with OpsStore(path) as reader:
                assert reader.conn.total_changes == 0
                assert reader.list_jobs() == []
        finally:
            writer.conn.rollback()


def test_read_fast_path_survives_process_cache_reset(tmp_path, monkeypatch):
    path = tmp_path / "ops.db"
    with OpsStore(path):
        pass
    store_module._SCHEMA_READY.clear()
    monkeypatch.setattr(OpsStore, "_apply_schema_compat", lambda self: pytest.fail("already migrated"))
    with OpsStore(path) as reader:
        assert reader.conn.total_changes == 0


def test_recreated_file_at_same_path_is_initialized(tmp_path):
    path = tmp_path / "ops.db"
    with OpsStore(path):
        pass
    path.unlink()
    with OpsStore(path) as reader:
        assert reader.list_jobs() == []


def test_schema_change_repairs_missing_index(tmp_path):
    path = tmp_path / "ops.db"
    with OpsStore(path) as store:
        store.conn.execute("DROP INDEX idx_runs_heartbeat")
    with OpsStore(path) as reader:
        assert reader.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='idx_runs_heartbeat'").fetchone()
    with OpsStore(path) as reader:
        assert reader.conn.total_changes == 0


def test_changed_migration_list_is_not_skipped(tmp_path, monkeypatch):
    path = tmp_path / "ops.db"
    with OpsStore(path):
        pass
    monkeypatch.setattr(store_module, "_MIGRATIONS", [*store_module._MIGRATIONS,
                         "CREATE TABLE IF NOT EXISTS test_upgrade (id INTEGER PRIMARY KEY)"])
    with OpsStore(path) as reader:
        assert reader.conn.execute("SELECT count(*) FROM test_upgrade").fetchone()[0] == 0
    with OpsStore(path) as reader:
        assert reader.conn.total_changes == 0
