from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.formula import (
    ATR,
    BOLL_LOWER,
    BOLL_MID,
    BOLL_UPPER,
    CCI,
    MACD,
    MACD_DEA,
    MACD_DIF,
    OBV,
    ROC,
    RSI,
    TR,
    WR,
)


class TechnicalIndicatorTests(unittest.TestCase):
    def test_rsi_uses_recursive_sma_and_waits_for_warmup(self) -> None:
        values = pd.Series(np.arange(1.0, 9.0))
        result = RSI(values, 3)
        self.assertTrue(result.iloc[:3].isna().all())
        self.assertAlmostEqual(float(result.iloc[3]), 100.0)

    def test_true_range_and_atr_preserve_first_bar_gap(self) -> None:
        high = pd.Series([11.0, 12.0, 13.0, 15.0])
        low = pd.Series([9.0, 10.0, 11.0, 12.0])
        close = pd.Series([10.0, 11.0, 12.0, 13.0])
        tr = TR(high, low, close)
        atr = ATR(high, low, close, 2)
        self.assertTrue(np.isnan(tr.iloc[0]))
        self.assertAlmostEqual(float(tr.iloc[1]), 2.0)
        self.assertTrue(np.isnan(atr.iloc[1]))
        self.assertAlmostEqual(float(atr.iloc[2]), 2.0)

    def test_momentum_and_volatility_indicators_have_expected_ranges(self) -> None:
        close = pd.Series([10.0, 11.0, 12.0, 11.0, 13.0, 14.0])
        high = close + 1.0
        low = close - 1.0
        self.assertAlmostEqual(float(ROC(close, 2).iloc[2]), 20.0)
        self.assertLessEqual(float(WR(high, low, close, 3).iloc[-1]), 0.0)
        self.assertGreaterEqual(float(RSI(close, 3).dropna().min()), 0.0)
        self.assertLessEqual(float(RSI(close, 3).dropna().max()), 100.0)
        self.assertAlmostEqual(float(CCI(high, low, close, 3).iloc[2]), 100.0)

    def test_obv_and_macd_are_deterministic(self) -> None:
        close = pd.Series([10.0, 11.0, 10.0, 10.0, 12.0])
        volume = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
        self.assertEqual(list(OBV(close, volume)), [0.0, 200.0, -100.0, -100.0, 400.0])
        dif = MACD_DIF(close, 2, 4)
        dea = MACD_DEA(close, 2, 4, 2)
        np.testing.assert_allclose(MACD(close, 2, 4, 2), (dif - dea) * 2, equal_nan=True)

    def test_bollinger_mid_upper_lower_share_the_same_window(self) -> None:
        close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        mid = BOLL_MID(close, 3)
        upper = BOLL_UPPER(close, 3, 2.0)
        lower = BOLL_LOWER(close, 3, 2.0)
        self.assertTrue(mid.iloc[:2].isna().all())
        self.assertAlmostEqual(float(mid.iloc[-1]), 4.0)
        self.assertGreater(float(upper.iloc[-1]), float(mid.iloc[-1]))
        self.assertLess(float(lower.iloc[-1]), float(mid.iloc[-1]))

    def test_panel_column_matches_standalone_series(self) -> None:
        index = pd.date_range("2026-01-01", periods=20, freq="D").strftime("%Y-%m-%d")
        close = pd.DataFrame({"000001": np.arange(10.0, 30.0), "000002": np.arange(20.0, 40.0)}, index=index)
        high = close + 1.0
        low = close - 1.0
        volume = pd.DataFrame(100.0, index=index, columns=close.columns)
        cases = {
            "RSI": RSI(close, 5),
            "ATR": ATR(high, low, close, 5),
            "CCI": CCI(high, low, close, 5),
            "OBV": OBV(close, volume),
            "MACD": MACD(close, 3, 6, 2),
        }
        for name, panel in cases.items():
            with self.subTest(indicator=name):
                standalone = {
                    "RSI": RSI(close["000002"], 5),
                    "ATR": ATR(high["000002"], low["000002"], close["000002"], 5),
                    "CCI": CCI(high["000002"], low["000002"], close["000002"], 5),
                    "OBV": OBV(close["000002"], volume["000002"]),
                    "MACD": MACD(close["000002"], 3, 6, 2),
                }[name]
                pd.testing.assert_series_equal(panel["000002"], standalone, check_names=False)


if __name__ == "__main__":
    unittest.main()
