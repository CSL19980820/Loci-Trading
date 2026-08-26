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


class _DipPanelStore:
    """信号面板 qfq（close=10）、执行面板不复权（close=20），入场日探底到 19。"""

    def __init__(self, days: list[str]) -> None:
        self.days = days

    def trading_days(self, *, end: str | None = None) -> list[str]:
        return [day for day in self.days if end is None or day <= end]

    def data_snapshot(self) -> dict[str, object]:
        return {"revision": "dip-test"}

    def load_panel(self, **kwargs: object) -> dict[str, pd.DataFrame]:
        raw = str(kwargs["adjust"]) == "none"
        index = pd.Index(self.days, name="trade_date")
        close = pd.DataFrame({"600001": [20.0 if raw else 10.0] * len(self.days)}, index=index)
        low = close * 0.999
        low.iloc[3, 0] = 19.0 if raw else 9.5
        return {
            "open": close.copy(),
            "high": close * 1.001,
            "low": low,
            "close": close.copy(),
            "volume": pd.DataFrame(1.0, index=index, columns=["600001"]),
        }


class _DipEngine(_ExecutionPriceEngine):
    slug = "dip-execution-test"
    entry_timing = "next_dip"

    def default_params(self) -> dict[str, object]:
        return {"dip_pct": 0.02}


class RunnerDipExecutionPanelTests(unittest.TestCase):
    def test_dip_target_price_lives_in_execution_price_space(self) -> None:
        """预挂价用 qfq 收盘算、却拿不复权最低价去比，触价判断会整体错位。"""
        days = [f"2026-01-{day:02d}" for day in range(1, 6)]
        store = _DipPanelStore(days)
        resolved = ResolvedUniverse(
            codes=["600001"], meta={"600001": {"name": "测试"}}, spec={"preset": "test"}
        )
        with patch(
            "src.backtest.application.runner.resolve_universe", return_value=resolved
        ):
            result = backtest_strategy(
                store,
                _DipEngine(),
                start=days[2],
                end=days[2],
                config=BacktestConfig(
                    hold_days=1,
                    stop_loss_pct=None,
                    take_profit_pct=None,
                    commission_bps=0.0,
                    stamp_duty_bps=0.0,
                    slippage_bps=0.0,
                    benchmark=None,
                ),
            )

        # 目标价 = 不复权收盘 20 × 0.98 = 19.6；入场日最低 19.0 触价。
        # 用 qfq 的 10 × 0.98 = 9.8 去比 19.0，会记成"次日低吸未触价"。
        self.assertEqual(result.skipped.get("次日低吸未触价"), None)
        self.assertEqual(len(result.trades), 1)
        self.assertAlmostEqual(result.trades[0].entry_price, 19.6, places=4)


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
