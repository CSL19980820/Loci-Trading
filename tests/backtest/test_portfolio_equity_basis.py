"""组合层账本的资金不变式与权益口径披露。

针对 `docs/research/2026-08-mainstream-quant-benchmark.md` §1.7 记录的缺陷：
`equity = cash + Σ 入场名义额` 让未实现盈亏恒为 0，`max_drawdown_pct` 因此量的是
已实现盈亏回撤而非账户回撤，而当时没有任何字段说明这一点。
"""
from __future__ import annotations

import unittest

from src.backtest.application.engine import Trade
from src.backtest.application.research_portfolio import (
    PortfolioResearchConfig,
    analyze_portfolio,
)
from src.backtest.application.research_portfolio_marks import (
    EQUITY_BASIS,
    PortfolioInvariantError,
    assert_cash_conservation,
    drawdown_pct,
    mae_floor_value,
)

TRADING_WEEK = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]


def _trade(code, entry, exit_, net_pct, mae_pct=0.0, price=10.0):
    return Trade(
        code=code,
        signal_date=entry,
        entry_date=entry,
        entry_price=price,
        exit_date=exit_,
        exit_price=price * (1.0 + net_pct / 100.0),
        hold_days=1,
        gross_return_pct=net_pct,
        net_return_pct=net_pct,
        mae_pct=mae_pct,
        mfe_pct=abs(net_pct),
        exit_reason="hold_expired",
    )


class CashConservationTest(unittest.TestCase):
    def test_should_settle_every_position_back_into_cash(self):
        trades = [
            _trade("000001", "2026-01-05", "2026-01-07", 5.0),
            _trade("000002", "2026-01-06", "2026-01-08", -3.0),
            _trade("000003", "2026-01-09", "2026-01-12", 1.5),
        ]
        result = analyze_portfolio(
            trades,
            config=PortfolioResearchConfig(initial_capital=200_000.0, max_positions=2),
            strategy_slug="test",
        )
        realized = sum(item.pnl for item in result.allocations)
        expected = float(result.metrics["initial_capital"]) + realized
        self.assertAlmostEqual(float(result.metrics["final_equity"]), expected, places=4)

    def test_should_reject_a_ledger_that_loses_cash(self):
        with self.assertRaises(PortfolioInvariantError):
            assert_cash_conservation(
                initial_capital=200_000.0,
                final_equity=180_000.0,
                realized_pnl_total=0.0,
            )


class EquityBasisDisclosureTest(unittest.TestCase):
    """口径必须自报，否则读的人会把它当账户净值。"""

    def _metrics(self):
        trades = [_trade("000001", "2026-01-05", "2026-01-09", 2.0, mae_pct=-30.0)]
        result = analyze_portfolio(
            trades,
            config=PortfolioResearchConfig(initial_capital=100_000.0, max_positions=1),
            strategy_slug="test",
            trading_dates=TRADING_WEEK,
        )
        return result.to_dict()["metrics"]

    def test_should_declare_that_equity_is_not_marked_to_market(self):
        assumption = self._metrics()["assumption"]
        self.assertEqual(assumption["equity_basis"], EQUITY_BASIS)
        self.assertFalse(assumption["marks_to_market"])
        self.assertEqual(assumption["drawdown_basis"], "realized_only")

    def test_realized_drawdown_hides_the_intra_hold_loss(self):
        """锁住缺陷的形状：持仓中途 -30%，已实现口径看不见，MAE 上界看得见。"""
        metrics = self._metrics()
        realized = float(metrics["max_drawdown_pct"])
        bound = float(metrics["mae_bound_max_drawdown_pct"])
        self.assertEqual(realized, 0.0)
        self.assertLess(bound, -20.0)
        self.assertLess(bound, realized)


class MarksHelperTest(unittest.TestCase):
    def test_drawdown_counts_from_initial_capital_not_first_point(self):
        # 峰值若从首个观测起算，第一天就亏的曲线会被记成 0 回撤。
        self.assertAlmostEqual(drawdown_pct([90.0, 95.0], peak_floor=100.0), -10.0, places=6)

    def test_floor_ignores_non_negative_and_non_finite_mae(self):
        self.assertAlmostEqual(mae_floor_value(0.0, [(1000.0, 0.0)]), 1000.0, places=6)
        nan = float("nan")
        self.assertAlmostEqual(mae_floor_value(0.0, [(1000.0, nan)]), 1000.0, places=6)
        self.assertAlmostEqual(mae_floor_value(0.0, [(1000.0, -25.0)]), 750.0, places=6)

    def test_floor_never_goes_below_zero_for_a_position(self):
        self.assertAlmostEqual(mae_floor_value(0.0, [(1000.0, -250.0)]), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
