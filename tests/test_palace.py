from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.palace import PalaceError, PalaceStore


class PalaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "palace.db"
        self.store = PalaceStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_partial_sell_reprices_remaining_cost_and_keeps_audit_event(self) -> None:
        self.store.record_trade(action="BUY", code="300358", name="楚天科技", shares=100, price=10, occurred_on="2026-07-01")
        self.store.record_trade(action="BUY", code="300358", shares=100, price=12, occurred_on="2026-07-02")
        result = self.store.record_trade(action="SELL", code="300358", shares=50, price=10, occurred_on="2026-07-03")

        position = self.store.list_positions()[0]
        self.assertEqual(position.shares, 150)
        self.assertAlmostEqual(position.cost, 11.333333, places=5)
        self.assertEqual(result["realized_pnl"], -50.0)
        self.assertEqual(self.store.realized_pnl(), -50.0)
        self.assertIn("SELL 50股", self.store.timeline_markdown("300358"))

    def test_rejects_sell_larger_than_position(self) -> None:
        self.store.record_trade(action="BUY", code="300358", name="楚天科技", shares=100, price=10)
        with self.assertRaises(PalaceError):
            self.store.record_trade(action="SELL", code="300358", shares=101, price=10)

    def test_dashboard_connects_candidate_plan_and_review(self) -> None:
        self.store.record_trade(action="BUY", code="300358", name="楚天科技", shares=100, price=8.3)
        self.store.record_snapshot(total_assets=206400, occurred_on="2026-07-24")
        candidate_id = self.store.record_candidate(
            code="300358", name="楚天科技", score=81, decision="重点", timing="D-low",
            reason="记录回踩确认条件", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        plan_id = self.store.record_plan(
            code="300358", title="首仓预案", scenario="回踩企稳", entry_zone="8.10-8.30",
            stop_price=7.76, target_price=9.1, layers=1, invalidation="跌破结构位", occurred_on="2026-07-24",
        )
        self.store.record_review(
            entity_type="candidate", entity_id=candidate_id, outcome="T+5 回看", return_pct=3.2,
            lesson="等待回踩确认", next_rule="保留 D-low", reviewed_on="2026-07-29",
        )
        dashboard = self.store.dashboard_markdown("2026-07-24")
        self.assertIn("POOL-2026-07-24", dashboard)
        self.assertIn(plan_id, dashboard)
        self.assertIn("3.20%", dashboard)

    def test_imports_skill_state_once_as_opening_snapshot(self) -> None:
        state_path = Path(self.temp.name) / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "updatedAt": "2026-07-24",
                    "totalAssets": 206400,
                    "realizedPnlCumulative": -11104,
                    "holdings": [{"name": "楚天科技", "code": "300358", "cost": 8.3, "shares": 3200, "layers": 1.29}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = self.store.import_qianlong_state(state_path)
        self.assertEqual(len(result["position_events"]), 1)
        self.assertEqual(self.store.list_positions()[0].shares, 3200)
        self.assertEqual(self.store.realized_pnl(), -11104.0)
        dashboard = self.store.dashboard_payload("2026-07-24")
        self.assertIsNone(dashboard["account"]["today_realized_pnl"])
        self.assertIn("累计盈亏基线", dashboard["account"]["today_realized_note"])
        with self.assertRaises(PalaceError):
            self.store.import_qianlong_state(state_path)

    def test_journal_pool_review_and_analytics_payloads(self) -> None:
        self.store.record_trade(
            action="BUY", code="300358", name="楚天科技", shares=100, price=8.3, occurred_on="2026-07-20"
        )
        self.store.record_trade(
            action="SELL", code="300358", shares=40, price=8.8, occurred_on="2026-07-22", reason="减仓"
        )
        self.store.record_candidate(
            code="300358", name="楚天科技", score=81, decision="重点", timing="D-low",
            reason="结构回踩", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        self.store.record_candidate(
            code="000722", name="湖南发展", score=55, decision="落选", timing="观望",
            reason="量能不足", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        candidate_id = self.store.record_candidate(
            code="002230", name="科大讯飞", score=72, decision="观察", timing="D0",
            reason="等待确认", occurred_on="2026-07-24", pool_id="POOL-2026-07-24",
        )
        self.store.record_review(
            entity_type="candidate",
            entity_id=candidate_id,
            outcome="T+3 回看",
            return_pct=1.5,
            lesson="观察池也要记失效条件",
            next_rule="观察票单独样本",
            reviewed_on="2026-07-27",
        )

        trades = self.store.trades_payload()
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["action"], "SELL")
        self.assertEqual(trades[0]["realized_pnl"], 20.0)

        pools = self.store.pool_dates_payload()
        self.assertEqual(pools[0]["total"], 3)
        self.assertEqual(pools[0]["selected"], 1)
        self.assertEqual(pools[0]["filtered"], 2)

        day = self.store.pool_day_payload("2026-07-24")
        self.assertEqual(day["selected_count"], 1)
        self.assertEqual(day["filtered_count"], 2)
        self.assertEqual(day["selected"][0]["code"], "300358")

        reviews = self.store.reviews_payload()
        self.assertEqual(reviews[0]["lesson"], "观察池也要记失效条件")

        analytics = self.store.analytics_payload()
        self.assertGreaterEqual(len(analytics["equity_curve"]), 1)
        self.assertEqual(analytics["equity_curve"][-1]["cumulative_pnl"], 20.0)
        self.assertTrue(any(item["decision"] == "重点" for item in analytics["decisions"]))

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
        count = self.store.conn.execute(
            "SELECT COUNT(*) AS n FROM candidate_reviews WHERE code = '600178'"
        ).fetchone()["n"]
        self.assertEqual(int(count), 1)


if __name__ == "__main__":
    unittest.main()
