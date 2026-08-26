"""战法本体：前视偏差、入场时点、晨星打分、数据注入与公式接线。

注册表相关的用例在 `test_strategy_registry.py`；合成行情夹具在 `strategy_fixtures.py`。
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.formula import MA, REF
from src.strategy import all_strategies
from src.strategy.application.qianlong import CHENXING_DIVISOR, CHENXING_WEIGHTS, chenxing
from src.strategy.application.tail_resonance import SanyuanTailResonance
from src.strategy.domain.base import ENTRY_TIMINGS

from tests.strategy.strategy_fixtures import synthetic_panels


class LookAheadBiasTests(unittest.TestCase):
    """信号截断一致性：整个回测体系可信度的地基。

    做法是同一天的信号算两遍——一遍喂全部历史，一遍只喂到当天为止。
    如果某个指标偷看了未来（用了 shift(-1)、居中窗口、或者对整段做了
    全局归一化），两次结果就会不一致。

    这条必须常驻 CI：它防的不是今天的代码，而是将来任何一次指标改动
    悄悄引入未来函数——那种错误跑出来的回测收益很漂亮，但一分钱都赚不到。
    """

    def _assert_truncation_consistent(self, engine, panels, cut_positions) -> None:
        full = engine.compute(panels).signals
        index = panels["close"].index

        for position in cut_positions:
            cut_date = index[position]
            truncated_panels = {
                field: panel.iloc[: position + 1] for field, panel in panels.items()
            }
            partial = engine.compute(truncated_panels).signals

            self.assertIn(cut_date, partial.index, f"{engine.slug} 截断后丢了目标日")
            pd.testing.assert_series_equal(
                full.loc[cut_date].astype(bool),
                partial.loc[cut_date].astype(bool),
                check_names=False,
                obj=f"{engine.slug} 在 {cut_date} 的信号依赖了未来数据",
            )

    def test_every_registered_strategy_is_free_of_look_ahead(self) -> None:
        panels = synthetic_panels()
        rows = len(panels["close"].index)
        cuts = [rows - 1, rows - 5, rows - 20, int(rows * 0.7)]
        for engine in all_strategies():
            with self.subTest(strategy=engine.slug):
                self._assert_truncation_consistent(engine, panels, cuts)

    def test_appending_future_bars_never_changes_past_signals(self) -> None:
        """反向验证：往后追加新 K 线，历史信号必须一根都不变。"""
        panels = synthetic_panels(seed=99, rows=180)
        cut = 150
        head = {field: panel.iloc[:cut] for field, panel in panels.items()}
        for engine in all_strategies():
            with self.subTest(strategy=engine.slug):
                before = engine.compute(head).signals
                after = engine.compute(panels).signals.iloc[:cut]
                pd.testing.assert_frame_equal(
                    before.astype(bool),
                    after.astype(bool),
                    obj=f"{engine.slug} 的历史信号被后来的 K 线改写了",
                )


class EntryTimingTests(unittest.TestCase):
    """入场时点必须与策略实际用到的数据自洽。"""

    def test_declared_timings_are_valid(self) -> None:
        for engine in all_strategies():
            with self.subTest(strategy=engine.slug):
                self.assertIn(engine.entry_timing, ENTRY_TIMINGS)

    def test_close_based_strategy_cannot_claim_same_day_open_entry(self) -> None:
        """用到当日收盘/最低的策略，声称当日开盘成交就是前视偏差。

        用"把当日 close/high/low 换掉、只保留 open"的方式探测策略到底
        依赖了哪些当日数据：若信号随之改变，说明它用了开盘后才知道的信息，
        那就不能标成 entry_timing='open'。
        """
        panels = synthetic_panels(seed=7)
        index = panels["close"].index
        last = index[-1]

        for engine in all_strategies():
            if engine.entry_timing != "open":
                continue
            with self.subTest(strategy=engine.slug):
                baseline = engine.compute(panels).signals.loc[last]
                tampered = {field: panel.copy() for field, panel in panels.items()}
                # 只改当日的收盘/最高/最低，开盘价保持不变。
                for field in ("close", "high", "low"):
                    tampered[field].iloc[-1] = tampered[field].iloc[-1] * 1.05
                mutated = engine.compute(tampered).signals.loc[last]
                pd.testing.assert_series_equal(
                    baseline.astype(bool),
                    mutated.astype(bool),
                    check_names=False,
                    obj=(
                        f"{engine.slug} 声明 entry_timing='open'，但信号会随当日"
                        "收盘/最高/最低变化，说明用了开盘时还不知道的数据"
                    ),
                )


class ChenxingTests(unittest.TestCase):
    def test_weight_table_matches_the_tdx_source(self) -> None:
        """权重表要和通达信潜龙出海主图辰星线原式逐项对上。"""
        self.assertEqual(CHENXING_WEIGHTS[0], 20.0)
        self.assertEqual(CHENXING_WEIGHTS[1], 19.0)
        self.assertEqual(CHENXING_WEIGHTS[18], 2.0)
        self.assertNotIn(19, CHENXING_WEIGHTS, "原式跳过 REF 19，不能自作主张补上")
        self.assertEqual(CHENXING_WEIGHTS[20], 1.0)
        self.assertEqual(sum(CHENXING_WEIGHTS.values()), 210.0)
        self.assertEqual(CHENXING_DIVISOR, 211.0, "分母是 211，与权重和 210 不等，属原式构造")

    def test_matches_the_qianlong_module_implementation(self) -> None:
        """与 src/qianlong.py 的单票实现必须给出同一条线。

        两处独立实现同一个公式，互为对照：任何一边被改坏，这里就会红。
        """
        from src.formula.domain.qianlong import chenxing_line, ytsl as ytsl_single

        panels = synthetic_panels(seed=5, cols=3)
        code = panels["close"].columns[0]
        panel_line = chenxing(panels)[code]

        single_df = pd.DataFrame(
            {
                "收盘": panels["close"][code],
                "最低": panels["low"][code],
                "开盘": panels["open"][code],
                "最高": panels["high"][code],
            }
        )
        single_line = chenxing_line(ytsl_single(single_df))

        pd.testing.assert_series_equal(
            panel_line.astype(float).rename(None),
            single_line.astype(float).rename(None),
            check_names=False,
        )


class StrategyDataInjectionTests(unittest.TestCase):
    def test_sanyuan_tail_resonance_ranks_candidates_and_keeps_two(self) -> None:
        index = pd.date_range("2026-01-01", periods=26, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003"]
        close_values = np.full((26, 3), 10.0)
        close_values[-1] = [11.0, 10.8, 10.6]
        close = pd.DataFrame(close_values, index=index, columns=codes)
        open_ = close.copy()
        high = close * 1.01
        low = close * 0.99
        volume = pd.DataFrame(1_000_000.0, index=index, columns=codes)
        turnover = pd.DataFrame(0.02, index=index, columns=codes)

        result = SanyuanTailResonance().compute(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
            }
        )

        self.assertTrue(result.factors["A_MA25突破"].iloc[-1].all())
        self.assertEqual(result.signals.iloc[-1].tolist(), [True, True, False])
        self.assertEqual(SanyuanTailResonance().entry_timing, "next_open")
        self.assertEqual(SanyuanTailResonance().screen_hold_days, 1)

    def test_sanyuan_1450_variant_is_gone_for_good(self) -> None:
        """14:50 档已整体下线：注册表不认这个 slug，也不再挂任何定时。"""
        from src.strategy import StrategyError, get

        with self.assertRaises(StrategyError):
            get("sanyuan-tail-1450")
        self.assertFalse(get("sanyuan-tail-v1").screen_force_spot_refresh)

    def test_sanyuan_v2_applies_gate_after_top2_without_refilling(self) -> None:
        """V2.5：先闸门过滤全体候选，再按评分取 Top2（可落到原 Top2 之外的票）。"""
        index = pd.date_range("2026-01-01", periods=26, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003", "600004", "600005", "600006", "600007"]
        close_values = np.full((26, len(codes)), 10.0)
        close_values[-1] = [11.0, 10.8, 10.6, 9.0, 9.0, 9.0, 9.0]
        close = pd.DataFrame(close_values, index=index, columns=codes)
        open_ = close.copy()
        high = close * 1.005
        low = close * 0.98
        volume = pd.DataFrame(1_000_000.0, index=index, columns=codes)
        turnover = pd.DataFrame(0.02, index=index, columns=codes)
        turnover.iloc[-1, 2] = 0.10

        result = SanyuanTailResonance().compute(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
            }
        )

        self.assertEqual(
            result.factors["原始每日前二"].iloc[-1].tolist(),
            [True, True, False, False, False, False, False],
        )
        self.assertAlmostEqual(
            float(result.factors["市场上涨家数占比"].iloc[-1, 0]), 3 / 7
        )
        self.assertFalse(bool(result.factors["后置闸门"].iloc[-1, 0]))
        self.assertFalse(bool(result.factors["后置闸门"].iloc[-1, 1]))
        self.assertTrue(bool(result.factors["闸门_换手8%-12%"].iloc[-1, 2]))
        # 原 Top2 未过闸门；换手过闸的第三名可进入最终 Top2。
        self.assertEqual(
            result.signals.iloc[-1].tolist(),
            [False, False, True, False, False, False, False],
        )

    def test_sanyuan_v2_clv_gate_can_keep_an_original_top2(self) -> None:
        index = pd.date_range("2026-01-01", periods=26, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003", "600004"]
        close_values = np.full((26, len(codes)), 10.0)
        close_values[-1] = [11.0, 10.8, 9.0, 9.0]
        close = pd.DataFrame(close_values, index=index, columns=codes)
        open_ = close.copy()
        high = close * 1.01
        low = close * 0.99
        # 让第一只的收盘位于区间低位，CLV=0；其余列保持 CLV≈0.6。
        high.iloc[-1, 0] = close.iloc[-1, 0] * 1.01
        low.iloc[-1, 0] = close.iloc[-1, 0] * 0.99
        high.iloc[-1, 1:] = close.iloc[-1, 1:] * 1.005
        low.iloc[-1, 1:] = close.iloc[-1, 1:] * 0.98
        volume = pd.DataFrame(1_000_000.0, index=index, columns=codes)
        turnover = pd.DataFrame(0.02, index=index, columns=codes)

        result = SanyuanTailResonance().compute(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
            }
        )

        self.assertTrue(bool(result.factors["原始每日前二"].iloc[-1, 0]))
        self.assertTrue(bool(result.factors["闸门_CLV<0.5"].iloc[-1, 0]))
        self.assertTrue(bool(result.signals.iloc[-1, 0]))

    def test_sanyuan_excludes_unadjusted_price_below_six(self) -> None:
        """未复权现价 <6 元硬剔；前复权看起来贵也不能进正式信号。"""
        index = pd.date_range("2026-01-01", periods=26, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003"]
        close_values = np.full((26, 3), 10.0)
        close_values[-1] = [11.0, 10.8, 10.6]
        close = pd.DataFrame(close_values, index=index, columns=codes)
        raw = close.copy()
        raw.iloc[-1, 0] = 5.99
        raw.iloc[-1, 1] = 6.0
        result = SanyuanTailResonance().compute(
            {
                "open": close.copy(),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": pd.DataFrame(1_000_000.0, index=index, columns=codes),
                "turnover": pd.DataFrame(0.02, index=index, columns=codes),
                "__raw_close": raw,
            }
        )

        self.assertEqual(
            result.factors["闸门_现价>=6元"].iloc[-1].tolist(),
            [False, True, True],
        )
        # 评分最高的 600001 是仙股，Top2 让位给恰好 6 元与 10.6 元的两只。
        self.assertEqual(result.signals.iloc[-1].tolist(), [False, True, True])
        self.assertIsNotNone(result.watch_signals)
        assert result.watch_signals is not None
        self.assertFalse(bool(result.watch_signals.iloc[-1, 0]))

    def test_sanyuan_price_floor_falls_back_to_close(self) -> None:
        """没有未复权面板时，用 close 做现价门槛，避免单测/缺字段时放行仙股。"""
        index = pd.date_range("2026-01-01", periods=26, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003"]
        close_values = np.full((26, 3), 10.0)
        close_values[:, 0] = 5.0
        close_values[-1] = [5.5, 10.8, 10.6]
        close = pd.DataFrame(close_values, index=index, columns=codes)
        result = SanyuanTailResonance().compute(
            {
                "open": close.copy(),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": pd.DataFrame(1_000_000.0, index=index, columns=codes),
                "turnover": pd.DataFrame(0.02, index=index, columns=codes),
            }
        )

        self.assertFalse(bool(result.factors["闸门_现价>=6元"].iloc[-1, 0]))
        self.assertFalse(bool(result.signals.iloc[-1, 0]))


class FormulaWiringTests(unittest.TestCase):
    """确认策略里用到的公式函数确实作用在时间轴上。"""

    def test_ref_and_ma_operate_along_the_date_axis(self) -> None:
        panels = synthetic_panels(seed=17, rows=30, cols=4)
        close = panels["close"]
        self.assertTrue(REF(close, 1).iloc[0].isna().all(), "REF 必须沿时间轴取上一根")
        pd.testing.assert_series_equal(
            REF(close, 1).iloc[5], close.iloc[4], check_names=False
        )
        self.assertTrue(MA(close, 5).iloc[3].isna().all(), "不足窗口应为空值")


if __name__ == "__main__":
    unittest.main()
