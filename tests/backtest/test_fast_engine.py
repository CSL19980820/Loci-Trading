"""fast_engine：无止损 hold 场景与经典引擎对照；有细规则止损时回退经典。

允许差异（文档化）：
- fast 路径 ``result.config['engine']`` 可为 ``numpy_fast`` / ``vectorbt_aligned``
- 数值比较用 AlmostEqual（成交价经 round 到 4 位）
- 有 ``stop_loss_pct`` / ``take_profit_pct`` 时必须与直接 ``run_backtest`` 完全一致
  （回退经典，不做近似加速）
"""
from __future__ import annotations

import os
import unittest

import numpy as np
import pandas as pd

from src.backtest.application.engine import BacktestConfig, run_backtest
from src.backtest.application.fast_engine import (
    fast_backtest_enabled,
    run_backtest_fast,
)


def _panels(n: int = 10, codes: list[str] | None = None) -> dict[str, pd.DataFrame]:
    codes = codes or ["600519", "000001"]
    dates = [f"2026-01-{i:02d}" for i in range(5, 5 + n)]
    idx = pd.Index(dates, name="trade_date")
    close = pd.DataFrame(
        {c: np.linspace(10, 10 + n, n) for c in codes},
        index=idx,
    )
    open_ = close * 0.99
    high = close * 1.02
    low = close * 0.98
    volume = pd.DataFrame(1_000_000.0, index=idx, columns=codes)
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _hold_signals(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    signals = pd.DataFrame(False, index=panels["close"].index, columns=panels["close"].columns)
    # 两笔独立 hold：次日开盘入场、固定持有，无一字板/停牌
    signals.iloc[1, 0] = True
    signals.iloc[2, 1] = True
    return signals


class FastEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("LOCI_BACKTEST_FAST")

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("LOCI_BACKTEST_FAST", None)
        else:
            os.environ["LOCI_BACKTEST_FAST"] = self._prev

    def test_flag_off_by_default(self) -> None:
        os.environ.pop("LOCI_BACKTEST_FAST", None)
        self.assertFalse(fast_backtest_enabled())

    def test_next_open_entry_matches_classic_without_stops(self) -> None:
        panels = _panels()
        signals = _hold_signals(panels)
        cfg = BacktestConfig(hold_days=3, stop_loss_pct=None, take_profit_pct=None, benchmark=None)

        os.environ["LOCI_BACKTEST_FAST"] = "1"
        self.assertTrue(fast_backtest_enabled())

        classic = run_backtest(signals, panels, entry_timing="next_open", config=cfg, strategy_slug="t")
        fast = run_backtest_fast(
            signals, panels, entry_timing="next_open", config=cfg, strategy_slug="t"
        )

        self.assertEqual(len(classic.trades), len(fast.trades))
        self.assertGreaterEqual(len(classic.trades), 2)
        self.assertEqual(classic.metrics["trades"], fast.metrics["trades"])
        # 总收益方向一致；关键均值字段对齐
        self.assertEqual(
            np.sign(classic.metrics["avg_net_return"]),
            np.sign(fast.metrics["avg_net_return"]),
        )
        self.assertAlmostEqual(
            classic.metrics["avg_net_return"],
            fast.metrics["avg_net_return"],
            places=4,
        )
        for ct, ft in zip(classic.trades, fast.trades):
            self.assertEqual(ct.code, ft.code)
            self.assertEqual(ct.signal_date, ft.signal_date)
            self.assertEqual(ct.entry_date, ft.entry_date)
            self.assertEqual(ct.exit_reason, ft.exit_reason)
            self.assertAlmostEqual(ct.net_return_pct, ft.net_return_pct, places=4)
        self.assertEqual(fast.config["fast"]["engine"], "classic")

    def test_close_entry_matches_classic_without_stops(self) -> None:
        panels = _panels()
        signals = _hold_signals(panels)
        cfg = BacktestConfig(hold_days=2, stop_loss_pct=None, take_profit_pct=None, benchmark=None)

        classic = run_backtest(signals, panels, entry_timing="close", config=cfg, strategy_slug="t")
        fast = run_backtest_fast(signals, panels, entry_timing="close", config=cfg, strategy_slug="t")

        self.assertEqual(len(classic.trades), len(fast.trades))
        self.assertAlmostEqual(
            classic.metrics["avg_net_return"],
            fast.metrics["avg_net_return"],
            places=4,
        )

    def test_next_dip_falls_back_to_classic_and_preserves_limit_fill(self) -> None:
        panels = _panels(n=10, codes=["600001"])
        signals = pd.DataFrame(False, index=panels["close"].index, columns=["600001"])
        signals.iloc[1, 0] = True
        panels["low"].iloc[2, 0] = panels["close"].iloc[1, 0] * 0.98
        target = panels["close"] * 0.98
        cfg = BacktestConfig(
            hold_days=1, stop_loss_pct=None, take_profit_pct=None, benchmark=None
        )

        classic = run_backtest(
            signals,
            panels,
            entry_timing="next_dip",
            entry_price_panel=target,
            config=cfg,
            strategy_slug="t",
        )
        fast = run_backtest_fast(
            signals,
            panels,
            entry_timing="next_dip",
            entry_price_panel=target,
            config=cfg,
            strategy_slug="t",
        )

        self.assertEqual(len(classic.trades), 1)
        self.assertEqual(len(fast.trades), 1)
        self.assertAlmostEqual(classic.trades[0].entry_price, target.iloc[1, 0], places=4)
        self.assertEqual(classic.trades, fast.trades)
        self.assertNotEqual(fast.config.get("engine"), "numpy_fast")

    def test_data_end_records_match_classic_without_stops(self) -> None:
        panels = _panels(n=8, codes=["600001"])
        signals = pd.DataFrame(False, index=panels["close"].index, columns=["600001"])
        signals.iloc[-2, 0] = True
        signals.iloc[-1, 0] = True
        cfg = BacktestConfig(hold_days=3, stop_loss_pct=None, take_profit_pct=None, benchmark=None)

        classic = run_backtest(signals, panels, entry_timing="open", config=cfg, strategy_slug="t")
        fast = run_backtest_fast(signals, panels, entry_timing="open", config=cfg, strategy_slug="t")

        self.assertEqual(len(classic.trades), len(fast.trades))
        self.assertEqual(classic.metrics, fast.metrics)
        self.assertEqual(
            [trade.exit_reason for trade in classic.trades],
            [trade.exit_reason for trade in fast.trades],
        )

    def test_invalid_data_end_close_is_skipped_consistently(self) -> None:
        """数据到头不等于可以用缺失收盘价伪造一笔交易。"""
        panels = _panels(n=5, codes=["600001"])
        signals = pd.DataFrame(False, index=panels["close"].index, columns=["600001"])
        signals.iloc[-1, 0] = True
        panels["close"].iloc[-1, 0] = np.nan
        cfg = BacktestConfig(hold_days=3, stop_loss_pct=None, take_profit_pct=None, benchmark=None)

        classic = run_backtest(signals, panels, entry_timing="open", config=cfg, strategy_slug="t")
        fast = run_backtest_fast(signals, panels, entry_timing="open", config=cfg, strategy_slug="t")

        self.assertEqual(classic.trades, [])
        self.assertEqual(fast.trades, [])
        self.assertEqual(classic.skipped, {"持有期内始终无法卖出": 1})
        self.assertEqual(classic.skipped, fast.skipped)
        self.assertEqual(classic.metrics, fast.metrics)

    def test_untradable_planned_exit_matches_classic_without_stops(self) -> None:
        panels = _panels(n=9, codes=["600001"])
        signals = pd.DataFrame(False, index=panels["close"].index, columns=["600001"])
        signals.iloc[1, 0] = True
        panels["volume"].iloc[3, 0] = 0.0
        cfg = BacktestConfig(hold_days=2, stop_loss_pct=None, take_profit_pct=None, benchmark=None)

        classic = run_backtest(signals, panels, entry_timing="open", config=cfg, strategy_slug="t")
        fast = run_backtest_fast(signals, panels, entry_timing="open", config=cfg, strategy_slug="t")

        self.assertEqual(classic.metrics, fast.metrics)
        self.assertEqual(classic.trades[0].exit_date, fast.trades[0].exit_date)
        self.assertAlmostEqual(classic.trades[0].exit_price, fast.trades[0].exit_price, places=4)

    def test_fallback_result_does_not_claim_numpy_fast_engine(self) -> None:
        """回退经典引擎后仍自称 numpy_fast，会让"两条路径是否一致"的复核失效。"""
        panels = _panels()
        signals = _hold_signals(panels)
        cfg = BacktestConfig(hold_days=5, stop_loss_pct=-1.0, benchmark=None)

        fast = run_backtest_fast(
            signals, panels, entry_timing="next_open", config=cfg, strategy_slug="t"
        )
        echo = fast.config.get("fast")
        self.assertIsInstance(echo, dict)
        self.assertEqual(echo["engine"], "classic")
        self.assertIn("止损", echo["fallback_reason"])

    def test_legacy_fast_entry_reports_shared_engine(self) -> None:
        panels = _panels()
        signals = _hold_signals(panels)
        cfg = BacktestConfig(
            hold_days=3, stop_loss_pct=None, take_profit_pct=None, benchmark=None
        )

        fast = run_backtest_fast(
            signals, panels, entry_timing="next_open", config=cfg, strategy_slug="t"
        )
        self.assertEqual(fast.config["fast"]["engine"], "classic")
        self.assertIn("共享引擎", fast.config["fast"]["fallback_reason"])

    def test_stop_loss_falls_back_to_classic(self) -> None:
        """有细规则止损时应回退经典——结果与直接 run_backtest 一致。"""
        panels = _panels()
        signals = _hold_signals(panels)
        cfg = BacktestConfig(
            hold_days=5,
            stop_loss_pct=-1.0,
            take_profit_pct=None,
            benchmark=None,
        )

        classic = run_backtest(signals, panels, entry_timing="next_open", config=cfg, strategy_slug="t")
        fast = run_backtest_fast(
            signals, panels, entry_timing="next_open", config=cfg, strategy_slug="t"
        )

        self.assertNotEqual(fast.config.get("engine"), "numpy_fast")
        self.assertEqual(len(classic.trades), len(fast.trades))
        self.assertEqual(classic.metrics, fast.metrics)
        for ct, ft in zip(classic.trades, fast.trades):
            self.assertEqual(ct.exit_reason, ft.exit_reason)
            self.assertAlmostEqual(ct.entry_price, ft.entry_price, places=6)
            self.assertAlmostEqual(ct.exit_price, ft.exit_price, places=6)
            self.assertAlmostEqual(ct.net_return_pct, ft.net_return_pct, places=4)


if __name__ == "__main__":
    unittest.main()
