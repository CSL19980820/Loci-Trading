from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.formula import COUNT, CROSS, EXIST, MA, REF, ZTPRICE
from src.strategy.application.screen_formula import build_formula_engine
from src.strategy import all_strategies, describe_all, get, merge_params
from src.strategy.domain.base import ENTRY_TIMINGS, StrategyError
from src.strategy.application.qianlong import (
    CHENXING_DIVISOR,
    CHENXING_WEIGHTS,
    chenxing,
    select_one_per_day,
)
from src.strategy.application.tail_resonance import SanyuanTailResonance


QIANLONG_TDX_FORMULA = """
YTSL:=(3*CLOSE+LOW+OPEN+HIGH)/6;
白色线:=(20*YTSL+19*REF(YTSL,1)+18*REF(YTSL,2)+17*REF(YTSL,3)+16*REF(YTSL,4)+15*REF(YTSL,5)+14*REF(YTSL,6)+13*REF(YTSL,7)+12*REF(YTSL,8)+11*REF(YTSL,9)+10*REF(YTSL,10)+9*REF(YTSL,11)+8*REF(YTSL,12)+7*REF(YTSL,13)+6*REF(YTSL,14)+5*REF(YTSL,15)+4*REF(YTSL,16)+3*REF(YTSL,17)+2*REF(YTSL,18)+REF(YTSL,20))/211;
黄色线:=MA(CLOSE,26);
死叉:=CROSS(黄色线,白色线);
曾死叉:=EXIST(死叉,20);
白线下运行:=COUNT(CLOSE<白色线,10)>=3;
昨阳:=CLOSE>OPEN AND CLOSE>=6;
昨突破白线:=CLOSE>白色线 AND REF(CLOSE,1)<=REF(白色线,1);
昨放量:=VOL>MA(VOL,5)*1.3;
昨站稳:=CLOSE>白色线*1.002;
突破日:=昨阳 AND 昨突破白线 AND 昨放量 AND 昨站稳;
白线向上:=白色线>REF(白色线,1);
非涨停价:=CLOSE<ZTPRICE(REF(CLOSE,1),0.1);
XG:曾死叉 AND 白线下运行 AND 突破日 AND 白线向上 AND 非涨停价;
"""


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

    def test_rsi30_dip_signal_uses_oversold_bullish_close_position(self) -> None:
        engine = get("rsi30-dip")
        index = pd.date_range("2026-01-01", periods=22, freq="B").strftime("%Y-%m-%d")
        close_values = [20.0] * 16 + [19.0, 18.0, 17.0, 16.0, 15.0, 15.5]
        close = pd.DataFrame({"600001": close_values}, index=index)
        open_ = close.copy()
        open_.iloc[-1, 0] = 15.0
        low = close.copy()
        low.iloc[-1, 0] = 14.8
        high = close.copy()
        high.iloc[-1, 0] = 15.9
        panels = {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": pd.DataFrame(1_000_000.0, index=index, columns=["600001"]),
        }

        result = engine.compute(
            panels, {"rsi_max": 30.0, "close_position_min": 0.60, "price_min": 5.0}
        )

        self.assertTrue(bool(result.signals.iloc[-1, 0]))
        self.assertLess(float(result.factors["RSI14"].iloc[-1, 0]), 30.0)
        self.assertGreater(float(result.factors["收盘位置"].iloc[-1, 0]), 0.60)
        self.assertAlmostEqual(float(result.factors["次日挂价"].iloc[-1, 0]), 15.19)

    def test_rsi30_dip_defaults_use_the_optimized_pool_and_thresholds(self) -> None:
        engine = get("rsi30-dip")

        self.assertEqual(engine.default_params()["rsi_max"], 22.0)
        self.assertEqual(engine.default_params()["close_position_min"], 0.80)
        self.assertEqual(
            engine.default_universe,
            {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        )
        self.assertEqual(engine.warmup_bars, 100)
        self.assertEqual(engine.strategy_revision, "builtin:rsi30-dip-v2")

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


class RegistryTests(unittest.TestCase):
    def test_lookup_and_metadata(self) -> None:
        engine = get("qianlong-close-v3")
        self.assertEqual(engine.slug, "qianlong-close-v3")
        self.assertEqual(engine.name, "潜龙出海（V3）")
        described = {item["slug"]: item for item in describe_all()}
        self.assertEqual(
            set(described),
            {"qianlong-close-v3", "qianlong-tail-v1", "rsi30-dip", "sanyuan-tail-v1"},
        )
        self.assertNotIn("sanyuan-tail-v2", described)
        self.assertNotIn("qianlong-close", described)
        self.assertNotIn("qianlong-close-v2", described)
        with self.assertRaises(StrategyError):
            get("qianlong-close-v2")
        with self.assertRaises(StrategyError):
            get("lugw-haidi")
        for item in described.values():
            self.assertIn("version", item)
            self.assertIn("version_history", item)
            self.assertIn("backtest_metrics", item)
            self.assertIn("backtest_config", item)
        self.assertNotIn("qianlong-auction", described)
        self.assertNotIn("lugw-tianyi", described)
        self.assertNotIn("lugw-daoba", described)
        self.assertNotIn("lugw-fenshou", described)
        for slug in ("lugw-sanwai", "lugw-sanwai-v2", "lugw-chouma"):
            self.assertNotIn(slug, described)
        self.assertNotIn("lugw-haidi", described)
        self.assertEqual(described["qianlong-close-v3"]["params"]["death_lookback"], 15)
        self.assertEqual(described["qianlong-close-v3"]["params"]["price_min"], 8.0)
        self.assertEqual(described["qianlong-close-v3"]["params"]["turnover_min"], 0.02)
        self.assertEqual(described["qianlong-close-v3"]["params"]["turnover_max"], 0.08)
        self.assertIn("T+1", described["qianlong-close-v3"]["entry_instructions"])
        self.assertEqual(described["qianlong-tail-v1"]["entry_timing"], "close")
        self.assertEqual(described["qianlong-tail-v1"]["params"]["price_min"], 10.0)
        self.assertIn("ROC5", described["qianlong-tail-v1"]["entry_instructions"])
        self.assertIn("RSI14<22", described["rsi30-dip"]["entry_instructions"])
        sanyuan = described["sanyuan-tail-v1"]
        self.assertIn("T+2 收盘卖出", sanyuan["entry_instructions"])
        self.assertIn("不递补第三名", sanyuan["entry_instructions"])
        self.assertEqual(sanyuan["entry_timing"], "next_open")
        self.assertEqual(sanyuan["version"], "v2")
        self.assertEqual(sanyuan["strategy_revision"], "builtin:sanyuan-tail-v2")
        self.assertEqual(sanyuan["version_history"][0]["status"], "archived")
        self.assertEqual(sanyuan["version_history"][1]["status"], "active")
        self.assertEqual(sanyuan["backtest_metrics"]["trades"], 138)
        self.assertAlmostEqual(sanyuan["backtest_metrics"]["win_rate"], 53.62)
        self.assertAlmostEqual(sanyuan["backtest_metrics"]["payoff_ratio"], 1.2142)
        self.assertAlmostEqual(sanyuan["backtest_metrics"]["profit_factor"], 1.4039)
        self.assertEqual(sanyuan["backtest_metrics"]["completed_trades"], 138)
        self.assertEqual(sanyuan["backtest_metrics"]["portfolio_trades"], 86)
        self.assertAlmostEqual(sanyuan["backtest_metrics"]["portfolio_return_pct"], 95.2232)
        self.assertAlmostEqual(sanyuan["backtest_metrics"]["max_drawdown_pct"], -34.3005)
        self.assertIn("turnover", sanyuan["required_fields"])
        self.assertEqual(
            sanyuan["default_universe"],
            {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        )

    def test_registered_strategy_window_contracts_are_explicit(self) -> None:
        expected = {
            "qianlong-close-v3": 46,
            "qianlong-tail-v1": 46,
            "rsi30-dip": 20,
            "sanyuan-tail-v1": 25,
        }
        actual = {engine.slug: engine.min_bars() for engine in all_strategies()}
        self.assertEqual(actual, expected)

    def test_unknown_strategy_raises(self) -> None:
        with self.assertRaises(StrategyError):
            get("does-not-exist")

    def test_unknown_param_is_rejected_not_ignored(self) -> None:
        """静默忽略拼错的参数，会让人以为调过参了其实没有。"""
        engine = get("qianlong-close-v3")
        with self.assertRaises(StrategyError):
            merge_params(engine, {"vol_boostt": 1.0})
        merged = merge_params(engine, {"vol_boost": 1.0})
        self.assertEqual(merged["vol_boost"], 1.0)
        self.assertEqual(merged["hold_ratio"], engine.default_params()["hold_ratio"])

    def test_signals_have_the_same_shape_as_the_input_panel(self) -> None:
        panels = synthetic_panels(seed=3)
        for engine in all_strategies():
            with self.subTest(strategy=engine.slug):
                result = engine.compute(panels)
                self.assertEqual(result.signals.shape, panels["close"].shape)
                self.assertTrue(result.factors, "策略必须给出中间因子以便归因")

    def test_qianlong_close_defaults_match_yunyang_tdx(self) -> None:
        """V3 保留历史 V2 原式结构，并增加换手率过滤。"""
        engine = get("qianlong-close-v3")
        params = engine.default_params()
        self.assertEqual(params["death_lookback"], 15)
        self.assertEqual(params["below_window"], 10)
        self.assertEqual(params["below_min"], 3)
        self.assertEqual(params["price_min"], 8.0)
        self.assertEqual(params["vol_boost"], 1.3)
        self.assertEqual(params["hold_ratio"], 1.002)
        self.assertEqual(params["turnover_min"], 0.02)
        self.assertEqual(params["turnover_max"], 0.08)
        self.assertEqual(engine.entry_timing, "next_open")
        self.assertEqual(engine.min_bars(), 46)

    def test_tail_selector_keeps_one_stable_winner_per_day(self) -> None:
        index = pd.Index(["2026-01-01", "2026-01-02"], name="trade_date")
        candidates = pd.DataFrame(
            [[True, True, False], [False, True, True]],
            index=index,
            columns=["600001", "600002", "600003"],
        )
        strength = pd.DataFrame(
            [[1.02, 1.05, 1.20], [1.03, 1.03, 1.01]],
            index=index,
            columns=candidates.columns,
        )
        selected = select_one_per_day(candidates, strength)
        self.assertEqual(selected.loc["2026-01-01"].to_dict(), {
            "600001": False,
            "600002": True,
            "600003": False,
        })
        self.assertEqual(selected.loc["2026-01-02"].to_dict(), {
            "600001": False,
            "600002": True,
            "600003": False,
        })

    def test_qianlong_tdx_formula_matches_builtin_signal_and_factors(self) -> None:
        """用户原式与内置实现逐项一致，防止两条运行时链路漂移。"""
        panels = synthetic_panels(seed=20260731, rows=120, cols=6)
        # 回归测试比较的是用户原式；V3 显式放回原式的旧参数并放宽换手过滤。
        builtin = get("qianlong-close-v3").compute(
            panels,
            {
                "death_lookback": 20,
                "price_min": 6.0,
                "turnover_min": 0.0,
                "turnover_max": 1.0,
            },
        )
        formula_engine = build_formula_engine(
            {
                "slug": "qianlong-formula-regression",
                "name": "潜龙公式回归",
                "description": "用户提供的通达信原式",
                "formula": QIANLONG_TDX_FORMULA,
                "manifest": {
                    "schema_version": 1,
                    "entry_timing": "next_open",
                    "min_bars": 46,
                    "params": {},
                    "output": {"signal": "XG"},
                "factors": [
                    "YTSL", "白色线", "黄色线", "死叉", "曾死叉",
                    "白线下运行", "突破日", "白线向上", "非涨停价",
                ],
                },
            }
        )
        self.assertEqual(formula_engine.compiled.min_bars_required, 46)
        self.assertEqual(formula_engine.min_bars(), 46)
        formula = formula_engine.compute(panels)

        close, open_ = panels["close"], panels["open"]
        ytsl = (3 * close + panels["low"] + open_ + panels["high"]) / 6
        white = chenxing(panels)
        yellow = MA(close, 26)
        death = CROSS(yellow, white)
        had_death = EXIST(death, 20)
        ran_below = COUNT(close < white, 10) >= 3
        breakout_day = (
            (close > open_)
            & (close >= 6)
            & (close > white)
            & (REF(close, 1) <= REF(white, 1))
            & (panels["volume"] > MA(panels["volume"], 5) * 1.3)
            & (close > white * 1.002)
        )
        white_rising = white > REF(white, 1)
        non_limit_up = close < ZTPRICE(REF(close, 1), 0.1)
        expected = {
            "YTSL": ytsl,
            "白色线": white,
            "黄色线": yellow,
            "死叉": death,
            "曾死叉": had_death,
            "白线下运行": ran_below,
            "突破日": breakout_day,
            "白线向上": white_rising,
            "非涨停价": non_limit_up,
        }
        for name, expected_frame in expected.items():
            with self.subTest(factor=name):
                pd.testing.assert_frame_equal(
                    formula.factors[name], expected_frame, check_dtype=False
                )

        expected_signal = (
            had_death & ran_below & breakout_day & white_rising & non_limit_up
        ).fillna(False)
        pd.testing.assert_frame_equal(
            formula.signals.astype(bool), expected_signal.astype(bool), check_names=False
        )
        pd.testing.assert_frame_equal(
            formula.signals.astype(bool), builtin.signals.astype(bool), check_names=False
        )

    def test_qianlong_close_signal_requires_four_factors_and_not_limit_up(self) -> None:
        """XG = 四个形态条件 AND 收盘不在涨停价。"""
        panels = synthetic_panels(seed=21, rows=200, cols=30)
        result = get("qianlong-close-v3").compute(
            panels, {"turnover_min": 0.0, "turnover_max": 1.0}
        )
        for name in ("曾死叉", "白线下运行", "突破日", "白线向上"):
            self.assertIn(name, result.factors)
        all_four = (
            result.factors["曾死叉"].fillna(False).astype(bool)
            & result.factors["白线下运行"].fillna(False).astype(bool)
            & result.factors["突破日"].fillna(False).astype(bool)
            & result.factors["白线向上"].fillna(False).astype(bool)
            & result.factors["非涨停价"].fillna(False).astype(bool)
        )
        pd.testing.assert_frame_equal(
            result.signals.astype(bool),
            all_four.astype(bool),
            check_names=False,
        )

    def test_qianlong_v3_adds_turnover_filter_to_core(self) -> None:
        panels = synthetic_panels(seed=20260802, rows=200, cols=30)
        core = get("qianlong-close-v3").compute(
            panels, {"turnover_min": 0.0, "turnover_max": 1.0}
        ).signals.fillna(False).astype(bool)
        v3_result = get("qianlong-close-v3").compute(panels)
        turnover = panels["turnover"]
        turnover_ok = (turnover >= 0.02) & (turnover < 0.08)
        expected = core & turnover_ok
        pd.testing.assert_frame_equal(
            v3_result.signals.astype(bool), expected.astype(bool), check_names=False
        )
        self.assertIn("换手率(%)", v3_result.factors)
        self.assertIn("换手2%-8%", v3_result.factors)
        self.assertIn("ROC5", v3_result.factors)
        self.assertEqual(getattr(get("qianlong-close-v3"), "screen_rank_factor"), "ROC5")

    def test_qianlong_picks_on_sorts_by_roc5_descending(self) -> None:
        """选股输出按 ROC5 降序，最强排最前。"""
        from src.strategy.domain.base import SignalResult

        index = ["2026-07-01"]
        codes = ["600001", "600002", "600003"]
        signals = pd.DataFrame([[True, True, True]], index=index, columns=codes)
        roc5 = pd.DataFrame([[1.02, 1.15, 1.08]], index=index, columns=codes)
        result = SignalResult(signals=signals, factors={"ROC5": roc5})
        self.assertEqual(
            result.picks_on("2026-07-01", rank_by="ROC5"),
            ["600002", "600003", "600001"],
        )
        # 无 rank_by 时仍按代码序，兼容旧调用。
        self.assertEqual(result.picks_on("2026-07-01"), ["600001", "600002", "600003"])

    def test_qianlong_excludes_exact_limit_up_by_board(self) -> None:
        """主板 10% 与创业板 20% 涨停价都不得进入尾盘候选。"""
        index = pd.date_range("2026-01-01", periods=50, freq="B").strftime("%Y-%m-%d")
        close = pd.DataFrame(
            {
                "600001": [10.0] * 49 + [11.0],
                "300001": [10.0] * 49 + [12.0],
            },
            index=index,
        )
        panels = {
            "open": close * 0.99,
            "high": close,
            "low": close * 0.98,
            "close": close,
            "volume": pd.DataFrame(1_000_000.0, index=index, columns=close.columns),
            "turnover": pd.DataFrame(0.03, index=index, columns=close.columns),
        }

        result = get("qianlong-close-v3").compute(panels)

        self.assertFalse(bool(result.factors["非涨停价"].iloc[-1, 0]))
        self.assertFalse(bool(result.factors["非涨停价"].iloc[-1, 1]))

    def test_qianlong_limit_filter_uses_raw_close_when_indicator_is_qfq(self) -> None:
        """复权技术指标不能把真实未复权涨停价漏掉。"""
        index = pd.date_range("2026-01-01", periods=50, freq="B").strftime("%Y-%m-%d")
        close = pd.DataFrame({"600001": [10.0] * 49 + [10.5]}, index=index)
        raw_close = pd.DataFrame({"600001": [10.0] * 49 + [11.0]}, index=index)
        panels = {
            "open": close * 0.99,
            "high": close,
            "low": close * 0.98,
            "close": close,
            "volume": pd.DataFrame(1_000_000.0, index=index, columns=close.columns),
            "turnover": pd.DataFrame(0.03, index=index, columns=close.columns),
            "__raw_close": raw_close,
        }

        result = get("qianlong-close-v3").compute(panels)

        self.assertFalse(bool(result.factors["非涨停价"].iloc[-1, 0]))

    def test_loosening_thresholds_never_shrinks_the_pick_set(self) -> None:
        """单调性自检：把门槛放宽，选出的票只能更多不能更少。"""
        panels = synthetic_panels(seed=11, rows=200, cols=60)
        engine = get("qianlong-close-v3")
        strict = engine.compute(panels).signals.to_numpy().sum()
        loose = engine.compute(
            panels,
            {
                "death_lookback": 60,
                "below_window": 10,
                "below_min": 0,
                "price_min": 0.0,
                "vol_boost": 0.0,
                "hold_ratio": 0.5,
                "turnover_min": 0.0,
                "turnover_max": 1.0,
            },
        ).signals.to_numpy().sum()
        self.assertGreaterEqual(loose, strict)

    def test_optimized_variants_are_subsets_of_relaxed_signals(self) -> None:
        """收紧参数只能减少候选，不能悄悄引入另一套不可解释的候选。"""
        panels = synthetic_panels(seed=20260801, rows=220, cols=40)
        for slug, relaxed_params in (
            (
                "qianlong-close-v3",
                {
                    "death_lookback": 20,
                    "price_min": 0.0,
                    "turnover_min": 0.0,
                    "turnover_max": 1.0,
                },
            ),
        ):
            with self.subTest(strategy=slug):
                engine = get(slug)
                strict = engine.compute(panels).signals.fillna(False).astype(bool)
                relaxed = engine.compute(panels, relaxed_params).signals.fillna(False).astype(bool)
                self.assertFalse((strict & ~relaxed).any().any())


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

    def test_sanyuan_v2_applies_gate_after_top2_without_refilling(self) -> None:
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
        self.assertFalse(bool(result.signals.iloc[-1].any()))

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
