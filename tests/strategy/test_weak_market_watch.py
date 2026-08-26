from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.strategy.application.qianlong import (
    QianlongCloseePickerV3,
    _QianlongCore,
)
from src.strategy.application.tail_resonance import SanyuanTailResonance
from src.strategy.domain.base import SignalResult


class WeakMarketWatchTests(unittest.TestCase):
    def test_qianlong_demotes_weak_market_candidates_to_watch(self) -> None:
        index = pd.date_range("2026-08-04", periods=6, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003"]
        close = pd.DataFrame(10.0, index=index, columns=codes)
        close.iloc[-1] = [11.0, 9.0, 9.0]
        turnover = pd.DataFrame(0.05, index=index, columns=codes)
        core_signals = pd.DataFrame(False, index=index, columns=codes)
        core_signals.iloc[-1] = True
        roc5 = pd.DataFrame(np.nan, index=index, columns=codes)
        roc5.iloc[-1] = [1.3, 1.2, 1.1]
        closeness = pd.DataFrame(np.nan, index=index, columns=codes)
        closeness.iloc[-1] = [0.99, 0.98, 0.80]
        core = SignalResult(
            signals=core_signals, factors={"ROC5": roc5, "白线贴近度": closeness}
        )

        with patch.object(_QianlongCore, "compute", return_value=core):
            result = QianlongCloseePickerV3().compute(
                {"close": close, "turnover": turnover}
            )

        self.assertEqual(result.signals.iloc[-1].tolist(), [False, False, False])
        self.assertIsNotNone(result.watch_signals)
        assert result.watch_signals is not None
        self.assertEqual(
            result.watch_signals.iloc[-1].tolist(), [True, True, False]
        )

    def test_qianlong_keeps_strong_market_candidates_formal(self) -> None:
        index = pd.date_range("2026-08-04", periods=6, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003"]
        close = pd.DataFrame(10.0, index=index, columns=codes)
        close.iloc[-1] = [11.0, 11.5, 9.0]
        turnover = pd.DataFrame(0.05, index=index, columns=codes)
        core_signals = pd.DataFrame(False, index=index, columns=codes)
        core_signals.iloc[-1] = True
        roc5 = pd.DataFrame(np.nan, index=index, columns=codes)
        roc5.iloc[-1] = [1.2, 1.3, 1.1]
        closeness = pd.DataFrame(np.nan, index=index, columns=codes)
        closeness.iloc[-1] = [0.99, 0.98, 0.80]
        core = SignalResult(
            signals=core_signals, factors={"ROC5": roc5, "白线贴近度": closeness}
        )

        with patch.object(_QianlongCore, "compute", return_value=core):
            result = QianlongCloseePickerV3().compute(
                {"close": close, "turnover": turnover}
            )

        self.assertEqual(result.signals.iloc[-1].tolist(), [True, True, False])
        self.assertIsNotNone(result.watch_signals)
        assert result.watch_signals is not None
        self.assertFalse(bool(result.watch_signals.iloc[-1].any()))

    def test_sanyuan_demotes_pre_market_gate_top_two_to_watch(self) -> None:
        index = pd.date_range("2026-01-01", periods=26, freq="B").strftime("%Y-%m-%d")
        codes = [f"60000{index}" for index in range(1, 9)]
        close_values = np.full((26, len(codes)), 10.0)
        close_values[-1] = [11.0, 10.8, 10.6, 9.0, 9.0, 9.0, 9.0, 9.0]
        close = pd.DataFrame(close_values, index=index, columns=codes)
        panels = {
            "open": close.copy(),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": pd.DataFrame(1_000_000.0, index=index, columns=codes),
            "turnover": pd.DataFrame(0.02, index=index, columns=codes),
        }

        engine = SanyuanTailResonance()
        result = engine.compute(panels)

        self.assertEqual(result.signals.iloc[-1].tolist(), [False] * len(codes))
        self.assertEqual(
            result.factors["弱市前候选"].iloc[-1].tolist(),
            [True, True, True, False, False, False, False, False],
        )
        self.assertIsNotNone(result.watch_signals)
        assert result.watch_signals is not None
        self.assertEqual(
            result.watch_signals.iloc[-1].tolist(),
            [True, True, False, False, False, False, False, False],
        )
        self.assertEqual(engine.screen_rank_factor, "横截面评分")


if __name__ == "__main__":
    unittest.main()
