"""`idx_quotes_receipt` 的归属与磁盘回收。

背景：`docs/research/2026-08-mainstream-quant-benchmark.md` §2.1 实测该索引在权威库
上占 1,049 MB（全库 5,740 MB 的 18%），而它唯一的热路径消费者
`store_hot._purge_orphan_receipts` 只跑在热库。schema v8 起权威库不建、热库建。
"""
from __future__ import annotations

import sqlite3
import unittest

from src.market.application.reclaim import RECLAIMABLE_INDEXES, reclaim_market_db
from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.store_hot import open_market_hot


def _index_names(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


class ReceiptIndexOwnershipTest(unittest.TestCase):
    def test_authoritative_store_does_not_build_receipt_index(self):
        path = self.tmp / "market.db"
        MarketStore(path).close()
        self.assertNotIn("idx_quotes_receipt", _index_names(path))
        # 主查询索引必须还在，别把该留的一起删了。
        self.assertIn("idx_quotes_code_date", _index_names(path))

    def test_hot_store_keeps_receipt_index(self):
        path = self.tmp / "market_hot.db"
        open_market_hot(str(path)).close()
        self.assertIn("idx_quotes_receipt", _index_names(path))

    def test_reopening_an_old_db_drops_the_index(self):
        """模拟 v7 旧库：先手工建索引，再用权威库口径打开，迁移应删掉它。"""
        path = self.tmp / "legacy.db"
        MarketStore(path, keep_receipt_index=True).close()
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quotes_receipt ON quotes_daily(receipt_id)"
        )
        conn.execute("UPDATE meta SET value = '7' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()
        self.assertIn("idx_quotes_receipt", _index_names(path))
        from src.market.infrastructure.store_schema import _SCHEMA_READY

        _SCHEMA_READY.discard(str(path.resolve()))
        MarketStore(path).close()
        self.assertNotIn("idx_quotes_receipt", _index_names(path))

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()


class ReclaimTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "market.db"
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE quotes_daily (trade_date TEXT, code TEXT, close REAL, receipt_id TEXT)"
        )
        conn.executemany(
            "INSERT INTO quotes_daily VALUES (?,?,?,?)",
            [(f"2026-01-{i % 28 + 1:02d}", f"{i:06d}", float(i), f"r{i}") for i in range(20000)],
        )
        conn.execute("CREATE INDEX idx_quotes_receipt ON quotes_daily(receipt_id)")
        conn.commit()
        conn.close()

    def tearDown(self):
        self._dir.cleanup()

    def test_drops_index_and_shrinks_file_without_losing_rows(self):
        before = self.path.stat().st_size
        report = reclaim_market_db(self.path)
        self.assertEqual(report.dropped_indexes, list(RECLAIMABLE_INDEXES))
        self.assertTrue(report.vacuumed)
        self.assertLess(report.size_after, before)
        conn = sqlite3.connect(self.path)
        rows = conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
        conn.close()
        self.assertEqual(rows, 20000)

    def test_is_idempotent(self):
        reclaim_market_db(self.path)
        again = reclaim_market_db(self.path, vacuum=False)
        self.assertEqual(again.dropped_indexes, [])

    def test_skips_vacuum_when_disk_is_tight_but_still_drops(self):
        report = reclaim_market_db(self.path, free_bytes=1024)
        self.assertFalse(report.vacuumed)
        self.assertIn("不足", report.skipped_reason)
        self.assertEqual(report.dropped_indexes, list(RECLAIMABLE_INDEXES))

    def test_missing_db_raises(self):
        with self.assertRaises(FileNotFoundError):
            reclaim_market_db(self.path.parent / "nope.db")


if __name__ == "__main__":
    unittest.main()
