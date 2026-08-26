"""候选池写入语义 + review 只读缓存指纹。

从已删除的 test_store_tracking.py 搬过来：那个文件里成交/持仓跟踪的断言随表下线，
候选池部分和「等长改判必须换指纹」这一条是候选池的网，必须留着。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ledger import PalaceStore


class CandidatePoolStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "palace.db"
        self.store = PalaceStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_candidate_same_day_pool_code_is_idempotent(self) -> None:
        first = self.store.record_candidate(
            code="600178",
            name="东安动力",
            score=72,
            decision="值得做",
            reason="等回踩",
            occurred_on="2026-07-24",
            pool_id="POOL-2026-07-24",
        )
        same = self.store.record_candidate(
            code="600178",
            name="东安动力",
            score=72,
            decision="值得做",
            reason="等回踩",
            occurred_on="2026-07-24",
            pool_id="POOL-2026-07-24",
        )
        revised = self.store.record_candidate(
            code="600178",
            name="东安动力",
            score=75,
            decision="值得做",
            reason="回踩确认",
            occurred_on="2026-07-24",
            pool_id="POOL-2026-07-24",
        )
        payload = self.store.candidates_payload("2026-07-24")
        self.assertEqual(first, same)
        self.assertEqual(first, revised)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["score"], 75.0)
        self.assertEqual(payload[0]["reason"], "回踩确认")
        self.assertEqual(payload[0]["decision"], "精选")
        self.assertEqual(payload[0]["rule_version"], "潜龙")
        count = self.store.conn.execute(
            "SELECT COUNT(*) AS n FROM candidate_reviews WHERE code = '600178'"
        ).fetchone()["n"]
        self.assertEqual(int(count), 1)

    def test_candidates_list_strategy_fuzzy_match(self) -> None:
        self.store.record_candidate(
            code="600150", name="中国船舶", decision="精选", reason="a",
            occurred_on="2026-07-29", rule_version="潜龙",
        )
        self.store.record_candidate(
            code="000001", name="平安银行", decision="落选", reason="b",
            occurred_on="2026-07-29", rule_version="卢高文·三外有三",
        )
        by_partial = self.store.candidates_list_payload(strategy="潜")
        self.assertEqual([r["code"] for r in by_partial], ["600150"])
        by_alias = self.store.candidates_list_payload(strategy="qianlong-v1")
        self.assertEqual([r["code"] for r in by_alias], ["600150"])
        by_lugw = self.store.candidates_list_payload(strategy="三外")
        self.assertEqual([r["code"] for r in by_lugw], ["000001"])

    def test_candidate_timing_and_reason_normalize_to_chinese(self) -> None:
        self.store.record_candidate(
            code="600150",
            name="中国船舶",
            decision="精选",
            reason="vol_ratio=2.1 D-flat next_open 错过W 放量2.3x",
            timing="D-flat",
            occurred_on="2026-07-29",
            rule_version="qianlong-v1",
        )
        self.store.record_candidate(
            code="002582",
            name="好想你",
            decision="精选",
            reason="lugw-chouma 选中：COST15=8.81，集中度=0.12",
            timing="next_open",
            occurred_on="2026-07-29",
            rule_version="lugw-chouma",
        )
        rows = {r["code"]: r for r in self.store.candidates_payload("2026-07-29")}
        ship = rows["600150"]
        self.assertEqual(ship["timing"], "平开")
        self.assertIn("量比=2.1", ship["reason"])
        self.assertIn("平开", ship["reason"])
        self.assertIn("次日开盘", ship["reason"])
        self.assertIn("错过尾盘", ship["reason"])
        self.assertIn("2.3倍", ship["reason"])
        self.assertEqual(ship["rule_version"], "潜龙")
        chouma = rows["002582"]
        self.assertEqual(chouma["rule_version"], "筹码峰突破")
        self.assertEqual(chouma["timing"], "次日开盘")
        self.assertIn("筹码峰突破选中", chouma["reason"])
        self.assertIn("筹码15%=8.81", chouma["reason"])

    def test_candidate_decision_rejects_unknown(self) -> None:
        with self.assertRaises(Exception):
            self.store.record_candidate(
                code="600178",
                name="东安动力",
                decision="随便写",
                reason="测试",
                occurred_on="2026-07-24",
            )

    def test_candidate_aliases_normalize_to_canonical(self) -> None:
        self.store.record_candidate(
            code="600001", name="甲", decision="值得做", reason="薄仓", occurred_on="2026-07-01",
        )
        self.store.record_candidate(
            code="600002", name="乙", decision="持仓", reason="已持不加", occurred_on="2026-07-01",
        )
        self.store.record_candidate(
            code="600003", name="丙", decision="reject", reason="追高", occurred_on="2026-07-01",
        )
        rows = {r["code"]: r for r in self.store.candidates_payload("2026-07-01")}
        self.assertEqual(rows["600001"]["decision"], "精选")
        self.assertEqual(rows["600002"]["decision"], "观察")
        self.assertEqual(rows["600003"]["decision"], "落选")
        self.assertTrue(all(r["rule_version"] == "潜龙" for r in rows.values()))

    def test_timeline_unknown_code_returns_empty(self) -> None:
        """行情点入未入账代码时时间线为空，不抛「账本中不存在」。"""
        self.assertEqual(self.store.timeline_payload("000001"), [])
        md = self.store.timeline_markdown("000001")
        self.assertIn("000001", md)
        self.assertIn("尚无记录", md)

    def test_review_read_fingerprint_changes_on_any_write(self) -> None:
        """复盘缓存键：候选写入、**等长改判**、预案与复盘写入都必须换指纹。

        改判走 record_candidate 的 UPDATE 分支：条数、rowid、created_at 全不变，
        只有逐行摘要看得出来。指纹不变 = review 端点的 LRU 会喂出陈数据，
        所以这条挡的是「把 GROUP_CONCAT 简化成 COUNT(*)」。
        """
        base = self.store.review_read_fingerprint()
        self.assertEqual(base, self.store.review_read_fingerprint())

        self.store.record_candidate(
            code="600178", name="东安动力", decision="精选", reason="等回踩",
            occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        after_candidate = self.store.review_read_fingerprint()
        self.assertNotEqual(base, after_candidate)

        # 同日同池同标的改判：原地 UPDATE，等长裁决，行数不变
        self.store.record_candidate(
            code="600178", name="东安动力", decision="落选", reason="等回踩",
            occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        rows = self.store.conn.execute("SELECT COUNT(*) FROM candidate_reviews").fetchone()[0]
        self.assertEqual(rows, 1)
        after_regrade = self.store.review_read_fingerprint()
        self.assertNotEqual(after_candidate, after_regrade)

        plan_id = self.store.record_plan(
            code="600178", title="回踩确认", scenario="站上均线再进", occurred_on="2026-07-24",
        )
        after_plan = self.store.review_read_fingerprint()
        self.assertNotEqual(after_regrade, after_plan)

        self.store.record_review(
            entity_type="plan", entity_id=plan_id, outcome="按计划出场",
            reviewed_on="2026-07-30", return_pct=4.0,
        )
        self.assertNotEqual(after_plan, self.store.review_read_fingerprint())

    def test_fingerprint_is_stable_without_writes(self) -> None:
        """只读不写时指纹必须逐次相同，否则缓存永远命不中。"""
        self.store.record_candidate(
            code="600150", name="中国船舶", decision="精选", reason="放量",
            occurred_on="2026-07-29", pool_id="POOL-2026-07-29",
        )
        first = self.store.review_read_fingerprint()
        self.store.candidates_payload("2026-07-29")
        self.assertEqual(first, self.store.review_read_fingerprint())
