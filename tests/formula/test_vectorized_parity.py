"""向量化改写的等价性证明：新实现 vs. 改写前的参考实现。

被替换的三个热点（``WMA`` / ``AVEDEV`` 的逐窗口 ``rolling.apply``、
``_extreme_bars`` 一次性物化 ``sliding_window_view``）都在下面留了一份逐字
照抄的旧实现作为 oracle。这类改写的风险不在"慢"而在"算错一位"，判据因此是
逐元素相等（含 NaN 位置），不是抽样对比。

``_extreme_bars`` 的改写目标是内存不是速度：旧写法对 (rows-N+1, cols, N)
整块 ``isnan`` + ``where``，250 天 × 5500 只 × N=60 峰值约 1.5 GB，而服务器
可用内存只有 1.1 G。这里用 ``tracemalloc`` 把这条约束钉成断言。
"""
from __future__ import annotations

import tracemalloc
import unittest
from unittest import mock
import warnings

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from src.formula.domain import functions
from src.formula.domain.functions import AVEDEV, HHVBARS, LLVBARS, WMA, _extreme_bars


# --------------------------------------------------------------------------
# 改写前的实现：逐字照抄自改动前的 src/formula/domain/functions.py
# --------------------------------------------------------------------------

def reference_wma(series, periods):
    if periods <= 0:
        raise ValueError("WMA 的周期必须为正")
    weights = np.arange(1, periods + 1, dtype=float)
    weights /= weights.sum()

    def _apply(window: np.ndarray) -> float:
        return float(np.dot(window, weights))

    return series.rolling(periods).apply(_apply, raw=True)


def reference_avedev(series, periods):
    def _apply(window: np.ndarray) -> float:
        return float(np.abs(window - window.mean()).mean())

    return series.rolling(periods).apply(_apply, raw=True)


def reference_extreme_bars(series, periods, *, highest):
    if periods <= 0:
        raise ValueError("HHVBARS/LLVBARS 的周期必须为正")
    values = np.asarray(series, dtype=float)
    single = values.ndim == 1
    matrix = values[:, None] if single else values
    rows, cols = matrix.shape
    out = np.full((rows, cols), np.nan, dtype=float)
    if rows >= periods:
        windows = sliding_window_view(matrix, periods, axis=0)
        with np.errstate(invalid="ignore"):
            picker = np.nanargmax if highest else np.nanargmin
            allnan = np.all(np.isnan(windows), axis=2)
            safe = np.where(np.isnan(windows), -np.inf if highest else np.inf, windows)
            distance = picker(safe[..., ::-1], axis=2).astype(float)
            distance[allnan] = np.nan
        out[periods - 1 :] = distance
    if single:
        return pd.Series(out[:, 0], index=series.index, name=series.name)
    return pd.DataFrame(out, index=series.index, columns=series.columns)


# --------------------------------------------------------------------------
# 合成数据
# --------------------------------------------------------------------------

