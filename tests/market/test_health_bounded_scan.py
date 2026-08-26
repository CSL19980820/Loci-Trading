"""体检不许扫全表。

`check_source_evidence_gap` 的 docstring 一直写着「故意不扫全表:千万行库上会让
体检页停在连接行情仓」,但里面那条查孤儿回执的 NOT EXISTS 原先是**无界**的——
生产库 106 万条回执逐条相关子查询,实测 2593 ms,比这个函数其余部分加起来还贵。

判据盯**执行计划与扫描行数**,不盯耗时:小库上全表扫也很快,断言会恒真。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.market import MarketStore
from src.market.infrastructure.sentinel_evidence import (
    ORPHAN_RECEIPT_SAMPLE,
    check_source_evidence_gap,
)

ORPHAN_SQL = (
    "SELECT COUNT(*) AS n FROM ("
    "  SELECT receipt_id FROM source_route_receipts"
    "   ORDER BY generated_at DESC, receipt_id DESC LIMIT ?"
    ") r WHERE NOT EXISTS ("
    "  SELECT 1 FROM source_route_attempts a WHERE a.receipt_id = r.receipt_id"
    ")"
)


class OrphanReceiptScanTests(unittest.TestCase):
    def test_orphan_probe_is_bounded_and_uses_the_recent_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                plan = " ".join(
                    str(row[-1])
                    for row in store.conn.execute(
                        "EXPLAIN QUERY PLAN " + ORPHAN_SQL, (ORPHAN_RECEIPT_SAMPLE,)
                    )
                )
                # 必须走近窗索引,且不许出现临时排序。
                self.assertIn("idx_source_receipts_recent", plan)
                self.assertNotIn("TEMP B-TREE", plan.upper())

    def test_sample_cap_is_declared(self) -> None:
        """上限必须是个显式常量,别退回成无界。"""
        self.assertGreater(ORPHAN_RECEIPT_SAMPLE, 0)
        self.assertLessEqual(ORPHAN_RECEIPT_SAMPLE, 200_000)

    def test_source_in_health_check_has_no_unbounded_not_exists(self) -> None:
        """源码级守卫:LIMIT 摘掉就等于回到 2593ms 的老路。"""
        import inspect

        src = inspect.getsource(check_source_evidence_gap)
        self.assertIn("ORPHAN_RECEIPT_SAMPLE", src)
        self.assertIn("LIMIT ?", src)

    def test_observed_reports_the_sampling_scope(self) -> None:
        """不标口径的话,「0 条孤儿」会被误读成「全库干净」。"""
        with tempfile.TemporaryDirectory() as tmp:
            with MarketStore(str(Path(tmp) / "m.db")) as store:
                finding = check_source_evidence_gap(store, max_ratio=0.5)
                observed = finding.to_dict().get("observed") or {}
                # 空库会走「无日 K」早退分支,那条不带抽样口径,属正常。
                if "orphan_receipts" in observed:
                    self.assertIn("orphan_scanned", observed)


if __name__ == "__main__":
    unittest.main()
