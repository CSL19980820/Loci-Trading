from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.market.store import MarketStore
from src.palace import PalaceStore
from src.review import (
    attribute_round_trips,
    build_equity_curve,
    evaluate_candidates,
    evaluate_plans,
    positions_as_of,
    round_trips,
    summarize_candidates,
    summarize_round_trips,
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
        # 一路上涨后回落，便于让 MFE 明显高于最终收益。
        rising = [10.0, 10.5, 11.0, 12.0, 13.0, 12.5, 11.5, 11.0, 10.8, 11.2] + [12.0] * 15
        falling = [20.0, 19.0, 18.0, 17.0, 16.5, 16.0, 15.5, 15.0, 15.2, 15.1] + [15.0] * 15
        flat = [50.0] * 25
        self.market.upsert_quotes("600001", _quotes(rising))
        self.market.upsert_quotes("600002", _quotes(falling))
        self.market.upsert_quotes("000300", _quotes(flat))


class PositionReplayTests(ReviewFixture):
    def test_replays_holdings_at_a_past_date(self) -> None:
        """核心能力：那天收盘时到底持有什么。此前只能取"现在"。"""
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0], name="甲")
        self.palace.record_trade(action="BUY", code="600002", shares=500, price=20.0,
                                 occurred_on=DAYS[3], name="乙")
        self.palace.record_trade(action="SELL", code="600001", shares=1000, price=13.0,
                                 occurred_on=DAYS[5])

        self.assertEqual([p.code for p in positions_as_of(self.palace, DAYS[0])], ["600001"])
        self.assertEqual(
            sorted(p.code for p in positions_as_of(self.palace, DAYS[3])), ["600001", "600002"]
        )
        self.assertEqual([p.code for p in positions_as_of(self.palace, DAYS[6])], ["600002"])
        self.assertEqual([p.code for p in positions_as_of(self.palace)], ["600002"])

    def test_before_any_event_there_is_no_position(self) -> None:
        self.palace.record_trade(action="BUY", code="600001", shares=100, price=10.0,
                                 occurred_on=DAYS[5])
        self.assertEqual(positions_as_of(self.palace, DAYS[1]), [])

    def test_same_day_multiple_events_use_the_final_state(self) -> None:
        """同一天多笔时必须取当日最终状态，不能停在中间某一笔。"""
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0])
        self.palace.record_trade(action="BUY", code="600001", shares=500, price=11.0,
                                 occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=200, price=12.0,
                                 occurred_on=DAYS[0])
        held = positions_as_of(self.palace, DAYS[0])
        self.assertEqual(held[0].shares, 1300)


class RoundTripTests(ReviewFixture):
    def test_splits_events_into_holding_cycles(self) -> None:
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=1000, price=13.0,
                                 occurred_on=DAYS[4])
        self.palace.record_trade(action="BUY", code="600001", shares=500, price=11.0,
                                 occurred_on=DAYS[8])

        trips = round_trips(self.palace)
        self.assertEqual(len(trips), 2)
        closed, still_open = trips[0], trips[1]
        self.assertEqual(closed.opened_on, DAYS[0])
        self.assertEqual(closed.closed_on, DAYS[4])
        self.assertFalse(closed.is_open)
        self.assertAlmostEqual(closed.realized_pnl, 3000.0)
        self.assertAlmostEqual(closed.return_pct, 30.0, places=4)
        self.assertTrue(still_open.is_open)
        self.assertIsNone(still_open.return_pct, "浮盈不是收益，未清仓不该有收益率")

    def test_partial_sells_stay_in_the_same_cycle(self) -> None:
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=400, price=12.0,
                                 occurred_on=DAYS[2])
        self.palace.record_trade(action="SELL", code="600001", shares=600, price=13.0,
                                 occurred_on=DAYS[5])
        trips = round_trips(self.palace)
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0].peak_shares, 1000)
        self.assertEqual(len(trips[0].event_ids), 3)

    def test_open_positions_are_still_reported(self) -> None:
        """扛着的仓位也要出现在复盘里，否则最该反省的部分正好缺席。"""
        self.palace.record_trade(action="BUY", code="600002", shares=500, price=20.0,
                                 occurred_on=DAYS[0])
        trips = round_trips(self.palace)
        self.assertEqual(len(trips), 1)
        self.assertTrue(trips[0].is_open)


