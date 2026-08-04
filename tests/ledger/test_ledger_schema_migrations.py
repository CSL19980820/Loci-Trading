from __future__ import annotations

import sqlite3
import unittest

from src.ledger.infrastructure.schema import SchemaMixin


class _FailingConnection:
    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")


class _SchemaHost(SchemaMixin):
    conn = _FailingConnection()


class SchemaMigrationTests(unittest.TestCase):
    def test_unexpected_migration_error_is_not_silently_ignored(self) -> None:
        with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
            _SchemaHost()._run_migrations()


if __name__ == "__main__":
    unittest.main()
