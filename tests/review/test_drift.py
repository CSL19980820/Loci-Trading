"""回测-实盘偏离：计划写入 + 真实成交对比分类。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.ledger import PalaceStore
from src.market.infrastructure.store import MarketStore
from src.review import compute_drift, evaluate_candidates, sync_position_tracking, track_candidate_outcomes

DAYS = [f"2026-03-{day:02d}" for day in range(2, 27)]


def _quotes(closes: list[float], *, spread: float = 0.02) -> pd.DataFrame:
    n = len(closes)
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": DAYS[:n],
            "open": close,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": np.full(n, 1_000_000.0),
            "amount": close * 1_000_000.0,
            "outstanding_share": np.full(n, 1e9),
            "turnover": np.full(n, 0.001),
        }
    )


class DriftSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.palace = PalaceStore(base / "palace.db")
        self.market = MarketStore(base / "market.db")
        rising = [10.0, 10.5, 11.0, 12.0, 13.0, 12.5, 11.5, 11.0, 10.8, 11.2] + [12.0] * 15
        self.market.upsert_quotes("600001", _quotes(rising))
        self.market.upsert_quotes("600002", _quotes([50.0] * 25))
        self.market.upsert_quotes("600003", _quotes([20.0, 19.0, 18.0, 17.0, 16.0] + [16.5] * 20))

    def tearDown(self) -> None:
        self.palace.close()
        self.market.close()
        self.temp.cleanup()

    def _candidate(self, code: str, day: str, slug: str = "demo-screen") -> None:
        self.palace.record_candidate(
            code=code,
            name=code,
            decision="精选",
            reason="r",
            occurred_on=day,
            pool_id=f"POOL-{day}",
            strategy_slug=slug,
            rule_version=slug,
        )

    def test_track_job_writes_plan_and_closes_expired(self) -> None:
        """track_candidate_outcomes 先把精选候选写入 position_tracking，T+5 走完后结算。"""
        self._candidate("600001", DAYS[0])
        first = track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        self.assertIn("tracking", first)
        # 首次运行：新计划开仓（当日还不能结算，等下次盘后）
        self.assertEqual(first["tracking"]["opened"], 1)
        self.assertEqual(first["tracking"]["closed"], 0)
        row = self.palace.find_tracking(
            strategy_tag="demo-screen",
            pool_id="POOL-2026-03-02",
            code="600001",
            signal_date="2026-03-02",
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["hold_days"], 5)
        self.assertIsNotNone(row["entry_price"])

        # 第二次盘后：T+5 已走完 → 结算为 expired
        again = track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        self.assertEqual(again["tracking"]["opened"], 0)
        self.assertEqual(again["tracking"]["closed"], 1)
        row = self.palace.find_tracking(
            strategy_tag="demo-screen",
            pool_id="POOL-2026-03-02",
            code="600001",
            signal_date="2026-03-02",
        )
        assert row is not None
        self.assertEqual(row["status"], "expired")
        self.assertIsNotNone(row["exit_price"])
        self.assertIsNotNone(row["actual_return"])

        # 幂等：再跑不应重复开仓
        third = track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        self.assertEqual(third["tracking"]["opened"], 0)

    def test_plan_followed_when_trade_matches_plan(self) -> None:
        """按计划买入并持有到期 → plan_followed，偏离接近 0。"""
        self._candidate("600001", DAYS[0])
        track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0, occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=1000, price=11.0, occurred_on=DAYS[5])
        report = compute_drift(self.palace, "demo-screen")
        self.assertEqual(report.total, 1)
        self.assertEqual(report.by_category.get("plan_followed"), 1)
        self.assertIsNotNone(report.avg_drift)
        self.assertEqual(report.worst_cases[0]["category"], "plan_followed")

    def test_early_exit_classified(self) -> None:
        """提前卖出（早于 exit_by_date）→ early_exit，且不再被误标 plan_followed。"""
        self._candidate("600001", DAYS[0])
        track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        # T+1 就卖：远早于 T+5 到期日
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0, occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=1000, price=9.8, occurred_on=DAYS[1])
        report = compute_drift(self.palace, "demo-screen")
        self.assertEqual(report.by_category.get("early_exit"), 1)
        self.assertEqual(report.by_category.get("plan_followed"), 0)

    def test_no_trade_and_late_entry(self) -> None:
        """无真实买入 → no_trade；晚于计划日买入 → late_entry。"""
        self._candidate("600002", DAYS[0])
        self._candidate("600003", DAYS[2])
        track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        track_candidate_outcomes(self.palace, self.market, max_age_trading_days=30)
        # 600003 在计划日次日才买入（600002 全程无成交）
        self.palace.record_trade(action="BUY", code="600003", shares=1000, price=19.0, occurred_on=DAYS[3])
        report = compute_drift(self.palace, "demo-screen")
        self.assertEqual(report.total, 2)
        self.assertEqual(report.by_category.get("no_trade"), 1)
        self.assertEqual(report.by_category.get("late_entry"), 1)

    def test_sync_skips_unselected(self) -> None:
        """未精选候选不写计划（opened 保持 0，且无 tracking 行）。"""
        self.palace.record_candidate(
            code="600002", name="600002", decision="落选", reason="r",
            occurred_on=DAYS[0], strategy_slug="demo-screen",
        )
        plan = sync_position_tracking(
            self.palace,
            evaluate_candidates(self.palace, self.market),
            self.market.trading_days(),
        )
        self.assertEqual(plan["opened"], 0)
        rows = self.palace.conn.execute("SELECT * FROM position_tracking").fetchall()
        self.assertEqual(len(rows), 0)


if __name__ == "__main__":
    unittest.main()