class AttributionTests(ReviewFixture):
    def test_mae_and_mfe_cover_the_whole_holding_window(self) -> None:
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=1000, price=11.0,
                                 occurred_on=DAYS[7])

        trip = attribute_round_trips(round_trips(self.palace), self.market)[0]
        # 区间最高 13.0（含 2% 上影 = 13.26），相对成本 10.0
        self.assertGreater(trip.mfe_pct, 30.0)
        self.assertLess(trip.mae_pct, 0.0)
        self.assertEqual(trip.hold_days, 7)

    def test_detects_profit_give_back(self) -> None:
        """MFE 远高于最终收益 → 问题在退出纪律而不是选股。

        这正是此前手工回测发现的病，现在能自动指出来。
        """
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0])
        self.palace.record_trade(action="SELL", code="600001", shares=1000, price=10.5,
                                 occurred_on=DAYS[8])
        summary = summarize_round_trips(
            attribute_round_trips(round_trips(self.palace), self.market)
        )
        self.assertGreater(summary["profit_give_back_pct"], 3)
        self.assertIn("退出纪律", summary["hint"])

    def test_summary_groups_by_code_and_month(self) -> None:
        self._seed_market()
        for code, exit_price in (("600001", 13.0), ("600002", 15.0)):
            entry = 10.0 if code == "600001" else 20.0
            self.palace.record_trade(action="BUY", code=code, shares=100, price=entry,
                                     occurred_on=DAYS[0])
            self.palace.record_trade(action="SELL", code=code, shares=100, price=exit_price,
                                     occurred_on=DAYS[6])
        summary = summarize_round_trips(
            attribute_round_trips(round_trips(self.palace), self.market)
        )
        self.assertEqual(summary["closed"], 2)
        self.assertEqual(summary["win_rate"], 50.0)
        self.assertEqual(set(summary["by_code"]), {"600001", "600002"})
        self.assertEqual(list(summary["by_month"]), ["2026-03"])
        # 亏损的排在前面，方便先看最该反省的
        self.assertEqual(next(iter(summary["by_code"])), "600002")

    def test_missing_quotes_do_not_break_attribution(self) -> None:
        """行情缺失应留空而不是崩，也不能编一个数字。"""
        self.palace.record_trade(action="BUY", code="600009", shares=100, price=10.0,
                                 occurred_on=DAYS[0])
        trip = attribute_round_trips(round_trips(self.palace), self.market)[0]
        self.assertIsNone(trip.mae_pct)
        self.assertIsNone(trip.mfe_pct)


class EquityCurveTests(ReviewFixture):
    def test_curve_reflects_floating_loss_not_just_realized(self) -> None:
        """与旧曲线的根本区别：持仓期间的浮亏必须体现在净值里。

        旧的 equity_curve 是已实现盈亏累加，扛着 −30% 的票和空仓长得一样，
        最大回撤根本无从谈起。
        """
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600002", shares=1000, price=20.0,
                                 occurred_on=DAYS[0], name="乙")
        curve = build_equity_curve(self.palace, self.market, benchmarks=())

        self.assertGreater(len(curve.points), 5)
        # 600002 从 20 跌到 15，持仓市值必须随之下滑
        self.assertLess(curve.points[-1].holding_value, curve.points[0].holding_value)
        self.assertLess(curve.points[-1].floating_pnl, 0)
        self.assertLess(curve.metrics["max_drawdown_pct"], 0)

    def test_reports_estimated_confidence_without_a_snapshot(self) -> None:
        """没有资产快照就不硬凑总资产数字，如实标注 estimated。"""
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600001", shares=100, price=10.0,
                                 occurred_on=DAYS[0])
        curve = build_equity_curve(self.palace, self.market, benchmarks=())
        self.assertEqual(curve.confidence, "estimated")
        self.assertIn("快照", curve.note)

    def test_snapshot_anchors_the_cash_level(self) -> None:
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600001", shares=1000, price=10.0,
                                 occurred_on=DAYS[0])
        self.palace.record_snapshot(total_assets=50000.0, occurred_on=DAYS[5])
        curve = build_equity_curve(self.palace, self.market, benchmarks=())
        self.assertEqual(curve.confidence, "anchored")
        anchored = next(p for p in curve.points if p.trade_date == DAYS[5])
        self.assertAlmostEqual(anchored.total_equity, 50000.0, places=2)

    def test_benchmark_is_normalised_to_the_same_start(self) -> None:
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600001", shares=100, price=10.0,
                                 occurred_on=DAYS[0])
        curve = build_equity_curve(self.palace, self.market, benchmarks=("000300",))
        self.assertEqual(curve.points[0].benchmarks["000300"], 0.0)
        self.assertIn("benchmark_000300_pct", curve.metrics)

    def test_empty_ledger_is_reported_not_crashed(self) -> None:
        curve = build_equity_curve(self.palace, self.market)
        self.assertEqual(curve.points, [])
        self.assertIn("成交", curve.note)

    def test_short_window_gets_a_caution(self) -> None:
        """几天的数据外推出来的年化毫无意义，必须明说。"""
        self._seed_market()
        self.palace.record_trade(action="BUY", code="600001", shares=100, price=10.0,
                                 occurred_on=DAYS[0])
        curve = build_equity_curve(self.palace, self.market, benchmarks=())
        self.assertIn("caution", curve.metrics)


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


if __name__ == "__main__":
    unittest.main()
