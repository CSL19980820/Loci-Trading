from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.market.infrastructure.store import MarketStore
from src.ledger import PalaceStore
from src.review import (
    evaluate_candidates,
    evaluate_plans,
    summarize_candidates,
)

DAYS = [f"2026-03-{day:02d}" for day in range(2, 27)]


def _quotes(closes: list[float], *, spread: float = 0.02) -> pd.DataFrame:
    """给定收盘价序列造一份日线。high/low 按固定比例展开，便于精确断言。"""
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


class ReviewFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.palace = PalaceStore(base / "palace.db")
        self.market = MarketStore(base / "market.db")

    def tearDown(self) -> None:
        self.palace.close()
        self.market.close()
        self.temp.cleanup()

    def _seed_market(self) -> None:
        # 一路上涨后回落：候选 T+N 与预案触发都需要窗口内有明显的高低点。
        rising = [10.0, 10.5, 11.0, 12.0, 13.0, 12.5, 11.5, 11.0, 10.8, 11.2] + [12.0] * 15
        falling = [20.0, 19.0, 18.0, 17.0, 16.5, 16.0, 15.5, 15.0, 15.2, 15.1] + [15.0] * 15
        flat = [50.0] * 25
        self.market.upsert_quotes("600001", _quotes(rising))
        self.market.upsert_quotes("600002", _quotes(falling))
        self.market.upsert_quotes("000300", _quotes(flat))


class CandidateOutcomeTests(ReviewFixture):
    def test_evaluates_rejected_candidates_too(self) -> None:
        """只统计买过的票是幸存者偏差。被否决的更能说明规则有没有问题。"""
        self._seed_market()
        self.palace.record_candidate(code="600001", name="甲", decision="剔除",
                                     reason="量能不足", occurred_on=DAYS[0], score=45)
        self.palace.record_candidate(code="600002", name="乙", decision="买入",
                                     reason="形态好", occurred_on=DAYS[0], score=88)

        outcomes = evaluate_candidates(self.palace, self.market)
        by_code = {o.code: o for o in outcomes}
        self.assertFalse(by_code["600001"].selected)
        self.assertTrue(by_code["600002"].selected)
        # 600001 从 10 涨到 13 后回落到 11.5（T+5 位置）
        self.assertGreater(by_code["600001"].returns[5], 0)
        # 600002 一路下跌
        self.assertLess(by_code["600002"].returns[5], 0)

    def test_surfaces_missed_winners(self) -> None:
        """当初否决、事后大涨——改进规则最直接的线索。"""
        self._seed_market()
        self.palace.record_candidate(code="600001", name="甲", decision="剔除",
                                     reason="不看好", occurred_on=DAYS[0])
        summary = summarize_candidates(evaluate_candidates(self.palace, self.market))
        self.assertTrue(summary["missed_winners"])
        self.assertEqual(summary["missed_winners"][0]["code"], "600001")

    def test_uses_the_trading_calendar_not_calendar_days(self) -> None:
        """T+N 必须走交易日历。按自然日会跨过周末，算出来的根本不是第 N 个交易日。"""
        self._seed_market()
        self.palace.record_candidate(code="600001", name="甲", decision="观察",
                                     reason="跟踪", occurred_on=DAYS[0])
        outcome = evaluate_candidates(self.palace, self.market)[0]
        calendar = self.market.trading_days()
        expected_day = calendar[calendar.index(DAYS[0]) + 5]
        series = self.market.history("600001", start=expected_day, end=expected_day)
        expected = (float(series.iloc[0]["close"]) / outcome.base_close - 1) * 100
        self.assertAlmostEqual(outcome.returns[5], expected, places=3)

    def test_missing_quotes_are_labelled_not_guessed(self) -> None:
        self.palace.record_candidate(code="600009", name="丙", decision="观察",
                                     reason="无行情", occurred_on=DAYS[0])
        outcome = evaluate_candidates(self.palace, self.market)[0]
        self.assertIsNone(outcome.base_close)
        self.assertIn("未取得真实", outcome.note)

    def test_score_buckets_expose_a_non_monotonic_scoring_model(self) -> None:
        """高分票如果并不比低分票赚得多，这套打分就是在做无用功。"""
        self._seed_market()
        for index in range(10):
            code = "600001" if index % 2 else "600002"
            self.palace.record_candidate(
                code=code, name="x", decision="观察", reason="r",
                occurred_on=DAYS[0], pool_id=f"pool-{index}",
                score=95 if code == "600002" else 55,
            )
        summary = summarize_candidates(evaluate_candidates(self.palace, self.market))
        buckets = {b["range"]: b for b in summary["score_buckets"]}
        low = buckets["0-59"]["avg_t20"]
        high = buckets["80-100"]["avg_t20"]
        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        # 本样本刻意构造成"低分票反而更赚"，分箱应如实反映
        self.assertGreater(low, high)


