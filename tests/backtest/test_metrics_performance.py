"""绩效指标与诊断资金曲线单测。"""
from __future__ import annotations

import unittest

from src.backtest.application.metrics import compute_metrics
from src.backtest.application.performance import compute_trade_performance
from src.backtest.domain.models import Trade


def _trade(
    net: float,
    *,
    exit_date: str = "2026-03-05",
    entry_date: str = "2026-03-02",
    code: str = "600001",
    exit_reason: str = "hold_expired",
) -> Trade:
    return Trade(
        code=code,
        signal_date=entry_date,
        entry_date=entry_date,
        entry_price=10.0,
        exit_date=exit_date,
        exit_price=10.0,
        hold_days=3,
        gross_return_pct=net,
        net_return_pct=net,
        mae_pct=-3.0,
        mfe_pct=5.0,
        exit_reason=exit_reason,
    )


class EnrichedMetricsTests(unittest.TestCase):
    def test_streaks_and_percentiles(self) -> None:
        trades = [
            _trade(2.0),
            _trade(1.0),
            _trade(-1.0),
            _trade(-2.0),
            _trade(-3.0),
            _trade(4.0),
        ]
        metrics = compute_metrics(trades)
        self.assertEqual(metrics["max_consecutive_wins"], 2)
        self.assertEqual(metrics["max_consecutive_losses"], 3)
        self.assertIn("p50", metrics["percentiles"])
        self.assertEqual(metrics["sample_confidence"], "low")
        self.assertTrue(metrics["by_month"])
        self.assertTrue(metrics["return_distribution"])

    def test_payoff_ratio(self) -> None:
        metrics = compute_metrics([_trade(4.0), _trade(-2.0)])
        self.assertAlmostEqual(metrics["payoff_ratio"], 2.0)


class PerformanceCurveTests(unittest.TestCase):
    def test_sequential_compounding_and_drawdown(self) -> None:
        trades = [
            _trade(10.0, exit_date="2026-01-10", entry_date="2026-01-02"),
            _trade(-50.0, exit_date="2026-02-10", entry_date="2026-02-02"),
            _trade(20.0, exit_date="2026-03-10", entry_date="2026-03-02"),
        ]
        perf = compute_trade_performance(trades)
        self.assertTrue(perf["available"])
        self.assertEqual(perf["assumption"]["model"], "trade_sequence_compounding")
        # 1.0 * 1.1 * 0.5 * 1.2 = 0.66 → -34%
        self.assertAlmostEqual(perf["cumulative_return_pct"], -34.0, places=2)
        self.assertLess(perf["max_drawdown_pct"], 0)
        self.assertGreaterEqual(len(perf["equity_curve"]), 4)
        self.assertIsNotNone(perf["sharpe"] is not None or perf["volatility_pct"] >= 0)

    def test_data_end_excluded(self) -> None:
        perf = compute_trade_performance(
            [_trade(5.0), _trade(-99.0, exit_reason="data_end")]
        )
        self.assertEqual(perf["trades"], 1)
        self.assertAlmostEqual(perf["cumulative_return_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
