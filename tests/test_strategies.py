from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.formula import MA, REF
from src.strategies import all_strategies, describe_all, get, merge_params
from src.strategies.base import ENTRY_TIMINGS, StrategyError
from src.strategies.qianlong import CHENXING_DIVISOR, CHENXING_WEIGHTS, chenxing, turnover_pct


def synthetic_panels(seed: int = 2026, rows: int = 160, cols: int = 40) -> dict[str, pd.DataFrame]:
    """造一批带随机涨跌与放量的合成行情，形状与真实面板一致。

    用合成数据而不是接真实行情：前视偏差是结构性质，与数据内容无关，
    而单测必须离线可复现、不受接口可用性影响。
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2025-01-01", periods=rows, freq="B").strftime("%Y-%m-%d")
    codes = [f"{600000 + i:06d}" for i in range(cols)]

    close = pd.DataFrame(
        np.cumprod(1 + rng.normal(0.001, 0.03, (rows, cols)), axis=0) * 20.0,
        index=index,
        columns=codes,
    )
    prev = close.shift(1).fillna(close.iloc[0])
    open_ = prev * (1 + rng.normal(0, 0.01, (rows, cols)))
    high = pd.concat([close, open_]).groupby(level=0).max() * (1 + abs(rng.normal(0, 0.012, (rows, cols))))
    low = pd.concat([close, open_]).groupby(level=0).min() * (1 - abs(rng.normal(0, 0.012, (rows, cols))))
    volume = pd.DataFrame(rng.lognormal(15, 0.6, (rows, cols)), index=index, columns=codes)
    turnover = pd.DataFrame(rng.uniform(0.005, 0.15, (rows, cols)), index=index, columns=codes)

    return {
        "open": open_.reindex(index),
        "high": high.reindex(index),
        "low": low.reindex(index),
        "close": close,
        "volume": volume,
        "turnover": turnover,
    }


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
        """权重表要和 tdx/潜龙出海_主图.txt 的原式逐项对上。"""
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
        from src.qianlong import chenxing_line, ytsl as ytsl_single

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


class TurnoverUnitTests(unittest.TestCase):
    def test_converts_fraction_to_tdx_percent(self) -> None:
        """通达信 HSL 是百分数，行情仓存的是小数——差 100 倍。

        漏掉这次换算，"昨换手>=5" 会变成要求 500% 换手，永远选不出票，
        而且不会报错，只会安静地返回空结果。
        """
        panels = {"turnover": pd.DataFrame({"000001": [0.05, 0.123]})}
        converted = turnover_pct(panels)
        self.assertAlmostEqual(converted.iloc[0, 0], 5.0)
        self.assertAlmostEqual(converted.iloc[1, 0], 12.3)


class RegistryTests(unittest.TestCase):
    def test_lookup_and_metadata(self) -> None:
        engine = get("qianlong-auction")
        self.assertEqual(engine.slug, "qianlong-auction")
        described = {item["slug"] for item in describe_all()}
        self.assertIn("qianlong-auction", described)
        self.assertIn("qianlong-close", described)

    def test_unknown_strategy_raises(self) -> None:
        with self.assertRaises(StrategyError):
            get("does-not-exist")

    def test_unknown_param_is_rejected_not_ignored(self) -> None:
        """静默忽略拼错的参数，会让人以为调过参了其实没有。"""
        engine = get("qianlong-auction")
        with self.assertRaises(StrategyError):
            merge_params(engine, {"gian_min": 3.0})
        merged = merge_params(engine, {"gain_min": 3.0})
        self.assertEqual(merged["gain_min"], 3.0)
        self.assertEqual(merged["gain_max"], engine.default_params()["gain_max"])

    def test_signals_have_the_same_shape_as_the_input_panel(self) -> None:
        panels = synthetic_panels(seed=3)
        for engine in all_strategies():
            with self.subTest(strategy=engine.slug):
                result = engine.compute(panels)
                self.assertEqual(result.signals.shape, panels["close"].shape)
                self.assertTrue(result.factors, "策略必须给出中间因子以便归因")

    def test_loosening_thresholds_never_shrinks_the_pick_set(self) -> None:
        """单调性自检：把门槛放宽，选出的票只能更多不能更少。

        若违反，说明条件之间有互相抵消的写法（常见于把 AND 写成了 OR、
        或者某个阈值被用在了不等号的另一侧）。
        """
        panels = synthetic_panels(seed=11, rows=200, cols=60)
        engine = get("qianlong-auction")
        strict = engine.compute(panels).signals.to_numpy().sum()
        loose = engine.compute(
            panels,
            {
                "gain_min": -100.0,
                "gain_max": 100.0,
                "amplitude_min": 0.0,
                "body_min": 0.0,
                "narrow_max": 5,
                "vol_ratio_min": 0.0,
                "vol_ratio_max": 1e9,
                "turnover_min": 0.0,
                "turnover_max": 1e9,
                "turnover_vs_ma5": 0.0,
                "turnover_x_volratio_min": 0.0,
                "breakout_count_max": 99,
            },
        ).signals.to_numpy().sum()
        self.assertGreaterEqual(loose, strict)


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
