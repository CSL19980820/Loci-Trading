from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.ops.infrastructure.store import OpsStore


class _FailingConnection:
    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")


class OpsSchemaMigrationTests(unittest.TestCase):
    def test_unexpected_migration_error_is_not_silently_ignored(self) -> None:
        store = OpsStore.__new__(OpsStore)
        store.conn = _FailingConnection()

        with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
            store._run_migrations()

    def test_existing_strategy_docs_get_buy_instruction_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy-ops.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE strategy_docs (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    assumptions TEXT NOT NULL DEFAULT '',
                    market_cond TEXT NOT NULL DEFAULT '',
                    failure_modes TEXT NOT NULL DEFAULT '',
                    entry_timing TEXT NOT NULL DEFAULT '',
                    exit_rules TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '1',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()

            with OpsStore(db_path) as store:
                columns = {
                    row["name"]
                    for row in store.conn.execute("PRAGMA table_info(strategy_docs)").fetchall()
                }
        assert "entry_instructions" in columns


if __name__ == "__main__":
    unittest.main()
