from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.formula import COST, WINNER, chip_cost_series
from src.formula.domain.board import (
    LIMIT_20,
    LIMIT_30,
    LIMIT_DEFAULT,
    LIMIT_ST,
    limit_ratio_for,
    limit_ratio_panel,
    limit_up_flags,
    one_word_flags,
)

DAYS = [f"2026-03-{day:02d}" for day in range(2, 32)]


def _frames(closes: list[float], turnover: float = 0.05, spread: float = 0.02):
    n = len(closes)
    index = pd.Index(DAYS[:n], name="trade_date")
    close = pd.Series(closes, index=index, dtype=float)
    return (
        close * (1 + spread),
        close * (1 - spread),
        close,
        pd.Series([turnover] * n, index=index, dtype=float),
    )


class ChipDistributionTests(unittest.TestCase):
    """筹码是逐日换手衰减的递推模型，不是固定窗口的直方图。"""

    def test_quantiles_are_monotonic(self) -> None:
        high, low, close, turnover = _frames([10.0, 11.0, 12.0, 11.5, 13.0, 12.0] * 4)
        costs = chip_cost_series(high, low, close, turnover, (15.0, 50.0, 85.0))
        c15, c50, c85 = costs[15.0], costs[50.0], costs[85.0]
        valid = c50.notna()
        self.assertTrue((c15[valid] <= c50[valid]).all(), "COST15 不得高于 COST50")
        self.assertTrue((c50[valid] <= c85[valid]).all(), "COST50 不得高于 COST85")

    def test_costs_stay_inside_the_traded_price_range(self) -> None:
        high, low, close, turnover = _frames([10.0, 12.0, 9.0, 11.0, 13.0, 10.5] * 4)
        cost = COST(high, low, close, turnover, 50.0).dropna()
        self.assertGreaterEqual(cost.min(), low.min() * 0.98)
        self.assertLessEqual(cost.max(), high.max() * 1.02)

    def test_a_flat_stock_concentrates_all_chips_at_that_price(self) -> None:
        """价格一直不动，全部筹码就该压在那个价位上。"""
        high, low, close, turnover = _frames([10.0] * 20, spread=0.0)
        costs = chip_cost_series(high, low, close, turnover, (15.0, 85.0))
        spread_pct = (costs[85.0].iloc[-1] - costs[15.0].iloc[-1]) / 10.0
        self.assertLess(spread_pct, 0.05, "价格恒定时筹码应高度集中")

    def test_high_turnover_replaces_old_chips_faster(self) -> None:
        """换手率就是筹码换手的速度——这是这个模型区别于直方图的核心。

        同样从 10 元涨到 20 元，高换手的票筹码应该更快跟上新价格；
        低换手的票会留着大量低位成本。
        """
        prices = [10.0] * 10 + [20.0] * 10
        slow = chip_cost_series(*_frames(prices, turnover=0.01), (50.0,))[50.0]
        fast = chip_cost_series(*_frames(prices, turnover=0.30), (50.0,))[50.0]
        self.assertLess(slow.iloc[-1], fast.iloc[-1], "低换手应保留更多低位筹码")
        self.assertGreater(fast.iloc[-1], 15.0, "高换手的成本中枢应接近新价格")

    def test_one_word_bar_does_not_break_the_distribution(self) -> None:
        """一字板最高等于最低，三角分布退化——不能因此算出 NaN。"""
        index = pd.Index(DAYS[:6], name="trade_date")
        close = pd.Series([10.0, 11.0, 11.0, 12.0, 12.0, 13.0], index=index)
        high = close.copy()
        low = close.copy()  # 全是一字
        turnover = pd.Series([0.05] * 6, index=index)
        cost = COST(high, low, close, turnover, 50.0)
        self.assertTrue(cost.iloc[-1] == cost.iloc[-1], "一字板不应产生 NaN")

    def test_winner_reports_the_share_of_profitable_chips(self) -> None:
        """一路上涨到历史新高时，几乎所有筹码都是赚的。"""
        high, low, close, turnover = _frames([float(10 + i) for i in range(20)], turnover=0.10)
        winner = WINNER(high, low, close, turnover)
        self.assertGreater(winner.iloc[-1], 90.0)

        falling = _frames([float(30 - i) for i in range(20)], turnover=0.10)
        self.assertLess(WINNER(*falling).iloc[-1], 30.0, "一路下跌时获利盘应很少")

    def test_panel_and_single_series_agree(self) -> None:
        """同一份实现要对面板和单票给出一致结果，否则两条路径会分叉。"""
        prices = [10.0, 11.0, 10.5, 12.0, 11.0, 13.0] * 4
        high, low, close, turnover = _frames(prices)
        panel_args = [pd.DataFrame({"600001": s, "600002": s * 2}) for s in (high, low, close)]
        panel_args.append(pd.DataFrame({"600001": turnover, "600002": turnover}))

        single = COST(high, low, close, turnover, 50.0)
        panel = COST(*panel_args, 50.0)["600001"]
        np.testing.assert_allclose(
            panel.to_numpy(dtype=float), single.to_numpy(dtype=float),
            rtol=1e-9, equal_nan=True,
        )

    def test_each_stock_gets_its_own_price_grid(self) -> None:
        """2 元的票和 2000 元的票不能共用一套价格档位，否则前者全挤在第一档。"""
        prices_low = [2.0, 2.1, 2.2, 2.15, 2.3] * 6
        prices_high = [2000.0, 2100.0, 2200.0, 2150.0, 2300.0] * 6
        index = pd.Index(DAYS[:30], name="trade_date")
        close = pd.DataFrame({"a": prices_low, "b": prices_high}, index=index)
        panel = COST(close * 1.02, close * 0.98, close, close * 0 + 0.05, 50.0)
        self.assertLess(panel["a"].iloc[-1], 3.0)
        self.assertGreater(panel["b"].iloc[-1], 1900.0)


