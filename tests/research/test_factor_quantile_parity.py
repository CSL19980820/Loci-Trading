"""``factor_analysis`` 分组向量化的等价性证明。

改写前每天都要 ``sorted(key=lambda code: scores.loc[code])``——对 n 只票是
O(n log n) 次 pandas 标量标签查表——再把结果 ``.loc`` 标签散写进三张面板。
现在换成整块 ``lexsort`` + ``put_along_axis``，全程不碰标签索引。

分组决定的是"买哪 20 只"，错一位就是换了一只票，所以这里的判据是与照抄的
旧实现逐元素相等（含 NaN 位置与 dtype），不是统计意义上的接近。
"""
from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src.research.application import factor_analysis
from src.research.application.factor_analysis import (
    QuantileSignals,
    _date_key,
    _finite_positive,
    _numeric_panel,
    _quantile_groups,
    _rebalance_keys,
    _require_group_count,
    _require_min_samples,
    analyze_cross_section,
    build_quantile_signals,
)


# --------------------------------------------------------------------------
# 改写前的实现：逐字照抄自改动前的 factor_analysis.py
# --------------------------------------------------------------------------

def reference_quantile_groups(scores: pd.Series, group_count: int) -> pd.Series:
    ordered_codes = sorted(scores.index, key=lambda code: (float(scores.loc[code]), str(code)))
    count = len(ordered_codes)
    assignments = {
        code: min(group_count, (position * group_count) // count + 1)
        for position, code in enumerate(ordered_codes)
    }
    return pd.Series(assignments, index=ordered_codes, dtype="int64")


def reference_build_quantile_signals(
    scores: pd.DataFrame,
    *,
    group_count: int = 10,
    rebalance_dates=None,
    min_samples: int | None = None,
) -> QuantileSignals:
    score_values = _numeric_panel(scores, "scores")
    _require_group_count(group_count)
    required = group_count if min_samples is None else min_samples
    _require_min_samples(required, group_count)

    groups = pd.DataFrame(np.nan, index=score_values.index, columns=score_values.columns)
    top = pd.DataFrame(False, index=score_values.index, columns=score_values.columns)
    bottom = top.copy()
    status: dict[object, str] = {}
    rebalance_keys = _rebalance_keys(rebalance_dates)

    for day, row in score_values.iterrows():
        if rebalance_keys is not None and _date_key(day) not in rebalance_keys:
            status[day] = "not_rebalance"
            continue
        valid = row[_finite_positive(row)]
        if len(valid) < required:
            status[day] = "insufficient_valid_scores"
            continue
        assignments = reference_quantile_groups(valid, group_count)
        groups.loc[day, assignments.index] = assignments.to_numpy(dtype=float)
        top.loc[day, assignments.index] = assignments.eq(group_count).to_numpy()
        bottom.loc[day, assignments.index] = assignments.eq(1).to_numpy()
        status[day] = "selected"

    return QuantileSignals(
        groups=groups,
        top=top,
        bottom=bottom,
        status=pd.Series(status, index=score_values.index, dtype="object"),
        group_count=group_count,
    )


# --------------------------------------------------------------------------
# 合成数据
# --------------------------------------------------------------------------

def synthetic_scores(seed: int = 20260825, days: int = 40, codes: int = 60) -> pd.DataFrame:
    """覆盖并列分数、非正值、非有限值、整天/整列缺失的分数面板。

    并列分数是重点：次关键字 ``str(code)`` 一旦丢掉，两种实现会在同分处给出
    不同的组号，而随机浮点几乎不会撞上并列，光靠随机数测不出来。
    """
    rng = np.random.default_rng(seed)
    values = rng.uniform(0.2, 1.5, (days, codes))
    # 同一天多只票分数完全相同，逼出按代码排序的次关键字。
    values[:, 5:11] = values[:, [5]]
    values[3, :20] = 1.0
    # 非正与非有限：应判为无效，既不分组也不占名额。
    values[7, 0:3] = 0.0
    values[8, 4] = -0.5
    values[9, 6] = np.inf
    values[10, 7] = -np.inf
    # 散布的单点缺失。
    values[rng.random(values.shape) < 0.08] = np.nan
    # 整天缺失与样本不足。
    values[11, :] = np.nan
    values[12, 5:] = np.nan
    # 整列缺失：长期停牌。
    values[:, 1] = np.nan
    index = pd.Index(
        pd.date_range("2026-01-05", periods=days, freq="B").strftime("%Y-%m-%d"), name="date"
    )
    # 列顺序必须真的打乱：若代码随列号递增，丢掉次关键字也测不出来。
    names = [f"{600000 + int(v):06d}" for v in np.random.default_rng(99).permutation(900)[:codes]]
    return pd.DataFrame(values, index=index, columns=pd.Index(names, name="code"))


class SignalParityMixin:
    @staticmethod
    def realign(frame: pd.DataFrame, name) -> pd.DataFrame:
        """补回旧实现丢掉的轴名字。

        旧实现每天用 ``groups.loc[day, assignments.index] = ...`` 做标签散写，而
        ``assignments.index`` 没有名字，于是 columns 轴的名字被这次赋值抹成了
        None——只在当天真被选中时才发生，一天都没选中反而会保留。新实现全程不碰
        标签索引，名字原样带出。这是两者唯一的差异，而且只是元数据：取值、
        dtype、行列顺序都不受影响。比对前先对齐，见 test_columns_name_is_preserved。
        """
        return frame.rename_axis(columns=name)

    def assert_signals_equal(self, actual: QuantileSignals, expected: QuantileSignals, label: str) -> None:
        name = actual.groups.columns.name
        np.testing.assert_allclose(
            actual.groups.to_numpy(dtype=float),
            expected.groups.to_numpy(dtype=float),
            equal_nan=True,
            err_msg=f"{label}: groups 逐元素不一致",
        )
        pd.testing.assert_frame_equal(
            actual.groups, self.realign(expected.groups, name), obj=f"{label} groups"
        )
        pd.testing.assert_frame_equal(
            actual.top, self.realign(expected.top, name), obj=f"{label} top"
        )
        pd.testing.assert_frame_equal(
            actual.bottom, self.realign(expected.bottom, name), obj=f"{label} bottom"
        )
        pd.testing.assert_series_equal(actual.status, expected.status, obj=f"{label} status")
        self.assertEqual(actual.group_count, expected.group_count)


class QuantileGroupsParityTests(unittest.TestCase):
    """单个横截面的分组：组号与返回顺序都要与旧实现一致。"""

    def _valid_row(self, day: int) -> pd.Series:
        row = synthetic_scores().iloc[day]
        return row[_finite_positive(row)]

    def test_matches_reference_on_every_day(self) -> None:
        panel = synthetic_scores()
        for position in range(len(panel.index)):
            row = panel.iloc[position]
            valid = row[_finite_positive(row)]
            if valid.empty:
                continue
            for group_count in (2, 3, 10):
                with self.subTest(day=position, group_count=group_count):
                    actual = _quantile_groups(valid, group_count)
                    expected = reference_quantile_groups(valid, group_count)
                    # 旧实现用 dict + 列表索引建 Series，index.name 同样会丢（纯元数据）。
                    pd.testing.assert_series_equal(actual, expected.rename_axis(actual.index.name))
                    # 返回顺序本身是契约：旧实现按 (分数, 代码) 升序排。
                    self.assertEqual(list(actual.index), list(expected.index))

    def test_ties_break_by_code_string(self) -> None:
        """同分时按 ``str(code)`` 排——丢掉这个次关键字会换掉被选中的票。"""
        scores = pd.Series({"000300": 1.0, "000001": 1.0, "000200": 1.0, "000100": 1.0})
        actual = _quantile_groups(scores, 2)
        self.assertEqual(list(actual.index), ["000001", "000100", "000200", "000300"])
        self.assertEqual(list(actual), [1, 1, 2, 2])
        pd.testing.assert_series_equal(actual, reference_quantile_groups(scores, 2).rename_axis(actual.index.name))

    def test_non_string_labels_use_str_ordering(self) -> None:
        """标签不是字符串时，次关键字仍然是 ``str(code)``——10 排在 9 前面。"""
        scores = pd.Series({9: 1.0, 10: 1.0, 2: 1.0})
        actual = _quantile_groups(scores, 3)
        self.assertEqual(list(actual.index), [10, 2, 9])
        pd.testing.assert_series_equal(actual, reference_quantile_groups(scores, 3).rename_axis(actual.index.name))

    def test_group_sizes_differ_by_at_most_one(self) -> None:
        """等量分组的定义本身：任何两组的票数最多差一只。"""
        for count in (10, 11, 19, 100, 5176):
            scores = pd.Series(
                np.linspace(0.5, 1.5, count), index=[f"{i:06d}" for i in range(count)]
            )
            sizes = _quantile_groups(scores, 10).value_counts()
            with self.subTest(count=count):
                self.assertEqual(sorted(sizes.index), list(range(1, 11)))
                self.assertLessEqual(int(sizes.max() - sizes.min()), 1)

    def test_group_is_non_decreasing_in_score(self) -> None:
        valid = self._valid_row(0)
        assignments = _quantile_groups(valid, 10)
        self.assertTrue((np.diff(assignments.to_numpy()) >= 0).all())
        ordered = valid.reindex(assignments.index).to_numpy()
        self.assertTrue((np.diff(ordered) >= 0).all())


class BuildQuantileSignalsParityTests(SignalParityMixin, unittest.TestCase):
    """整块面板的分组信号：三张面板 + status 全部逐元素比对。"""

    def test_matches_reference_for_group_counts(self) -> None:
        panel = synthetic_scores()
        for group_count in (2, 3, 5, 10):
            with self.subTest(group_count=group_count):
                self.assert_signals_equal(
                    build_quantile_signals(panel, group_count=group_count),
                    reference_build_quantile_signals(panel, group_count=group_count),
                    f"group_count={group_count}",
                )

    def test_matches_reference_with_min_samples(self) -> None:
        panel = synthetic_scores()
        for min_samples in (10, 30, 55, 60, 5000):
            with self.subTest(min_samples=min_samples):
                self.assert_signals_equal(
                    build_quantile_signals(panel, group_count=10, min_samples=min_samples),
                    reference_build_quantile_signals(
                        panel, group_count=10, min_samples=min_samples
                    ),
                    f"min_samples={min_samples}",
                )

    def test_matches_reference_with_rebalance_dates(self) -> None:
        panel = synthetic_scores()
        every_seventh = list(panel.index[::7])
        cases = {
            "子集": every_seventh,
            "含未知日期": [*every_seventh, "2099-12-31"],
            "Timestamp 形式": [pd.Timestamp(day) for day in every_seventh],
            "空集合": [],
            "全集": list(panel.index),
        }
        for label, dates in cases.items():
            with self.subTest(case=label):
                self.assert_signals_equal(
                    build_quantile_signals(panel, rebalance_dates=dates),
                    reference_build_quantile_signals(panel, rebalance_dates=dates),
                    label,
                )

    def test_columns_name_is_preserved(self) -> None:
        """与旧实现唯一的差异：columns.name 不再被丢掉（纯元数据，不影响取值）。"""
        panel = synthetic_scores()
        signals = build_quantile_signals(panel)
        self.assertEqual(signals.groups.columns.name, "code")
        self.assertEqual(signals.groups.index.name, "date")
        self.assertEqual(signals.status.index.name, "date")
        # 旧实现只有在至少选中过一天时才会把名字抹掉，这个样本确实选中了。
        self.assertIsNone(reference_build_quantile_signals(panel).groups.columns.name)

    def test_ties_break_by_code_string_across_the_panel(self) -> None:
        """整块路径同样按 str(code) 破并列——这里的列顺序正好是代码的逆序。"""
        columns = pd.Index(["000400", "000300", "000200", "000100"], name="code")
        panel = pd.DataFrame(
            [[1.0, 1.0, 1.0, 1.0]],
            index=pd.Index(["2026-01-01"], name="date"),
            columns=columns,
        )
        signals = build_quantile_signals(panel, group_count=2)
        self.assertEqual(list(signals.groups.iloc[0]), [2.0, 2.0, 1.0, 1.0])
        self.assert_signals_equal(
            signals, reference_build_quantile_signals(panel, group_count=2), "整块并列"
        )

    def test_status_covers_all_three_branches(self) -> None:
        """parity 只证明"和旧的一样"；这条确认样本本身真的覆盖了三种状态。"""
        panel = synthetic_scores()
        signals = build_quantile_signals(panel, rebalance_dates=list(panel.index[::4]))
        self.assertEqual(
            set(signals.status),
            {"selected", "not_rebalance", "insufficient_valid_scores"},
        )

    def test_selection_invariants(self) -> None:
        """top/bottom 必须严格等于最高/最低组，且只落在有效分数上。"""
        panel = synthetic_scores()
        signals = build_quantile_signals(panel, group_count=10)
        groups = signals.groups
        pd.testing.assert_frame_equal(signals.top, groups.eq(10))
        pd.testing.assert_frame_equal(signals.bottom, groups.eq(1))
        assigned = groups.notna()
        valid = _finite_positive(panel)
        selected = signals.status.eq("selected").to_numpy()[:, None]
        np.testing.assert_array_equal(assigned.to_numpy(), valid.to_numpy() & selected)
        values = groups.to_numpy(dtype=float)
        present = values[~np.isnan(values)]
        self.assertTrue(((present >= 1) & (present <= 10)).all())

    def test_non_rebalance_days_emit_nothing(self) -> None:
        panel = synthetic_scores()
        signals = build_quantile_signals(panel, rebalance_dates=[panel.index[0]])
        skipped = signals.status.ne("selected").to_numpy()
        self.assertTrue(signals.groups.to_numpy()[skipped].size > 0)
        self.assertTrue(np.isnan(signals.groups.to_numpy()[skipped]).all())
        self.assertFalse(signals.top.to_numpy()[skipped].any())
        self.assertFalse(signals.bottom.to_numpy()[skipped].any())

    def test_rejects_invalid_arguments(self) -> None:
        panel = synthetic_scores(days=15, codes=25)
        for group_count in (1, 0, -1, True, 2.0):
            with self.subTest(group_count=group_count), self.assertRaises(ValueError):
                build_quantile_signals(panel, group_count=group_count)
        with self.assertRaises(ValueError):
            build_quantile_signals(panel, group_count=10, min_samples=9)
        with self.assertRaises(TypeError):
            build_quantile_signals(panel.to_numpy())


class EdgeCaseTests(SignalParityMixin, unittest.TestCase):
    """全 NaN 列 / 全 NaN 天、样本不足、单行、空输入。"""

    def _frame(self, values, days, codes) -> pd.DataFrame:
        index = pd.Index([f"2026-01-{i + 1:02d}" for i in range(days)], name="date")
        columns = pd.Index([f"{600000 + i:06d}" for i in range(codes)], name="code")
        return pd.DataFrame(np.asarray(values, dtype=float).reshape(days, codes), index, columns)

    def test_all_nan_column(self) -> None:
        panel = self._frame(np.tile(np.arange(1.0, 5.0), (3, 1)), 3, 4)
        panel.iloc[:, 2] = np.nan
        self.assert_signals_equal(
            build_quantile_signals(panel, group_count=3),
            reference_build_quantile_signals(panel, group_count=3),
            "全 NaN 列",
        )
        self.assertTrue(build_quantile_signals(panel, group_count=3).groups.iloc[:, 2].isna().all())

    def test_all_nan_day(self) -> None:
        panel = self._frame(np.tile(np.arange(1.0, 5.0), (3, 1)), 3, 4)
        panel.iloc[1, :] = np.nan
        signals = build_quantile_signals(panel, group_count=2)
        self.assert_signals_equal(
            signals, reference_build_quantile_signals(panel, group_count=2), "全 NaN 天"
        )
        self.assertEqual(signals.status.iloc[1], "insufficient_valid_scores")

    def test_fewer_valid_than_required(self) -> None:
        panel = self._frame([1.0, 2.0, np.nan, np.nan], 1, 4)
        for min_samples in (2, 3, 4):
            with self.subTest(min_samples=min_samples):
                self.assert_signals_equal(
                    build_quantile_signals(panel, group_count=2, min_samples=min_samples),
                        reference_build_quantile_signals(
                            panel, group_count=2, min_samples=min_samples
                        ),
                    f"min_samples={min_samples}",
                )

    def test_exactly_enough_samples(self) -> None:
        panel = self._frame([1.0, 2.0, 3.0, np.nan], 1, 4)
        signals = build_quantile_signals(panel, group_count=3)
        self.assert_signals_equal(
            signals, reference_build_quantile_signals(panel, group_count=3), "刚好够"
        )
        self.assertEqual(signals.status.iloc[0], "selected")
        self.assertEqual(list(signals.groups.iloc[0])[:3], [1.0, 2.0, 3.0])

    def test_single_row_and_single_valid_code(self) -> None:
        self.assert_signals_equal(
            build_quantile_signals(self._frame([0.4, 0.9], 1, 2), group_count=2),
            reference_build_quantile_signals(self._frame([0.4, 0.9], 1, 2), group_count=2),
            "单行",
        )
        lonely = self._frame([np.nan, 0.9], 1, 2)
        self.assert_signals_equal(
            build_quantile_signals(lonely, group_count=2),
            reference_build_quantile_signals(lonely, group_count=2),
            "单行单只有效",
        )

    def test_non_positive_and_infinite_scores_are_invalid(self) -> None:
        panel = self._frame([1.0, 0.0, -2.0, np.inf, -np.inf, 3.0], 1, 6)
        signals = build_quantile_signals(panel, group_count=2)
        self.assert_signals_equal(
            signals, reference_build_quantile_signals(panel, group_count=2), "非正/非有限"
        )
        np.testing.assert_allclose(
            signals.groups.iloc[0].to_numpy(dtype=float),
            [1.0, np.nan, np.nan, np.nan, np.nan, 2.0],
            equal_nan=True,
        )

    def test_empty_index(self) -> None:
        panel = self._frame(np.empty((0, 3)), 0, 3)
        signals = build_quantile_signals(panel, group_count=2)
        self.assert_signals_equal(
            signals, reference_build_quantile_signals(panel, group_count=2), "空行"
        )
        self.assertEqual(signals.groups.shape, (0, 3))
        self.assertTrue(signals.status.empty)

    def test_empty_columns(self) -> None:
        index = pd.Index(["2026-01-01", "2026-01-02"], name="date")
        panel = pd.DataFrame(index=index, columns=pd.Index([], name="code"), dtype=float)
        signals = build_quantile_signals(panel, group_count=2)
        self.assertEqual(signals.groups.shape, (2, 0))
        self.assertEqual(list(signals.status), ["insufficient_valid_scores"] * 2)
        self.assert_signals_equal(
            signals, reference_build_quantile_signals(panel, group_count=2), "空列"
        )


class CrossSectionRegressionTests(unittest.TestCase):
    """``analyze_cross_section`` 也吃 ``_quantile_groups``，一并锁住。"""

    def _panels(self):
        scores = synthetic_scores(seed=7, days=25, codes=40)
        rng = np.random.default_rng(11)
        labels = pd.DataFrame(
            rng.normal(0.0, 0.03, scores.shape) + (scores.to_numpy() - 1.0) * 0.05,
            index=scores.index,
            columns=scores.columns,
        )
        labels.iloc[5, :] = np.nan
        return scores, labels

    def test_matches_reference_grouping(self) -> None:
        scores, labels = self._panels()
        actual = analyze_cross_section(scores, labels, group_count=5, min_samples=10)
        with mock.patch.object(factor_analysis, "_quantile_groups", reference_quantile_groups):
            expected = analyze_cross_section(scores, labels, group_count=5, min_samples=10)
        pd.testing.assert_frame_equal(actual.daily, expected.daily)
        pd.testing.assert_frame_equal(actual.group_returns, expected.group_returns)
        self.assertEqual(actual.summary, expected.summary)
        self.assertGreater(actual.summary["evaluated_days"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
