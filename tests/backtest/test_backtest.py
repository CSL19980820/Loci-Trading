from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, compute_metrics, run_backtest
from src.backtest.application.engine import Trade

DATES = [f"2026-03-{day:02d}" for day in range(2, 22)]
CODES = ["600001", "600002"]


def _flat_panels(
    *, close: dict[str, list[float]] | None = None, volume_zero_days: dict[str, list[int]] | None = None
) -> dict[str, pd.DataFrame]:
    """造一组可控的行情面板。默认每天平价，便于把某一天单独拨动来测规则。"""
    base = {code: [10.0] * len(DATES) for code in CODES}
    if close:
        for code, values in close.items():
            base[code] = values

    frames: dict[str, pd.DataFrame] = {}
    close_df = pd.DataFrame(base, index=DATES)
    frames["close"] = close_df
    frames["open"] = close_df.copy()
    frames["high"] = close_df * 1.02
    frames["low"] = close_df * 0.98
    volume = pd.DataFrame(1_000_000.0, index=DATES, columns=CODES)
    if volume_zero_days:
        for code, positions in volume_zero_days.items():
            for position in positions:
                volume.iloc[position, volume.columns.get_loc(code)] = 0.0
    frames["volume"] = volume
    return frames


def _signal_on(position: int, code: str = "600001") -> pd.DataFrame:
    signals = pd.DataFrame(False, index=DATES, columns=CODES)
    signals.iloc[position, signals.columns.get_loc(code)] = True
    return signals


class AShareRuleTests(unittest.TestCase):
    """A 股交易规则。少实现一条，回测收益就会系统性虚高。"""

    def test_t_plus_one_forbids_same_day_exit(self) -> None:
        """当日买入当日不可卖，持有期至少一个交易日。"""
        panels = _flat_panels()
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=0, stop_loss_pct=None, benchmark=None),
        )
        self.assertEqual(len(result.trades), 1)
        self.assertGreaterEqual(result.trades[0].hold_days, 1, "T+1 被违反：当日买当日卖")

    def test_one_word_limit_up_blocks_entry(self) -> None:
        """一字涨停当天挂单也买不到，必须跳过而不是假装成交。"""
        panels = _flat_panels()
        entry_row = 5
        for field in ("open", "high", "low", "close"):
            panels[field].iloc[entry_row, 0] = 11.0  # 全天同价 = 一字板
        result = run_backtest(
            _signal_on(entry_row), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        self.assertEqual(len(result.trades), 0)
        self.assertIn("入场日一字板买不进", result.skipped)

    def test_one_word_limit_up_entry_can_be_opted_in(self) -> None:
        panels = _flat_panels()
        entry_row = 5
        for field in ("open", "high", "low", "close"):
            panels[field].iloc[entry_row, 0] = 11.0
        result = run_backtest(
            _signal_on(entry_row), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None, allow_limit_up_entry=True),
        )
        self.assertEqual(len(result.trades), 1)

    def test_suspended_entry_day_is_skipped(self) -> None:
        """停牌日没有成交量，不可能成交。"""
        panels = _flat_panels(volume_zero_days={"600001": [5]})
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        self.assertEqual(len(result.trades), 0)
        self.assertIn("入场日停牌", result.skipped)

    def test_exit_is_deferred_when_the_planned_day_is_untradable(self) -> None:
        """计划退出日停牌，就得顺延到能成交的日子，不能假装卖掉了。"""
        panels = _flat_panels(volume_zero_days={"600001": [8, 9]})
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, stop_loss_pct=None, benchmark=None),
        )
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].exit_date, DATES[10], "停牌日应顺延而不是就地成交")


class EntryTimingTests(unittest.TestCase):
    def test_open_timing_enters_on_the_signal_day(self) -> None:
        panels = _flat_panels()
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        self.assertEqual(result.trades[0].signal_date, DATES[5])
        self.assertEqual(result.trades[0].entry_date, DATES[5])

    def test_next_open_timing_enters_the_following_day(self) -> None:
        panels = _flat_panels()
        result = run_backtest(
            _signal_on(5), panels, entry_timing="next_open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        self.assertEqual(result.trades[0].signal_date, DATES[5])
        self.assertEqual(result.trades[0].entry_date, DATES[6])

    def test_signal_at_the_very_end_has_no_entry_day(self) -> None:
        panels = _flat_panels()
        result = run_backtest(
            _signal_on(len(DATES) - 1), panels, entry_timing="next_open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        self.assertEqual(len(result.trades), 0)
        self.assertIn("入场日超出数据范围", result.skipped)


class ExitRuleTests(unittest.TestCase):
    def test_stop_loss_fires_and_is_labelled(self) -> None:
        prices = [10.0] * len(DATES)
        prices[6] = 9.0  # 入场次日跌 10%
        panels = _flat_panels(close={"600001": prices})
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=5, stop_loss_pct=-6.0, benchmark=None),
        )
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertLess(trade.net_return_pct, 0)

    def test_take_profit_fires_before_hold_expires(self) -> None:
        prices = [10.0] * len(DATES)
        prices[6] = 12.0
        panels = _flat_panels(close={"600001": prices})
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=5, stop_loss_pct=None, take_profit_pct=8.0, benchmark=None),
        )
        self.assertEqual(result.trades[0].exit_reason, "take_profit")

    def test_running_out_of_data_is_not_counted_as_a_normal_exit(self) -> None:
        """数据到头必须单独标记，混进"到期了结"会污染统计。"""
        panels = _flat_panels()
        result = run_backtest(
            _signal_on(len(DATES) - 2), panels, entry_timing="open",
            config=BacktestConfig(hold_days=10, stop_loss_pct=None, benchmark=None),
        )
        self.assertEqual(result.trades[0].exit_reason, "data_end")


