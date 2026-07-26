from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.qianlong import add_qianlong, chenxing_line, ytsl


def _reference_chenxing(values: list[float], i: int) -> float:
    """独立参照实现：把 tdx/潜龙出海_主图.txt 的辰星线原式逐项抄下来。

    刻意不复用被测代码的任何写法，这样一旦被测实现的权重方向、
    跳过项或分母被改动，两边就会分叉。
    """
    total = 20 * values[i]
    for offset in range(1, 19):  # REF 1..18 -> 权重 19..2
        total += (20 - offset) * values[i - offset]
    total += values[i - 20]  # REF 20 -> 权重 1；原式跳过 REF 19
    return total / 211.0


class ChenxingLineTests(unittest.TestCase):
    def test_matches_tdx_formula_term_by_term(self) -> None:
        """与逐项展开的原式在每一根 K 线上都一致。"""
        rng = np.random.default_rng(20260726)
        values = list(rng.uniform(8.0, 40.0, size=60))
        out = chenxing_line(pd.Series(values))

        for i in range(20, len(values)):
            self.assertAlmostEqual(
                float(out.iloc[i]), _reference_chenxing(values, i), places=9,
                msg=f"第 {i} 根 K 线与原式不符",
            )

    def test_recent_bars_carry_the_larger_weight(self) -> None:
        """回归护栏：权重必须偏向近期，不能倒挂。

        对单调递增序列，近期加权均值必然高于同窗口简单均值。
        历史 bug 把权重 20 给了最旧一根、权重 1 给了当天，
        会让结果落到简单均值下方，这条断言即为此设。
        """
        y = pd.Series(np.arange(1.0, 31.0))
        out = chenxing_line(y)

        last = len(y) - 1
        window_mean = float(y.iloc[last - 20 : last + 1].mean())
        self.assertGreater(float(out.iloc[last]), window_mean)

        # 反过来：单调递减序列必须落在简单均值下方。
        out_desc = chenxing_line(pd.Series(np.arange(30.0, 0.0, -1.0)))
        desc_mean = float(pd.Series(np.arange(30.0, 0.0, -1.0)).iloc[last - 20 : last + 1].mean())
        self.assertLess(float(out_desc.iloc[last]), desc_mean)

    def test_denominator_211_is_deliberate(self) -> None:
        """锁定原式的非归一化构造，防止有人"顺手修正"成 210。

        权重之和是 210，原式分母是 211，因此常数序列的结果
        比该常数本身低约 0.47%。这是通达信原式的既有构造，
        改动它等于改策略口径，必须走单独决策而不是静默修复。
        """
        y = pd.Series([7.0] * 30)
        out = chenxing_line(y)
        self.assertAlmostEqual(float(out.iloc[-1]), 7.0 * 210 / 211, places=12)
        self.assertNotAlmostEqual(float(out.iloc[-1]), 7.0, places=4)

    def test_needs_21_bars(self) -> None:
        """原式含 REF(YTSL,20)，因此前 20 根没有有效值。"""
        out = chenxing_line(pd.Series(np.arange(1.0, 31.0)))
        self.assertTrue(out.iloc[:20].isna().all())
        self.assertTrue(pd.notna(out.iloc[20]))


class YtslTests(unittest.TestCase):
    def test_typical_price_weighting(self) -> None:
        """YTSL := (3*CLOSE + LOW + OPEN + HIGH) / 6"""
        df = pd.DataFrame(
            {"收盘": [10.0], "最低": [9.0], "开盘": [9.5], "最高": [11.0]}
        )
        self.assertAlmostEqual(float(ytsl(df).iloc[0]), (3 * 10.0 + 9.0 + 9.5 + 11.0) / 6)


class AddQianlongTests(unittest.TestCase):
    def test_pipeline_runs_and_chenxing_is_populated(self) -> None:
        """端到端：足够长的 K 线上，辰星线与派生的辰星升都要算得出来。"""
        n = 60
        rng = np.random.default_rng(7)
        close = pd.Series(np.cumsum(rng.normal(0, 0.5, n)) + 30.0)
        df = pd.DataFrame(
            {
                "收盘": close,
                "最低": close - 0.4,
                "最高": close + 0.4,
                "开盘": close.shift(1).fillna(close.iloc[0]),
                "成交量": rng.uniform(1e6, 5e6, n),
            }
        )

        out = add_qianlong(df)
        self.assertTrue(pd.notna(out["辰星线"].iloc[-1]))
        # 辰星线自身必须与直接调用一致，确保管线没有额外加工。
        self.assertAlmostEqual(
            float(out["辰星线"].iloc[-1]),
            float(chenxing_line(ytsl(df)).iloc[-1]),
            places=9,
        )


if __name__ == "__main__":
    unittest.main()