class PlanOutcomeTests(ReviewFixture):
    def test_evaluates_plans_with_one_market_panel_load(self) -> None:
        """多个预案不应为每一只标的重复发起日线查询。"""
        self._seed_market()
        self.palace.record_plan(
            code="600001", title="上涨预案", scenario="跟随",
            occurred_on=DAYS[0], stop_price=1.0, target_price=12.5,
        )
        self.palace.record_plan(
            code="600002", title="下跌预案", scenario="防守",
            occurred_on=DAYS[0], stop_price=19.0, target_price=99.0,
        )

        with (
            patch.object(self.market, "history", wraps=self.market.history) as history,
            patch.object(self.market, "load_panel", wraps=self.market.load_panel) as load_panel,
        ):
            results = evaluate_plans(self.palace, self.market)

        self.assertEqual(len(results), 2)
        self.assertEqual(history.call_count, 0)
        self.assertEqual(load_panel.call_count, 1)
        by_code = {row["code"]: row for row in results}
        # 各预案必须用自身止盈/止损，不能串用循环末项价位
        self.assertEqual(by_code["600001"]["status_final"], "target_hit")
        self.assertIsNotNone(by_code["600001"]["target_hit_on"])
        self.assertEqual(by_code["600002"]["status_final"], "stop_hit")
        self.assertIsNotNone(by_code["600002"]["stop_hit_on"])

    def test_detects_stop_and_target_hits(self) -> None:
        self._seed_market()
        self.palace.record_plan(code="600001", title="突破跟随", scenario="站上均线",
                                occurred_on=DAYS[0], stop_price=9.0, target_price=12.5)
        result = evaluate_plans(self.palace, self.market)[0]
        self.assertIsNotNone(result["target_hit_on"], "价格摸到 13.0，止盈应被触发")
        self.assertEqual(result["status_final"], "target_hit")

    def test_untriggered_plan_stays_observing(self) -> None:
        self._seed_market()
        self.palace.record_plan(code="600001", title="远目标", scenario="等待",
                                occurred_on=DAYS[0], stop_price=1.0, target_price=999.0)
        self.assertEqual(evaluate_plans(self.palace, self.market)[0]["status_final"], "observing")

    def test_plan_without_quotes_is_labelled(self) -> None:
        self.palace.record_plan(code="600009", title="无行情", scenario="x",
                                occurred_on=DAYS[0], stop_price=1.0)
        self.assertEqual(evaluate_plans(self.palace, self.market)[0]["status_final"], "no_data")

    def test_plan_does_not_trigger_on_signal_day_intraday(self) -> None:
        """盘后预案不吃当天盘中价：次日才进入观察，当天 low 破止损不算触发。"""
        self._seed_market()
        # DAYS[0] low = 9.8 < 10.0：若把当天计入，会误判止损触发
        self.palace.record_plan(code="600001", title="次日观察", scenario="盘后制定",
                                occurred_on=DAYS[0], stop_price=10.0, target_price=99.0)
        result = evaluate_plans(self.palace, self.market)[0]
        self.assertIsNone(result["stop_hit_on"])
        self.assertEqual(result["status_final"], "observing")

    def test_plan_window_has_an_upper_bound(self) -> None:
        """超过 60 个交易日的长尾预案不再无限扫描，标记 window_expired。"""
        long_days = [f"2026-01-{day:02d}" for day in range(1, 32)] + [f"2026-02-{day:02d}" for day in range(1, 29)] + [f"2026-03-{day:02d}" for day in range(1, 32)]
        close = np.full(len(long_days), 50.0)
        long_df = pd.DataFrame({
            "date": long_days, "open": close, "high": close * 1.02, "low": close * 0.98,
            "close": close, "volume": np.full(len(long_days), 1_000_000.0),
            "amount": close * 1_000_000.0, "outstanding_share": np.full(len(long_days), 1e9),
            "turnover": np.full(len(long_days), 0.001),
        })
        self.market.upsert_quotes("600001", long_df)
        # 目标价极高永不可能触发；日历有 91 天 > 60 上限 → 应截断并标记
        self.palace.record_plan(code="600001", title="长尾预案", scenario="等待",
                                occurred_on=long_days[0], stop_price=1.0, target_price=99999.0)
        result = evaluate_plans(self.palace, self.market)[0]
        self.assertEqual(result["status_final"], "expired")
        self.assertTrue(result["window_expired"])


if __name__ == "__main__":
    unittest.main()
