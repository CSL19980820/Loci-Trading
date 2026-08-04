from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from src.backtest import BacktestConfig, backtest_strategy
from src.market.domain.universe import ResolvedUniverse
from src.strategy.domain.base import SignalResult


class _ExecutionPanelStore:
    def __init__(self, days: list[str]) -> None:
        self.days = days
        self.adjusts: list[str] = []

    def trading_days(self, *, end: str | None = None) -> list[str]:
        return [day for day in self.days if end is None or day <= end]

    def data_snapshot(self) -> dict[str, object]:
        return {"revision": "execution-test"}

    def load_panel(self, **kwargs: object) -> dict[str, pd.DataFrame]:
        adjust = str(kwargs["adjust"])
        self.adjusts.append(adjust)
        index = pd.Index(self.days, name="trade_date")
        close = pd.Series(10.0 if adjust != "none" else 20.0, index=index)
        close.iloc[3] = 10.1 if adjust != "none" else 20.6
        frame = pd.DataFrame({"600001": close})
        return {
            "open": frame.copy(),
            "high": frame * 1.01,
            "low": frame * 0.99,
            "close": frame.copy(),
            "volume": pd.DataFrame(1.0, index=index, columns=["600001"]),
        }


class _ExecutionPriceEngine:
    slug = "execution-price-test"
    name = "成交价测试"
    description = "测试信号与执行价格分离"
    entry_timing = "close"
    execution_adjust = "none"
    strategy_revision = "test"

    def default_params(self) -> dict[str, object]:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 1

    def compute(
        self,
        panels: dict[str, pd.DataFrame],
        params: dict[str, object] | None = None,
    ) -> SignalResult:
        signals = pd.DataFrame(False, index=panels["close"].index, columns=["600001"])
        signals.iloc[2, 0] = True
        return SignalResult(signals=signals, factors={"信号": signals})


class RunnerExecutionPriceTests(unittest.TestCase):
    def test_tail_strategy_uses_raw_execution_panel(self) -> None:
        days = [f"2026-01-{day:02d}" for day in range(1, 6)]
        store = _ExecutionPanelStore(days)
        resolved = ResolvedUniverse(
            codes=["600001"], meta={"600001": {"name": "测试"}}, spec={"preset": "test"}
        )
        with patch(
            "src.backtest.application.runner.resolve_universe", return_value=resolved
        ):
            result = backtest_strategy(
                store,
                _ExecutionPriceEngine(),
                start=days[2],
                end=days[2],
                config=BacktestConfig(
                    hold_days=1,
                    stop_loss_pct=None,
                    take_profit_pct=3.0,
                    commission_bps=0.0,
                    stamp_duty_bps=0.0,
                    slippage_bps=0.0,
                    benchmark=None,
                ),
            )

        self.assertIn("qfq", store.adjusts)
        self.assertIn("none", store.adjusts)
        self.assertEqual(result.trades[0].entry_price, 20.0)
        self.assertEqual(result.trades[0].exit_price, 20.6)
        self.assertEqual(result.config["data_snapshot"]["execution_adjust"], "none")


if __name__ == "__main__":
    unittest.main()