class CostAndMetricTests(unittest.TestCase):
    def test_round_trip_cost_is_deducted(self) -> None:
        """成本对短持有期策略是生死线，必须真的扣掉。"""
        panels = _flat_panels()
        config = BacktestConfig(hold_days=3, stop_loss_pct=None, benchmark=None)
        result = run_backtest(_signal_on(5), panels, entry_timing="open", config=config)
        trade = result.trades[0]
        self.assertAlmostEqual(
            trade.net_return_pct, trade.gross_return_pct - config.round_trip_cost_pct(), places=6
        )
        # 万三佣金双边 + 千一印花税 + 5bps 滑点双边 = 26 bps = 0.26%
        self.assertAlmostEqual(config.round_trip_cost_pct(), 0.26, places=6)

    def test_mfe_and_mae_cover_the_whole_holding_window(self) -> None:
        prices = [10.0] * len(DATES)
        prices[6] = 13.0   # 期间冲高
        prices[7] = 8.0    # 期间挖坑
        panels = _flat_panels(close={"600001": prices})
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=4, stop_loss_pct=None, benchmark=None),
        )
        trade = result.trades[0]
        self.assertGreater(trade.mfe_pct, 25.0, "MFE 应覆盖持有期内的最高点")
        self.assertLess(trade.mae_pct, -18.0, "MAE 应覆盖持有期内的最低点")
        self.assertGreaterEqual(trade.mfe_pct, trade.net_return_pct)
        self.assertLessEqual(trade.mae_pct, trade.net_return_pct)

    def test_benchmark_alpha_is_return_minus_benchmark(self) -> None:
        panels = _flat_panels(close={"600001": [10.0 + i * 0.5 for i in range(len(DATES))]})
        benchmark = pd.Series(
            [100.0 + i for i in range(len(DATES))], index=DATES, dtype=float
        )
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, stop_loss_pct=None),
            benchmark_close=benchmark,
        )
        trade = result.trades[0]
        self.assertIsNotNone(trade.benchmark_return_pct)
        self.assertAlmostEqual(
            trade.alpha_pct, trade.net_return_pct - trade.benchmark_return_pct, places=4
        )

    def test_missing_benchmark_degrades_instead_of_failing(self) -> None:
        """忘了同步指数不该让整个回测报废。"""
        panels = _flat_panels()
        result = run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None), benchmark_close=None,
        )
        self.assertEqual(len(result.trades), 1)
        self.assertIsNone(result.trades[0].benchmark_return_pct)
        self.assertIsNone(result.trades[0].alpha_pct)


class MetricsTests(unittest.TestCase):
    @staticmethod
    def _trade(net: float, mfe: float = 5.0, mae: float = -3.0) -> Trade:
        return Trade(
            code="600001", signal_date="2026-03-02", entry_date="2026-03-02",
            entry_price=10.0, exit_date="2026-03-05", exit_price=10.0, hold_days=3,
            gross_return_pct=net, net_return_pct=net, mae_pct=mae, mfe_pct=mfe,
            exit_reason="hold_expired",
        )

    def test_empty_input(self) -> None:
        self.assertEqual(compute_metrics([]), {"trades": 0})

    def test_win_rate_and_profit_factor(self) -> None:
        trades = [self._trade(5.0), self._trade(3.0), self._trade(-2.0), self._trade(-2.0)]
        metrics = compute_metrics(trades)
        self.assertEqual(metrics["trades"], 4)
        self.assertAlmostEqual(metrics["win_rate"], 50.0)
        self.assertAlmostEqual(metrics["profit_factor"], 2.0)
        self.assertAlmostEqual(metrics["expectancy"], 1.0)

    def test_small_sample_gets_an_explicit_caution(self) -> None:
        """7 笔交易的均值不是结论。不加提示，人就会当成结论。"""
        metrics = compute_metrics([self._trade(1.0)] * 7)
        self.assertIn("caution", metrics)

    def test_large_sample_has_no_caution(self) -> None:
        metrics = compute_metrics([self._trade(1.0)] * 40)
        self.assertNotIn("caution", metrics)

    def test_all_winners_gives_infinite_profit_factor(self) -> None:
        metrics = compute_metrics([self._trade(2.0), self._trade(3.0)])
        self.assertEqual(metrics["profit_factor"], float("inf"))
        self.assertIsNone(metrics["avg_loss"])


class SeparationOfConcernsTests(unittest.TestCase):
    """回测器不得参与选股决策，否则"信号不看未来"的保证就形同虚设。"""

    def test_backtest_never_alters_the_signal_panel(self) -> None:
        panels = _flat_panels()
        signals = _signal_on(5)
        snapshot = signals.copy()
        run_backtest(
            signals, panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        pd.testing.assert_frame_equal(signals, snapshot)

    def test_backtest_never_alters_the_market_panels(self) -> None:
        panels = _flat_panels()
        snapshot = {field: panel.copy() for field, panel in panels.items()}
        run_backtest(
            _signal_on(5), panels, entry_timing="open",
            config=BacktestConfig(hold_days=3, benchmark=None),
        )
        for field, panel in panels.items():
            pd.testing.assert_frame_equal(panel, snapshot[field], obj=f"{field} 被回测改动了")


if __name__ == "__main__":
    unittest.main()
