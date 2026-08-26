"""战法注册表：目录、参数合并、公式引擎装配与错误契约。

从 `test_strategies.py` 拆出——该文件原本 674 行，其中本类独占 353 行。
合成行情夹具见 `strategy_fixtures.py`。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.formula import COUNT, CROSS, EXIST, MA, REF, ZTPRICE
from src.strategy import all_strategies, describe_all, get, merge_params
from src.strategy.application.qianlong import (
    QianlongCloseePickerV3,
    _QianlongCore,
    chenxing,
    select_one_per_day,
)
from src.strategy.application.screen_formula import build_formula_engine
from src.strategy.domain.base import SignalResult, StrategyError

from tests.strategy.strategy_fixtures import QIANLONG_TDX_FORMULA, synthetic_panels


class RegistryTests(unittest.TestCase):
    def test_lookup_and_metadata(self) -> None:
        engine = get("qianlong-close-v3")
        self.assertEqual(engine.slug, "qianlong-close-v3")
        self.assertEqual(engine.name, "潜龙出海（V3.2）")
        described = {item["slug"]: item for item in describe_all()}
        self.assertEqual(
            set(described),
            {
                "qianlong-close-v3",
                "sanyuan-tail-v1",
                "yangshi-tail-v1",
            },
        )
        self.assertNotIn("qianfu-close", described)
        self.assertNotIn("qianfu-1450", described)
        self.assertNotIn("sanyuan-tail-1450", described)
        self.assertNotIn("yangshi-tail-1450", described)
        self.assertNotIn("qianlong-tail-v1", described)
        self.assertNotIn("rsi30-dip", described)
        self.assertNotIn("sanyuan-tail-v2", described)
        self.assertNotIn("qianlong-close", described)
        self.assertNotIn("qianlong-close-v2", described)
        with self.assertRaises(StrategyError):
            get("qianfu-close")
        with self.assertRaises(StrategyError):
            get("qianfu-1450")
        with self.assertRaises(StrategyError):
            get("sanyuan-tail-1450")
        with self.assertRaises(StrategyError):
            get("yangshi-tail-1450")
        with self.assertRaises(StrategyError):
            get("qianlong-close-v2")
        with self.assertRaises(StrategyError):
            get("qianlong-tail-v1")
        with self.assertRaises(StrategyError):
            get("rsi30-dip")
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
        self.assertEqual(described["qianlong-close-v3"]["params"]["turnover_min"], 0.035)
        self.assertEqual(described["qianlong-close-v3"]["params"]["turnover_max"], 0.08)
        self.assertEqual(described["qianlong-close-v3"]["params"]["weak_breadth_skip"], 0.45)
        self.assertEqual(described["qianlong-close-v3"]["params"]["top_n"], 2)
        self.assertEqual(described["qianlong-close-v3"]["version"], "v3.2")
        self.assertIn("T+1", described["qianlong-close-v3"]["entry_instructions"])
        sanyuan = described["sanyuan-tail-v1"]
        self.assertIn("T+2 收盘卖出", sanyuan["entry_instructions"])
        self.assertEqual(sanyuan["entry_timing"], "next_open")
        self.assertIn("turnover", sanyuan["required_fields"])
        self.assertEqual(sanyuan["params"]["price_min"], 6.0)
        self.assertEqual(sanyuan["version"], "v2.6")
        self.assertIn("未复权收盘价≥6 元", sanyuan["entry_instructions"])
        self.assertEqual(described["yangshi-tail-v1"]["name"], "杨氏尾盘选股（15:30）")
        self.assertEqual(
            sanyuan["default_universe"],
            {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        )
        for key in (
            "trades",
            "win_rate",
            "completed_trades",
        ):
            self.assertIn(key, sanyuan["backtest_metrics"])

    def test_registered_strategy_window_contracts_are_explicit(self) -> None:
        expected = {
            "qianlong-close-v3": 46,
            "sanyuan-tail-v1": 25,
            # 只需前一根算涨幅，40 根是为了挡掉上市不足约两个月的次新。
            "yangshi-tail-v1": 40,
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
        """V3.2：核心突破 + 换手 3.5%–8% + 弱市空仓 + 白线贴近度 Top2。"""
        engine = get("qianlong-close-v3")
        params = engine.default_params()
        self.assertEqual(params["death_lookback"], 15)
        self.assertEqual(params["below_window"], 10)
        self.assertEqual(params["below_min"], 3)
        self.assertEqual(params["price_min"], 8.0)
        self.assertEqual(params["vol_boost"], 1.3)
        self.assertEqual(params["hold_ratio"], 1.002)
        self.assertEqual(params["turnover_min"], 0.035)
        self.assertEqual(params["turnover_max"], 0.08)
        self.assertEqual(params["weak_breadth_skip"], 0.45)
        self.assertEqual(params["top_n"], 2)
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
        """核心 XG = 四个形态条件 AND 收盘不在涨停价（关掉换手/宽度/TopN 后验）。"""
        panels = synthetic_panels(seed=21, rows=200, cols=30)
        result = get("qianlong-close-v3").compute(
            panels,
            {
                "turnover_min": 0.0,
                "turnover_max": 1.0,
                "weak_breadth_skip": None,
                "top_n": 0,
            },
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
        isolate = {"weak_breadth_skip": None, "top_n": 0}
        core = get("qianlong-close-v3").compute(
            panels, {**isolate, "turnover_min": 0.0, "turnover_max": 1.0}
        ).signals.fillna(False).astype(bool)
        v3_result = get("qianlong-close-v3").compute(panels, isolate)
        turnover = panels["turnover"]
        turnover_ok = (turnover >= 0.035) & (turnover < 0.08)
        expected = core & turnover_ok
        pd.testing.assert_frame_equal(
            v3_result.signals.astype(bool), expected.astype(bool), check_names=False
        )
        self.assertIn("换手率(%)", v3_result.factors)
        self.assertIn("换手过滤", v3_result.factors)
        self.assertIn("ROC5", v3_result.factors)
        self.assertIn("白线贴近度", v3_result.factors)
        self.assertIn("辰星线延伸", v3_result.factors)
        self.assertEqual(getattr(get("qianlong-close-v3"), "screen_rank_factor"), "白线贴近度")

    def test_qianlong_top2_prefers_closest_to_chenxing_not_highest_roc5(self) -> None:
        """过闸三只时取最贴近辰星线的两只，即使 ROC5 最强的是另一只。"""
        index = pd.date_range("2026-08-04", periods=6, freq="B").strftime("%Y-%m-%d")
        codes = ["600001", "600002", "600003"]
        close = pd.DataFrame(10.0, index=index, columns=codes)
        close.iloc[-1] = [11.0, 11.2, 11.1]
        turnover = pd.DataFrame(0.05, index=index, columns=codes)
        core_signals = pd.DataFrame(False, index=index, columns=codes)
        core_signals.iloc[-1] = True
        roc5 = pd.DataFrame(np.nan, index=index, columns=codes)
        roc5.iloc[-1] = [1.30, 1.10, 1.20]
        closeness = pd.DataFrame(np.nan, index=index, columns=codes)
        closeness.iloc[-1] = [0.90, 0.995, 0.97]
        core = SignalResult(
            signals=core_signals,
            factors={"ROC5": roc5, "白线贴近度": closeness},
        )

        with patch.object(_QianlongCore, "compute", return_value=core):
            result = QianlongCloseePickerV3().compute(
                {"close": close, "turnover": turnover}
            )

        self.assertEqual(result.signals.iloc[-1].tolist(), [False, True, True])

    def test_qianlong_picks_on_sorts_by_chenxing_closeness_descending(self) -> None:
        """选股输出按白线贴近度降序，刚站上白线的排最前。"""
        index = ["2026-07-01"]
        codes = ["600001", "600002", "600003"]
        signals = pd.DataFrame([[True, True, True]], index=index, columns=codes)
        closeness = pd.DataFrame([[0.90, 0.995, 0.97]], index=index, columns=codes)
        result = SignalResult(signals=signals, factors={"白线贴近度": closeness})
        self.assertEqual(
            result.picks_on("2026-07-01", rank_by="白线贴近度"),
            ["600002", "600003", "600001"],
        )
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