class BoardLimitTests(unittest.TestCase):
    """涨停判定是所有打板战法的地基，判错幅度整个战法就不成立。"""

    def test_limit_ratio_by_board(self) -> None:
        cases = [
            ("600519", "", LIMIT_DEFAULT),   # 沪主板
            ("000001", "", LIMIT_DEFAULT),   # 深主板
            ("300750", "", LIMIT_20),        # 创业板
            ("301291", "", LIMIT_20),
            ("688981", "", LIMIT_20),        # 科创板
            ("689009", "", LIMIT_20),
            ("830799", "", LIMIT_30),        # 北交所
            ("430047", "", LIMIT_30),
            ("000『x』"[:6], "", LIMIT_DEFAULT),
        ]
        for code, name, expected in cases:
            with self.subTest(code=code):
                self.assertEqual(limit_ratio_for(code, name), expected)

    def test_st_is_five_percent(self) -> None:
        self.assertEqual(limit_ratio_for("600001", "ST某某"), LIMIT_ST)
        self.assertEqual(limit_ratio_for("600001", "*ST某某"), LIMIT_ST)
        self.assertEqual(limit_ratio_for("600001", "某某股份"), LIMIT_DEFAULT)

    def test_board_prefix_wins_over_st(self) -> None:
        """原式先判板块再判 ST，这里照抄它的顺序。"""
        self.assertEqual(limit_ratio_for("300001", "ST某某"), LIMIT_20)

    def test_ratio_panel_is_constant_per_column(self) -> None:
        close = pd.DataFrame(
            {"600519": [10.0, 11.0], "300750": [20.0, 21.0]},
            index=pd.Index(DAYS[:2], name="trade_date"),
        )
        ratios = limit_ratio_panel(close)
        self.assertEqual(ratios.shape, close.shape)
        self.assertTrue((ratios["600519"] == LIMIT_DEFAULT).all())
        self.assertTrue((ratios["300750"] == LIMIT_20).all())

    def test_detects_limit_up_at_the_right_threshold(self) -> None:
        """10 元主板涨停价是 11.00；创业板是 12.00。差一分钱就判错。"""
        index = pd.Index(DAYS[:2], name="trade_date")
        close = pd.DataFrame({"600519": [10.0, 11.00], "300750": [10.0, 11.00]}, index=index)
        high = close.copy()
        ratios = limit_ratio_panel(close)
        flags = limit_up_flags(close, high, ratios)
        self.assertTrue(flags["600519"].iloc[1], "主板 10→11 应判为涨停")
        self.assertFalse(flags["300750"].iloc[1], "创业板 10→11 只有 10%，未涨停")

    def test_limit_up_requires_the_close_to_seal(self) -> None:
        """炸板（收盘低于最高）不算涨停。"""
        index = pd.Index(DAYS[:2], name="trade_date")
        close = pd.DataFrame({"600519": [10.0, 10.5]}, index=index)
        high = pd.DataFrame({"600519": [10.0, 11.0]}, index=index)
        flags = limit_up_flags(close, high, limit_ratio_panel(close))
        self.assertFalse(flags["600519"].iloc[1])

    def test_half_up_rounding_matches_the_exchange(self) -> None:
        """交易所逢五进一；Python 的 round() 是银行家舍入，会差一分。"""
        index = pd.Index(DAYS[:2], name="trade_date")
        # 9.13 × 1.1 = 10.043 → 10.04
        close = pd.DataFrame({"600001": [9.13, 10.04]}, index=index)
        flags = limit_up_flags(close, close.copy(), limit_ratio_panel(close))
        self.assertTrue(flags["600001"].iloc[1])

    def test_one_word_detection(self) -> None:
        index = pd.Index(DAYS[:3], name="trade_date")
        high = pd.DataFrame({"a": [11.0, 12.0, 13.0]}, index=index)
        low = pd.DataFrame({"a": [11.0, 11.5, 13.0]}, index=index)
        flags = one_word_flags(high, low)
        self.assertEqual(list(flags["a"]), [True, False, True])