def synthetic_panel(seed: int = 20260825, rows: int = 180, cols: int = 12) -> pd.DataFrame:
    """带缺口、平台期和重复极值的价格面板。

    只有随机游走不够：``HHVBARS`` 的并列取最近、``AVEDEV`` 的常数窗口、停牌造
    成的整段 NaN，都是逐窗口回调与整块规约最容易分叉的地方，必须真的出现在
    数据里。
    """
    rng = np.random.default_rng(seed)
    values = np.cumsum(rng.normal(0.0, 1.0, (rows, cols)), axis=0) + 50.0
    # 平台期：连续相同值制造并列极值。
    values[30:40, :] = values[30, :]
    if rows > 110:
        values[100:106, 3] = values[100, 3]
    # 停牌：整段缺失，长度覆盖 <N、=N、>N 三种情形。
    values[10:13, 1] = np.nan
    values[50:70, 2] = np.nan
    values[0, 4] = np.nan
    values[-1, 5] = np.nan
    # 单点缺失散布在整块面板上。
    values[rng.random(values.shape) < 0.02] = np.nan
    # 整列全空：停牌一整段行情的极端情形。
    values[:, 0] = np.nan
    return pd.DataFrame(
        values,
        index=pd.date_range("2026-01-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
        columns=[f"{600000 + i:06d}" for i in range(cols)],
    )


PERIODS = (1, 2, 3, 5, 20, 60)


def assert_same(actual, expected, message: str) -> None:
    """逐元素相等，NaN 位置也要一致。"""
    np.testing.assert_allclose(
        np.asarray(actual, dtype=float),
        np.asarray(expected, dtype=float),
        equal_nan=True,
        err_msg=message,
    )


class WmaParityTests(unittest.TestCase):
    """WMA：权重卷积必须与逐窗口 np.dot 逐元素一致。"""

    def test_panel_matches_reference(self) -> None:
        panel = synthetic_panel()
        for periods in PERIODS:
            with self.subTest(periods=periods):
                assert_same(WMA(panel, periods), reference_wma(panel, periods), f"N={periods}")

    def test_series_matches_reference(self) -> None:
        column = synthetic_panel()["600003"]
        for periods in PERIODS:
            with self.subTest(periods=periods):
                assert_same(WMA(column, periods), reference_wma(column, periods), f"N={periods}")

    def test_weights_still_favour_the_latest_bar(self) -> None:
        """权重方向写反不会被参考实现抓到——两者共用同一份权重表。"""
        rising = pd.Series(np.arange(1.0, 11.0))
        self.assertGreater(WMA(rising, 4).iloc[-1], rising.iloc[-4:].mean())
        self.assertAlmostEqual(
            float(WMA(rising, 4).iloc[-1]),
            (7 * 1 + 8 * 2 + 9 * 3 + 10 * 4) / 10,
        )

    def test_rejects_non_positive_periods(self) -> None:
        for periods in (0, -1):
            with self.subTest(periods=periods), self.assertRaises(ValueError):
                WMA(pd.Series([1.0, 2.0]), periods)


class AvedevParityTests(unittest.TestCase):
    """AVEDEV：CCI 的地基，错一位会顺着指标传遍全市场扫描。"""

    def test_panel_matches_reference(self) -> None:
        panel = synthetic_panel()
        for periods in PERIODS:
            with self.subTest(periods=periods):
                assert_same(
                    AVEDEV(panel, periods), reference_avedev(panel, periods), f"N={periods}"
                )

    def test_series_matches_reference(self) -> None:
        column = synthetic_panel()["600007"]
        for periods in PERIODS:
            with self.subTest(periods=periods):
                assert_same(
                    AVEDEV(column, periods), reference_avedev(column, periods), f"N={periods}"
                )

    def test_constant_window_is_exactly_zero(self) -> None:
        """常数窗口的平均绝对偏差必须是 0，不能是 1e-16 级别的残差。

        CCI 拿它当分母，一个假的极小值会把商放大到 1e15。
        """
        flat = pd.Series([7.0] * 10)
        self.assertTrue((AVEDEV(flat, 5).dropna() == 0.0).all())

    def test_period_semantics_match_rolling(self) -> None:
        """N=0 全为空值、N<0 报错——沿用改写前 rolling 的口径。"""
        series = pd.Series([1.0, 2.0, 3.0])
        self.assertTrue(AVEDEV(series, 0).isna().all())
        with warnings.catch_warnings():
            # 旧实现 N=0 时会对空窗口求均值并抛 RuntimeWarning，新实现直接短路。
            warnings.simplefilter("ignore", RuntimeWarning)
            self.assertTrue(reference_avedev(series, 0).isna().all())
        with self.assertRaises(ValueError):
            AVEDEV(series, -1)


class ExtremeBarsParityTests(unittest.TestCase):
    """HHVBARS/LLVBARS：分块只改内存布局，取值与并列口径必须原样。"""

    def test_panel_matches_reference(self) -> None:
        panel = synthetic_panel()
        for periods in PERIODS:
            for highest in (True, False):
                with self.subTest(periods=periods, highest=highest):
                    assert_same(
                        _extreme_bars(panel, periods, highest=highest),
                        reference_extreme_bars(panel, periods, highest=highest),
                        f"N={periods} highest={highest}",
                    )

    def test_series_matches_reference(self) -> None:
        column = synthetic_panel()["600009"]
        for periods in PERIODS:
            for highest in (True, False):
                with self.subTest(periods=periods, highest=highest):
                    assert_same(
                        _extreme_bars(column, periods, highest=highest),
                        reference_extreme_bars(column, periods, highest=highest),
                        f"N={periods} highest={highest}",
                    )

    def test_chunk_boundary_does_not_shift_results(self) -> None:
        """列数横跨分块边界时结果必须与单块一致。

        分块是这次改动唯一引入的新维度：宽度取 256，所以 255/256/257 三种列数
        分别落在"未满一块""正好一块""跨一块半"上。
        """
        base = synthetic_panel(seed=7, rows=90, cols=8).to_numpy()
        for cols in (255, 256, 257, 520):
            wide = pd.DataFrame(
                base[:, [i % base.shape[1] for i in range(cols)]],
                columns=[f"c{i}" for i in range(cols)],
            )
            with self.subTest(cols=cols):
                assert_same(
                    HHVBARS(wide, 20),
                    reference_extreme_bars(wide, 20, highest=True),
                    f"cols={cols}",
                )

    def test_chunk_width_never_changes_results(self) -> None:
        """分块宽度只是内存旋钮：1 / 7 / 恰好列数 / 远大于列数，结果必须一致。"""
        panel = synthetic_panel(seed=9, rows=70, cols=30)
        expected_bars = reference_extreme_bars(panel, 12, highest=True)
        expected_avedev = reference_avedev(panel, 12)
        for width in (1, 7, 29, 30, 31, 256, 10_000):
            with mock.patch.object(functions, "_COLUMN_CHUNK", width), self.subTest(width=width):
                assert_same(HHVBARS(panel, 12), expected_bars, f"chunk={width}")
                assert_same(AVEDEV(panel, 12), expected_avedev, f"chunk={width}")

    def test_ties_pick_the_nearest_bar(self) -> None:
        series = pd.Series([3.0, 3.0, 3.0, 2.0])
        self.assertEqual(HHVBARS(series, 3).iloc[2], 0.0)
        self.assertEqual(HHVBARS(series, 3).iloc[3], 1.0)
        lows = pd.Series([1.0, 1.0, 1.0, 2.0])
        self.assertEqual(LLVBARS(lows, 3).iloc[2], 0.0)

    def test_rejects_non_positive_periods(self) -> None:
        for periods in (0, -1):
            with self.subTest(periods=periods), self.assertRaises(ValueError):
                HHVBARS(pd.Series([1.0, 2.0]), periods)


class EdgeCaseTests(unittest.TestCase):
    """全 NaN 列、长度 < 窗口、单行、空输入。"""

    CASES = {
        "WMA": (WMA, reference_wma),
        "AVEDEV": (AVEDEV, reference_avedev),
        "HHVBARS": (HHVBARS, lambda s, n: reference_extreme_bars(s, n, highest=True)),
        "LLVBARS": (LLVBARS, lambda s, n: reference_extreme_bars(s, n, highest=False)),
    }

    def _check(self, frame, periods: int, label: str) -> None:
        for name, (new, old) in self.CASES.items():
            with self.subTest(case=label, fn=name):
                actual, expected = new(frame, periods), old(frame, periods)
                self.assertEqual(actual.shape, expected.shape)
                assert_same(actual, expected, f"{name} {label}")

    def test_all_nan_column(self) -> None:
        panel = pd.DataFrame({"a": [np.nan] * 8, "b": np.arange(8.0)})
        self._check(panel, 3, "全 NaN 列")
        self.assertTrue(HHVBARS(panel, 3)["a"].isna().all())
        self.assertTrue(AVEDEV(panel, 3)["a"].isna().all())

    def test_shorter_than_window(self) -> None:
        panel = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        self._check(panel, 5, "长度 < 窗口")
        self.assertTrue(AVEDEV(panel, 5).isna().all().all())

    def test_single_row(self) -> None:
        panel = pd.DataFrame({"a": [1.0], "b": [np.nan]})
        self._check(panel, 1, "单行 N=1")
        self._check(panel, 3, "单行 N>行数")
        self.assertEqual(float(HHVBARS(panel, 1)["a"].iloc[0]), 0.0)
        self.assertEqual(float(AVEDEV(panel, 1)["a"].iloc[0]), 0.0)

    def test_empty_input(self) -> None:
        self._check(pd.DataFrame({"a": [], "b": []}, dtype=float), 3, "空行")
        self._check(pd.Series([], dtype=float), 3, "空 Series")
        empty_cols = pd.DataFrame(index=pd.RangeIndex(5), dtype=float)
        for name, (new, _old) in self.CASES.items():
            with self.subTest(fn=name):
                self.assertEqual(new(empty_cols, 3).shape, (5, 0))

    def test_single_column_panel_matches_series(self) -> None:
        column = synthetic_panel()["600011"]
        frame = column.to_frame()
        for name, (new, _old) in self.CASES.items():
            with self.subTest(fn=name):
                assert_same(new(frame, 10).iloc[:, 0], new(column, 10), name)


class ExtremeBarsMemoryTests(unittest.TestCase):
    """峰值内存必须与股票数解耦——这是 OOM 护栏，不是性能锦上添花。"""

    ROWS, COLS, PERIODS = 120, 1200, 40

    def _peak_mib(self, fn) -> float:
        panel = synthetic_panel(seed=3, rows=self.ROWS, cols=self.COLS)
        tracemalloc.start()
        try:
            fn(panel)
            return tracemalloc.get_traced_memory()[1] / 1024**2
        finally:
            tracemalloc.stop()

    def test_peak_memory_is_far_below_the_reference(self) -> None:
        # 旧实现至少要物化一份 (rows-N+1, cols, N) 的 float64 数组。
        materialised = self.ROWS * self.COLS * self.PERIODS * 8 / 1024**2
        new_peak = self._peak_mib(lambda p: HHVBARS(p, self.PERIODS))
        old_peak = self._peak_mib(
            lambda p: reference_extreme_bars(p, self.PERIODS, highest=True)
        )
        self.assertGreater(old_peak, materialised * 0.5)
        # 新实现只按 256 列一批物化，峰值与总列数无关。
        self.assertLess(new_peak, materialised * 0.35)
        self.assertLess(new_peak * 2, old_peak)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
