from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.formula import (
    ABS,
    BARSCOUNT,
    BARSLAST,
    BARSSINCE,
    COUNT,
    CROSS,
    EMA,
    EVERY,
    EXIST,
    FILTER,
    HHV,
    HHVBARS,
    IF,
    LLV,
    LLVBARS,
    MA,
    MAX,
    MIN,
    REF,
    SMA,
    SUM,
    WMA,
    ZTPRICE,
    weighted_ref_sum,
)


def _panel(seed: int = 42, rows: int = 60, cols: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = np.cumsum(rng.normal(0, 1.0, (rows, cols)), axis=0) + 50.0
    return pd.DataFrame(
        values,
        index=pd.date_range("2026-01-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
        columns=[f"00000{i}" for i in range(cols)],
    )


class ShapeAgnosticTests(unittest.TestCase):
    """同一份实现必须对全市场面板和单票序列给出一致结果。

    这是整个引擎的立身之本：如果两种形状会分叉，那"单票调试通过"就
    不能推出"全市场扫描正确"，向量化带来的速度就没有意义了。
    """

    def test_panel_column_equals_standalone_series(self) -> None:
        panel = _panel()
        column = panel["000002"]
        cases = {
            "REF": (lambda x: REF(x, 3)),
            "MA": (lambda x: MA(x, 5)),
            "EMA": (lambda x: EMA(x, 12)),
            "SMA": (lambda x: SMA(x, 9, 3)),
            "WMA": (lambda x: WMA(x, 4)),
            "SUM": (lambda x: SUM(x, 6)),
            "HHV": (lambda x: HHV(x, 10)),
            "LLV": (lambda x: LLV(x, 10)),
            "HHVBARS": (lambda x: HHVBARS(x, 10)),
            "LLVBARS": (lambda x: LLVBARS(x, 10)),
            "BARSLAST": (lambda x: BARSLAST(x > x.rolling(5).mean())),
            "BARSSINCE": (lambda x: BARSSINCE(x > 52)),
            "COUNT": (lambda x: COUNT(x > 50, 7)),
            "FILTER": (lambda x: FILTER(x > 50, 4)),
        }
        for name, fn in cases.items():
            with self.subTest(fn=name):
                from_panel = fn(panel)["000002"]
                standalone = fn(column)
                pd.testing.assert_series_equal(
                    from_panel.astype(float).rename(None),
                    standalone.astype(float).rename(None),
                    check_names=False,
                    obj=f"{name} 面板列与单票序列结果不一致",
                )


class SemanticsTests(unittest.TestCase):
    """逐条对齐通达信语义，尤其是那些反直觉的边界。"""

    def test_ref_zero_returns_self(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0])
        pd.testing.assert_series_equal(REF(series, 0), series)

    def test_ref_rejects_negative_periods(self) -> None:
        """负偏移会读未来 K 线，公开 API 也必须和编译器一样拒绝。"""
        with self.assertRaises(ValueError):
            REF(pd.Series([1.0, 2.0, 3.0]), -1)

    def test_ma_returns_nan_before_window_is_full(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0, 4.0])
        result = MA(series, 3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)

    def test_sum_and_hhv_with_zero_period_mean_since_listing(self) -> None:
        series = pd.Series([1.0, 3.0, 2.0, 5.0])
        self.assertEqual(list(SUM(series, 0)), [1.0, 4.0, 6.0, 11.0])
        self.assertEqual(list(HHV(series, 0)), [1.0, 3.0, 3.0, 5.0])
        self.assertEqual(list(LLV(series, 0)), [1.0, 1.0, 1.0, 1.0])

    def test_wma_weights_the_latest_bar_most(self) -> None:
        """WMA 权重方向：越近权重越大。写反是最常见的翻译错误。"""
        rising = pd.Series(np.arange(1.0, 11.0))
        window = rising.iloc[-4:]
        self.assertGreater(WMA(rising, 4).iloc[-1], window.mean())

    def test_sma_is_recursive_not_simple_average(self) -> None:
        """SMA(X,N,M) 是递推式 Y=(M*X+(N-M)*Y')/N，不是简单均值。"""
        series = pd.Series([10.0, 20.0, 30.0])
        result = SMA(series, 2, 1)
        expected = [10.0, 10.0 + (20.0 - 10.0) / 2, 0.0]
        expected[2] = expected[1] + (30.0 - expected[1]) / 2
        for got, want in zip(result, expected):
            self.assertAlmostEqual(got, want)

    def test_barslast_is_zero_on_the_bar_it_fires(self) -> None:
        condition = pd.Series([False, True, False, False, True, False])
        self.assertTrue(np.isnan(BARSLAST(condition).iloc[0]))
        self.assertEqual(list(BARSLAST(condition).iloc[1:]), [0.0, 1.0, 2.0, 0.0, 1.0])

    def test_barssince_counts_from_the_first_hit(self) -> None:
        condition = pd.Series([False, True, False, True, False])
        self.assertEqual(list(BARSSINCE(condition).iloc[1:]), [0.0, 1.0, 2.0, 3.0])

    def test_hhvbars_is_zero_when_today_is_the_high(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0, 2.5, 2.0])
        result = HHVBARS(series, 3)
        self.assertEqual(result.iloc[2], 0.0)  # 当日即为最高
        self.assertEqual(result.iloc[3], 1.0)  # 最高在 1 根之前
        self.assertEqual(result.iloc[4], 2.0)

    def test_llvbars_mirrors_hhvbars(self) -> None:
        series = pd.Series([3.0, 2.0, 1.0, 1.5, 2.0])
        result = LLVBARS(series, 3)
        self.assertEqual(result.iloc[2], 0.0)
        self.assertEqual(result.iloc[4], 2.0)

    def test_extreme_bars_choose_the_nearest_equal_extreme(self) -> None:
        highs = pd.Series([1.0, 3.0, 3.0, 2.0])
        lows = pd.Series([3.0, 1.0, 1.0, 2.0])
        self.assertEqual(HHVBARS(highs, 3).iloc[2], 0.0)
        self.assertEqual(LLVBARS(lows, 3).iloc[2], 0.0)

    def test_filter_suppresses_repeats_within_the_window(self) -> None:
        condition = pd.Series([True, True, True, False, True, True])
        self.assertEqual(list(FILTER(condition, 2)), [True, False, False, False, True, False])

    def test_every_and_exist(self) -> None:
        condition = pd.Series([True, True, False, True])
        self.assertEqual(list(EVERY(condition, 2)), [False, True, False, False])
        self.assertEqual(list(EXIST(condition, 2)), [False, True, True, True])

    def test_cross_needs_a_real_crossing(self) -> None:
        fast = pd.Series([1.0, 2.0, 3.0, 2.0])
        slow = pd.Series([2.0, 2.0, 2.0, 2.0])
        self.assertEqual(list(CROSS(fast, slow)), [False, False, True, False])

    def test_barscount_starts_at_the_first_valid_bar(self) -> None:
        series = pd.Series([np.nan, np.nan, 1.0, 2.0, 3.0])
        result = BARSCOUNT(series)
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertEqual(list(result.iloc[2:]), [1.0, 2.0, 3.0])

    def test_if_accepts_scalars_and_series(self) -> None:
        condition = pd.Series([True, False, True])
        self.assertEqual(list(IF(condition, 1.0, 0.0)), [1.0, 0.0, 1.0])
        alt = pd.Series([10.0, 20.0, 30.0])
        self.assertEqual(list(IF(condition, alt, 0.0)), [10.0, 0.0, 30.0])
        self.assertEqual(IF(True, 1.0, 0.0), 1.0)
        self.assertEqual(MAX(1.0, 2.0), 2.0)
        self.assertEqual(MIN(1.0, 2.0), 1.0)

    def test_abs(self) -> None:
        self.assertEqual(list(ABS(pd.Series([-1.0, 2.0, -3.0]))), [1.0, 2.0, 3.0])