if __name__ == "__main__":
    unittest.main()


class MissingTurnoverTests(unittest.TestCase):
    """没有换手率就没有筹码分布——必须给空值，不能给一个看着正常的错数字。"""

    def test_all_nan_turnover_yields_nan_not_a_stale_price(self) -> None:
        """衰减率缺失会让筹码永远停在第一天，算出来毫无意义。

        这种静默的错误答案比直接报错危险得多：它会一路流进选股结果，
        而且看起来完全正常。
        """
        index = pd.Index(DAYS[:20], name="trade_date")
        close = pd.Series([10.0 + i for i in range(20)], index=index, dtype=float)
        turnover = pd.Series([np.nan] * 20, index=index, dtype=float)
        cost = COST(close * 1.02, close * 0.98, close, turnover, 50.0)
        self.assertTrue(cost.isna().all(), "换手率全缺时 COST 必须全为空")

    def test_zero_turnover_is_also_unusable(self) -> None:
        index = pd.Index(DAYS[:20], name="trade_date")
        close = pd.Series([10.0 + i for i in range(20)], index=index, dtype=float)
        turnover = pd.Series([0.0] * 20, index=index, dtype=float)
        self.assertTrue(COST(close * 1.02, close * 0.98, close, turnover, 50.0).isna().all())

    def test_one_bad_column_does_not_poison_the_others(self) -> None:
        """全市场面板里有几只票缺数据是常态，不能因此让整批作废。"""
        index = pd.Index(DAYS[:20], name="trade_date")
        good = pd.Series([10.0 + i for i in range(20)], index=index, dtype=float)
        close = pd.DataFrame({"600001": good, "600002": good}, index=index)
        turnover = pd.DataFrame(
            {"600001": [0.05] * 20, "600002": [np.nan] * 20}, index=index
        )
        cost = COST(close * 1.02, close * 0.98, close, turnover, 50.0)
        self.assertFalse(cost["600001"].isna().all(), "有数据的票应正常算出")
        self.assertTrue(cost["600002"].isna().all(), "缺数据的票应全空")

    def test_winner_also_refuses_without_turnover(self) -> None:
        index = pd.Index(DAYS[:20], name="trade_date")
        close = pd.Series([10.0 + i for i in range(20)], index=index, dtype=float)
        turnover = pd.Series([np.nan] * 20, index=index, dtype=float)
        self.assertTrue(WINNER(close * 1.02, close * 0.98, close, turnover).isna().all())
