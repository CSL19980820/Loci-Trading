"""回执表的「最近 N 条」排序索引。

`source_route_receipts` 在生产库有 106 万行。体检的 `check_ohlc_reject_rate` 与
`check_race_fallback_rate` 都用 `ORDER BY generated_at DESC, receipt_id DESC LIMIT 200`
取最近若干条——没有对应索引时 EQP 是 `SCAN` + `USE TEMP B-TREE FOR ORDER BY`,
为拿 200 行排序 106 万行,单条实测 948 ms;加索引后 0.1 ms。

**加索引必须配套 bump `SCHEMA_VERSION`**:`init_schema()` 只在版本不符时才跑 DDL,
不 bump 的话新索引永远只出现在新建的库上,已有生产库一辈子享受不到。
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.market import MarketStore
from src.market.infrastructure.store_schema import SCHEMA_VERSION

INDEX = "idx_source_receipts_recent"
RECENT_SQL = (
    "SELECT coverage_json FROM source_route_receipts"
    " ORDER BY generated_at DESC, receipt_id DESC LIMIT 200"
)


class RecentReceiptIndexTests(unittest.TestCase):
    def test_index_exists_on_a_fresh_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                names = {
                    row[0]
                    for row in store.conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                        " AND tbl_name='source_route_receipts'"
                    ).fetchall()
                }
                self.assertIn(INDEX, names)

    def test_recent_query_uses_the_index_not_a_temp_sort(self) -> None:
        """判据要盯执行计划,不是盯耗时——小库上全表扫也很快,断言会恒真。"""
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                plan = " ".join(
                    str(row[-1])
                    for row in store.conn.execute("EXPLAIN QUERY PLAN " + RECENT_SQL)
                )
                self.assertIn(INDEX, plan)
                self.assertNotIn("TEMP B-TREE", plan.upper())

    def test_schema_version_was_bumped_for_the_index(self) -> None:
        """不 bump 的话已有库跑不到 DDL,索引只落在新库上。"""
        self.assertGreaterEqual(SCHEMA_VERSION, 7)

    def test_existing_db_gets_the_index_after_upgrade(self) -> None:
        """模拟老库:建表但把 schema_version 写成旧值,再开一次必须补上索引。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            with MarketStore(path) as store:
                store.conn.execute("DROP INDEX IF EXISTS " + INDEX)
                store.conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema_version'", ("1",)
                )
                store.conn.commit()

            # _SCHEMA_READY 是进程级缓存,直连确认索引确实没了
            raw = sqlite3.connect(path)
            before = {
                row[0]
                for row in raw.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            raw.close()
            self.assertNotIn(INDEX, before)

            from src.market.infrastructure.store import _SCHEMA_READY

            _SCHEMA_READY.clear()
            with MarketStore(path) as store:
                after = {
                    row[0]
                    for row in store.conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    ).fetchall()
                }
                self.assertIn(INDEX, after)


if __name__ == "__main__":
    unittest.main()