class ZtPriceTests(unittest.TestCase):
    def test_uses_half_up_rounding_not_bankers(self) -> None:
        """涨停价必须逢五进一。

        Python 内建 round() 是银行家舍入（round(10.045,2)->10.04），
        交易所是逢五进一（10.05）。差这一分钱就会把"是否涨停"判错，
        而涨停判断是所有打板类战法的地基。
        """
        prev = pd.Series([9.13, 10.045 / 1.1, 3.27])
        result = ZTPRICE(prev, 0.1)
        self.assertAlmostEqual(result.iloc[0], 10.04)  # 9.13*1.1 = 10.043
        self.assertAlmostEqual(result.iloc[1], 10.05)  # 恰好落在 .045
        self.assertAlmostEqual(result.iloc[2], 3.60)   # 3.27*1.1 = 3.597

    def test_supports_20_percent_boards(self) -> None:
        """创业板/科创板是 20%，北交所 30%，比例由调用方给。"""
        prev = pd.Series([10.0])
        self.assertAlmostEqual(ZTPRICE(prev, 0.2).iloc[0], 12.00)
        self.assertAlmostEqual(ZTPRICE(prev, 0.3).iloc[0], 13.00)

    def test_preserves_nan(self) -> None:
        self.assertTrue(np.isnan(ZTPRICE(pd.Series([np.nan]), 0.1).iloc[0]))


