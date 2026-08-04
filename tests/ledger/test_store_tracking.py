from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from src.ledger import PalaceError, PalaceStore, normalize_decision



class PalaceStoreTrackingAndCashTests(unittest.TestCase):
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


    def test_position_tracking_lifecycle(self) -> None:
        """open → update price → close → appears in summary."""
        tid = self.store.open_tracking(
            strategy_tag="strat-x",
            pool_id="POOL-2026-07-01",
            code="000001",
            name="平安银行",
            tier="core",
            signal_date="2026-07-01",
            entry_date="2026-07-02",
            hold_days=3,
            exit_by_date="2026-07-07",
            entry_price=12.5,
        )
        self.assertTrue(tid.startswith("PT-"))

        active = self.store.list_active_tracking("strat-x")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], tid)
        self.assertEqual(active[0]["status"], "active")

        self.store.close_tracking(tid, exit_price=13.0, actual_return=4.0, reason="expired")

        active_after = self.store.list_active_tracking("strat-x")
        self.assertEqual(len(active_after), 0)

        summary = self.store.tracking_summary("strat-x")
        self.assertEqual(len(summary), 1)
        row = summary[0]
        self.assertEqual(row["id"], tid)
        self.assertEqual(row["exit_price"], 13.0)
        self.assertAlmostEqual(row["actual_return"], 4.0)
        self.assertEqual(row["status"], "expired")

    def test_tracking_summary_only_closed(self) -> None:
        """tracking_summary excludes active records."""
        closed_id = self.store.open_tracking(
            strategy_tag="strat-y",
            pool_id="POOL-2026-07-02",
            code="000002",
            name="万科A",
            signal_date="2026-07-02",
            entry_date="2026-07-03",
            hold_days=3,
            exit_by_date="2026-07-08",
        )
        _active_id = self.store.open_tracking(
            strategy_tag="strat-y",
            pool_id="POOL-2026-07-02",
            code="000003",
            name="国药控股",
            signal_date="2026-07-02",
            entry_date="2026-07-03",
            hold_days=3,
            exit_by_date="2026-07-08",
        )
        self.store.close_tracking(closed_id, reason="expired")

        summary = self.store.tracking_summary("strat-y")
        ids = [r["id"] for r in summary]
        self.assertIn(closed_id, ids)
        self.assertNotIn(_active_id, ids)

    def test_broker_cash_rolls_with_buy_sell_and_cashflow(self) -> None:
        """券商口径：快照现金锚点后，买扣卖加、出入金滚动。"""
        self.store.record_snapshot(total_assets=100_000, cash=100_000, occurred_on="2026-07-01")
        self.assertAlmostEqual(self.store.broker_cash() or 0, 100_000)

        self.store.record_trade(
            action="BUY", code="600519", name="贵州茅台", shares=100, price=100, occurred_on="2026-07-02"
        )
        self.assertAlmostEqual(self.store.broker_cash() or 0, 90_000)

        self.store.record_trade(
            action="SELL", code="600519", shares=50, price=110, occurred_on="2026-07-03"
        )
        # 90000 + 50*110 = 95500
        self.assertAlmostEqual(self.store.broker_cash() or 0, 95_500)

        self.store.record_account_event(
            kind="CASHFLOW", amount=5_000, occurred_on="2026-07-04", note="入金"
        )
        self.assertAlmostEqual(self.store.broker_cash() or 0, 100_500)

        dash = self.store.dashboard_payload("2026-07-04")
        self.assertAlmostEqual(dash["account"]["cash"], 100_500)
        # 账面总资产 ≈ 现金 + 余仓成本 50*100=5000 → 105500（卖出后成本重算，用实际 cost_exposure）
        self.assertEqual(dash["account"]["cash"], self.store.broker_cash())

    def test_buy_rejects_when_cash_insufficient(self) -> None:
        self.store.record_snapshot(total_assets=1_000, cash=1_000, occurred_on="2026-07-01")
        with self.assertRaises(PalaceError):
            self.store.record_trade(
                action="BUY", code="600519", name="贵州茅台", shares=100, price=100, occurred_on="2026-07-02"
            )

    def test_opening_does_not_change_cash(self) -> None:
        self.store.record_snapshot(total_assets=50_000, cash=20_000, occurred_on="2026-07-01")
        self.store.record_trade(
            action="OPENING", code="300358", name="楚天科技", shares=1000, price=10, occurred_on="2026-07-01"
        )
        self.assertAlmostEqual(self.store.broker_cash() or 0, 20_000)

    def test_timeline_unknown_code_returns_empty(self) -> None:
        """行情点入未入账代码时时间线为空，不抛「账本中不存在」。"""
        self.assertEqual(self.store.timeline_payload("000001"), [])
        md = self.store.timeline_markdown("000001")
        self.assertIn("000001", md)
        self.assertIn("尚无记录", md)

    def test_dashboard_month_pnl_and_today_sells(self) -> None:
        """看板暴露本月已实现 + 当日卖出列表（同花顺式）。"""
        self.store.record_snapshot(total_assets=100_000, cash=100_000, occurred_on="2026-07-01")
        self.store.record_trade(
            action="BUY", code="300358", name="楚天科技", shares=1000, price=10, occurred_on="2026-07-02"
        )
        self.store.record_trade(
            action="SELL", code="300358", shares=400, price=11, occurred_on="2026-07-10", reason="减仓"
        )
        self.store.record_trade(
            action="SELL", code="300358", shares=200, price=12, occurred_on="2026-07-29", reason="再减"
        )
        # 上月卖出不应计入本月
        self.store.record_trade(
            action="BUY", code="000001", name="平安银行", shares=100, price=10, occurred_on="2026-06-20"
        )
        self.store.record_trade(
            action="SELL", code="000001", shares=100, price=11, occurred_on="2026-06-25"
        )

        dash = self.store.dashboard_payload("2026-07-29")
        # 部分卖出后已实现摊入余票成本：首卖 400；次卖 cost≈9.333 → 533.33；合计 933.33
        self.assertAlmostEqual(dash["account"]["month_realized_pnl"], 933.33)
        self.assertIsNotNone(dash["account"]["month_realized_pnl_pct"])
        sells = dash["today_sells"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["code"], "300358")
        self.assertEqual(sells[0]["shares"], 200)
        self.assertAlmostEqual(sells[0]["realized_pnl"], 533.33)
        self.assertAlmostEqual(sells[0]["realized_pnl_pct"], 28.57)
        curve = dash["month_pnl_curve"]
        self.assertGreaterEqual(len(curve), 29)
        self.assertEqual(curve[0]["date"], "2026-07-01")
        self.assertAlmostEqual(curve[0]["cumulative_pnl"], 0.0)
        self.assertEqual(curve[-1]["date"], "2026-07-29")
        self.assertAlmostEqual(curve[-1]["cumulative_pnl"], 933.33)
        # 首卖日累计应到 400
        day10 = next(p for p in curve if p["date"] == "2026-07-10")
        self.assertAlmostEqual(day10["cumulative_pnl"], 400.0)


if __name__ == "__main__":
    unittest.main()
