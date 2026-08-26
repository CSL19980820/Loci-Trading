from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.ledger import PalaceStore
from src.ledger.infrastructure.schema import SchemaMixin
from src.ledger.infrastructure.store_types import SCHEMA_VERSION, _SCHEMA_READY


#: v10 下线的七张表。既是断言口径，也是「别偷偷加回来」的清单。
RETIRED = (
    "position_events",
    "position_tracking",
    "account_events",
    "account_snapshots",
    "daily_pnl_ledger",
    "holdings",
    "ledger_write_receipts",
)

#: 候选池/股池/预案/复盘/AI 判定这几张必须原样活着。
SURVIVING = ("meta", "stocks", "candidate_reviews", "plans", "reviews", "ai_judgments")


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


class _FailingConnection:
    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")


class _SchemaHost(SchemaMixin):
    conn = _FailingConnection()


class SchemaMigrationTests(unittest.TestCase):
    def test_unexpected_migration_error_is_not_silently_ignored(self) -> None:
        with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
            _SchemaHost()._run_migrations()

    def test_fresh_database_never_creates_the_retired_tables(self) -> None:
        """空库建出来就不该有持仓/成交/账户表。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fresh.db"
            with PalaceStore(db) as store:
                names = _tables(store.conn)
            for table in RETIRED:
                self.assertNotIn(table, names)
            for table in SURVIVING:
                self.assertIn(table, names)

    def test_existing_database_gets_the_retired_tables_dropped(self) -> None:
        """已有库打开一次就要把七张表 DROP 掉，且候选事实一行不少。

        版本号故意写成旧值：init_schema 只有在版本不一致时才跑 DDL/迁移，
        所以「加删 DDL 必须配套 bump SCHEMA_VERSION」这条也一并钉在这里。
        """
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]',
                         note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE candidate_reviews (id TEXT PRIMARY KEY, occurred_on TEXT NOT NULL, pool_id TEXT NOT NULL,
                         code TEXT NOT NULL, name TEXT NOT NULL, score REAL, decision TEXT NOT NULL,
                         timing TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL, rule_version TEXT NOT NULL DEFAULT '潜龙',
                         evidence_json TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL DEFAULT 'manual',
                         created_at TEXT NOT NULL);
                    CREATE TABLE plans (id TEXT PRIMARY KEY, occurred_on TEXT NOT NULL, code TEXT NOT NULL,
                         title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', scenario TEXT NOT NULL,
                         entry_zone TEXT NOT NULL DEFAULT '', stop_price REAL, target_price REAL, layers REAL,
                         invalidation TEXT NOT NULL DEFAULT '', rule_version TEXT NOT NULL DEFAULT '潜龙',
                         source TEXT NOT NULL DEFAULT 'manual', supersedes_id TEXT, note TEXT NOT NULL DEFAULT '',
                         created_at TEXT NOT NULL);
                    CREATE TABLE reviews (id TEXT PRIMARY KEY, reviewed_on TEXT NOT NULL, entity_type TEXT NOT NULL,
                         entity_id TEXT NOT NULL, strategy_tag TEXT NOT NULL DEFAULT '潜龙', outcome TEXT NOT NULL,
                         return_pct REAL, max_favorable_pct REAL, max_adverse_pct REAL, lesson TEXT NOT NULL DEFAULT '',
                         next_rule TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL);
                    CREATE TABLE holdings (code TEXT PRIMARY KEY, name TEXT NOT NULL, shares INTEGER NOT NULL,
                         cost REAL NOT NULL, updated_on TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
                    CREATE TABLE position_events (id TEXT PRIMARY KEY, occurred_on TEXT NOT NULL, code TEXT NOT NULL,
                         name TEXT NOT NULL, action TEXT NOT NULL, shares INTEGER NOT NULL, price REAL NOT NULL,
                         shares_before INTEGER NOT NULL, shares_after INTEGER NOT NULL, cost_before REAL NOT NULL,
                         cost_after REAL NOT NULL, realized_pnl REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
                         source TEXT NOT NULL DEFAULT 'manual', correlation_id TEXT NOT NULL DEFAULT '',
                         metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
                    CREATE TABLE position_tracking (id TEXT PRIMARY KEY, strategy_tag TEXT NOT NULL, pool_id TEXT NOT NULL,
                         code TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', tier TEXT NOT NULL DEFAULT 'core',
                         signal_date TEXT NOT NULL, entry_date TEXT NOT NULL, hold_days INTEGER NOT NULL DEFAULT 3,
                         exit_by_date TEXT NOT NULL, entry_price REAL, exit_price REAL, max_price REAL, min_price REAL,
                         actual_return REAL, status TEXT NOT NULL DEFAULT 'active', closed_reason TEXT NOT NULL DEFAULT '',
                         created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE account_events (id TEXT PRIMARY KEY, occurred_on TEXT NOT NULL, kind TEXT NOT NULL,
                         amount REAL NOT NULL, note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
                         metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
                    CREATE TABLE account_snapshots (id TEXT PRIMARY KEY, occurred_on TEXT NOT NULL,
                         total_assets REAL NOT NULL, cash REAL, note TEXT NOT NULL DEFAULT '',
                         source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL);
                    CREATE TABLE daily_pnl_ledger (occurred_on TEXT PRIMARY KEY, broker_pnl REAL NOT NULL, market_pnl REAL,
                         gap REAL, source TEXT NOT NULL DEFAULT 'market', note TEXT NOT NULL DEFAULT '',
                         legs_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}',
                         created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE ledger_write_receipts (idempotency_key TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                         result_json TEXT NOT NULL, created_at TEXT NOT NULL);
                    """
                )
                conn.execute(
                    "INSERT INTO stocks(code, name, created_at, updated_at)"
                    " VALUES ('600178', '东安动力', '2026-07-24', '2026-07-24')"
                )
                conn.execute(
                    "INSERT INTO candidate_reviews(id, occurred_on, pool_id, code, name, decision, reason, created_at)"
                    " VALUES ('C-1', '2026-07-24', 'POOL', '600178', '东安动力', '精选', '保留我', '2026-07-24')"
                )
                conn.execute(
                    "INSERT INTO holdings(code, name, shares, cost, updated_on)"
                    " VALUES ('600178', '东安动力', 100, 10.0, '2026-07-24')"
                )
                conn.execute(
                    "INSERT INTO meta(key, value, updated_at) VALUES ('schema_version', '9', '2026-07-24')"
                )
                conn.commit()

            _SCHEMA_READY.discard(str(db.resolve()))
            with PalaceStore(db) as store:
                names = _tables(store.conn)
                for table in RETIRED:
                    self.assertNotIn(table, names)
                kept = store.conn.execute(
                    "SELECT COUNT(*) FROM candidate_reviews"
                ).fetchone()[0]
                self.assertEqual(int(kept), 1)
                version = store.conn.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0]
                self.assertEqual(str(version), str(SCHEMA_VERSION))

    def test_dropping_is_idempotent_on_a_second_open(self) -> None:
        """同一个库连开两次不能因为表已经没了而报错。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "twice.db"
            with PalaceStore(db) as store:
                store.record_candidate(
                    code="600178", name="东安动力", decision="精选", reason="首开",
                    occurred_on="2026-07-24", pool_id="POOL",
                )
            _SCHEMA_READY.discard(str(db.resolve()))
            with PalaceStore(db) as store:
                self.assertEqual(len(store.candidates_payload("2026-07-24")), 1)
                for table in RETIRED:
                    self.assertNotIn(table, _tables(store.conn))


if __name__ == "__main__":
    unittest.main()