class WeightedRefSumTests(unittest.TestCase):
    def test_reproduces_a_hand_expanded_tdx_formula(self) -> None:
        """照抄式加权和：用于翻译手写展开成一串 REF 的公式。"""
        series = pd.Series(np.arange(1.0, 26.0))
        weights = {offset: float(20 - offset) for offset in range(0, 19)}
        weights[20] = 1.0
        result = weighted_ref_sum(series, weights, 211.0)

        index = 24
        expected = sum(weight * series.iloc[index - offset] for offset, weight in weights.items()) / 211.0
        self.assertAlmostEqual(result.iloc[index], expected)

    def test_rejects_zero_divisor(self) -> None:
        with self.assertRaises(ValueError):
            weighted_ref_sum(pd.Series([1.0]), {0: 1.0}, 0.0)


class NaiveReferenceTests(unittest.TestCase):
    """用最朴素的逐行 Python 实现做对照，证明向量化没有改变语义。"""

    def test_barslast_matches_naive_loop(self) -> None:
        rng = np.random.default_rng(7)
        flags = pd.Series(rng.random(200) > 0.75)

        naive: list[float] = []
        last: int | None = None
        for i, hit in enumerate(flags):
            if hit:
                last = i
            naive.append(np.nan if last is None else float(i - last))

        np.testing.assert_allclose(
            BARSLAST(flags).to_numpy(dtype=float), np.array(naive), equal_nan=True
        )

    def test_hhvbars_matches_naive_loop(self) -> None:
        rng = np.random.default_rng(11)
        series = pd.Series(rng.normal(0, 1, 120).cumsum())
        window = 15

        naive = [np.nan] * (window - 1)
        for i in range(window - 1, len(series)):
            chunk = series.iloc[i - window + 1 : i + 1].to_numpy()
            naive.append(float((window - 1) - int(np.argmax(chunk))))

        np.testing.assert_allclose(
            HHVBARS(series, window).to_numpy(dtype=float), np.array(naive), equal_nan=True
        )

    def test_count_matches_naive_loop(self) -> None:
        rng = np.random.default_rng(13)
        flags = pd.Series(rng.random(150) > 0.5)
        window = 9

        naive = [np.nan] * (window - 1)
        for i in range(window - 1, len(flags)):
            naive.append(float(flags.iloc[i - window + 1 : i + 1].sum()))

        np.testing.assert_allclose(
            COUNT(flags, window).to_numpy(dtype=float), np.array(naive), equal_nan=True
        )


if __name__ == "__main__":
    unittest.main()
