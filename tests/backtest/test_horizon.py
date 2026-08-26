"""Horizon T+N 口径单测。"""
from __future__ import annotations

import unittest

import pandas as pd

from src.backtest.application.horizon import (
    mark_day_offset,
    run_horizon_backtest,
)
from src.backtest.application.runner import MAX_HORIZON_SPAN_DAYS, _validate_horizon_range
from src.strategy.domain.base import StrategyError

DATES = [f"2026-03-{day:02d}" for day in range(2, 22)]
CODES = ["600001", "600002"]


def _panels() -> dict[str, pd.DataFrame]:
    close = pd.DataFrame({code: [10.0] * len(DATES) for code in CODES}, index=DATES)
    # D=index5 close 保持 10；标记日抬高 high 便于验算
    high = close * 1.0
    low = close * 0.98
    open_ = close.copy()
    volume = pd.DataFrame(1_000_000.0, index=DATES, columns=CODES)
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _signal_on(position: int, code: str = "600001") -> pd.DataFrame:
    signals = pd.DataFrame(False, index=DATES, columns=CODES)
    signals.iloc[position, signals.columns.get_loc(code)] = True
    return signals


class HorizonMarkOffsetTests(unittest.TestCase):
    def test_close_t1_is_next_day(self) -> None:
        self.assertEqual(mark_day_offset("close", 1), 1)

    def test_next_open_t1_is_day_after_entry(self) -> None:
        self.assertEqual(mark_day_offset("next_open", 1), 2)

    def test_next_dip_t1_is_day_after_entry(self) -> None:
        self.assertEqual(mark_day_offset("next_dip", 1), 2)


class HorizonReturnTests(unittest.TestCase):
    def test_close_entry_t1_uses_next_day_high_over_signal_close(self) -> None:
        """尾盘买、次日卖：high(D+1)/close(D)-1。"""
        panels = _panels()
        d = 5
        panels["close"].iloc[d, 0] = 10.0
        panels["high"].iloc[d + 1, 0] = 11.0
        result = run_horizon_backtest(
            _signal_on(d), panels, entry_timing="close", horizons=(1,), strategy_slug="t"
        )
        self.assertEqual(result.horizons["t1"]["n"], 1)
        self.assertAlmostEqual(result.horizons["t1"]["avg"], 10.0)
        self.assertEqual(result.events[0].mark_date, DATES[d + 1])

    def test_next_open_t1_uses_d_plus_2_high(self) -> None:
        """次日买、再持 1 日卖：high(D+2)/close(D)-1。"""
        panels = _panels()
        d = 5
        panels["close"].iloc[d, 0] = 10.0
        panels["high"].iloc[d + 2, 0] = 12.0
        result = run_horizon_backtest(
            _signal_on(d), panels, entry_timing="next_open", horizons=(1,), strategy_slug="t"
        )
        self.assertEqual(result.horizons["t1"]["n"], 1)
        self.assertAlmostEqual(result.horizons["t1"]["avg"], 20.0)
        self.assertEqual(result.events[0].entry_date, DATES[d + 1])
        self.assertEqual(result.events[0].mark_date, DATES[d + 2])

    def test_next_dip_excludes_unfilled_signal(self) -> None:
        panels = _panels()
        d = 5
        target = panels["close"] * 0.97
        result = run_horizon_backtest(
            _signal_on(d),
            panels,
            entry_timing="next_dip",
            entry_price_panel=target,
            horizons=(1,),
            strategy_slug="t",
        )
        self.assertIsNone(result.horizons["t1"])
        self.assertEqual(result.skipped["次日低吸未触价"], 1)

    def test_aggregate_best_worst_win_rate(self) -> None:
        panels = _panels()
        signals = pd.DataFrame(False, index=DATES, columns=CODES)
        signals.iloc[3, 0] = True
        signals.iloc[4, 0] = True
        panels["close"].iloc[3, 0] = 10.0
        panels["close"].iloc[4, 0] = 10.0
        panels["high"].iloc[4, 0] = 11.0  # +10%
        panels["high"].iloc[5, 0] = 9.0  # -10%
        result = run_horizon_backtest(
            signals, panels, entry_timing="close", horizons=(1,), strategy_slug="t"
        )
        stats = result.horizons["t1"]
        self.assertEqual(stats["n"], 2)
        self.assertAlmostEqual(stats["best"], 10.0)
        self.assertAlmostEqual(stats["worst"], -10.0)
        self.assertAlmostEqual(stats["win_rate"], 50.0)
        self.assertEqual(stats["best_event"]["code"], "600001")
        self.assertEqual(stats["best_event"]["signal_date"], DATES[3])
        self.assertEqual(stats["best_event"]["mark_date"], DATES[4])
        self.assertEqual(stats["worst_event"]["signal_date"], DATES[4])
        self.assertEqual(stats["worst_event"]["mark_date"], DATES[5])
        self.assertIn("median", stats)
        self.assertIn("close_avg", stats)
        self.assertEqual(stats["mark_basis"], "high")
        self.assertEqual(stats["sample_confidence"], "low")
        self.assertTrue(stats["by_month"])

    def test_missing_mark_day_skipped(self) -> None:
        panels = _panels()
        last = len(DATES) - 1
        result = run_horizon_backtest(
            _signal_on(last), panels, entry_timing="close", horizons=(1, 3), strategy_slug="t"
        )
        self.assertIsNone(result.horizons["t1"])
        self.assertIn("T+1标记日超出数据范围", result.skipped)


class HorizonRangeTests(unittest.TestCase):
    def test_span_over_six_months_rejected(self) -> None:
        with self.assertRaises(StrategyError):
            _validate_horizon_range("2026-01-01", "2026-08-01")

    def test_span_within_limit_ok(self) -> None:
        _validate_horizon_range("2026-01-01", "2026-07-06")
        self.assertEqual(MAX_HORIZON_SPAN_DAYS, 186)


if __name__ == "__main__":
    unittest.main()
