"""杨氏尾盘选股 V1 的闸门、排序与前视测试。

素材原文六条里有四条能落到本仓行情字段上，逐条都必须真的在起作用——否则「照抄素材」
就变成了「抄了个名字」。第 6 条（净资产收益率）本仓无财务数据，未实现，测试不覆盖。
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.strategy import StrategyError, get
from src.strategy.application.yangshi_tail import YangshiTailPickerV1

from tests.strategy.strategy_fixtures import synthetic_panels

CODES = ["600001", "600002", "600003", "600004", "600005"]
ROWS = 45


def _panels(
    *,
    last_close: list[float],
    shares_yi: list[float] | None = None,
    turnover: list[float] | None = None,
    prev_close: float = 10.0,
) -> dict[str, pd.DataFrame]:
    """构造一份「除最后一天外完全静止」的面板，只让最后一根 K 承载差异。

    前 44 天恒定在 ``prev_close``，因此最后一天的涨幅完全由 ``last_close`` 决定，
    闸门判定不受历史噪声干扰。
    """
    index = pd.date_range("2026-01-01", periods=ROWS, freq="B").strftime("%Y-%m-%d")
    close = pd.DataFrame(prev_close, index=index, columns=CODES, dtype=float)
    close.iloc[-1] = last_close
    open_ = pd.DataFrame(prev_close, index=index, columns=CODES, dtype=float)
    # 成交额 = close×volume 必须站上 3000 万的可交易底线，否则闸门在别处就把票挡了，
    # 单条闸门的测试会变成恒假通过。
    volume = pd.DataFrame(10_000_000.0, index=index, columns=CODES)
    # 默认股本 1 亿股：低于 2 亿股闸门，让默认路径能出信号。
    share_row = [1.0] * len(CODES) if shares_yi is None else shares_yi
    turn_row = [0.05] * len(CODES) if turnover is None else turnover
    return {
        "open": open_,
        # 高低价拉开，避免被一字判定误伤。
        "high": close * 1.05,
        "low": close * 0.95,
        "close": close,
        "volume": volume,
        "amount": close * volume,
        "turnover": pd.DataFrame(
            np.tile(turn_row, (ROWS, 1)), index=index, columns=CODES
        ),
        "outstanding_share": pd.DataFrame(
            np.tile(np.asarray(share_row) * 1e8, (ROWS, 1)), index=index, columns=CODES
        ),
    }


class MetadataTests(unittest.TestCase):
    def test_registered_with_next_open_entry(self) -> None:
        engine = get("yangshi-tail-v1")
        self.assertEqual(engine.slug, "yangshi-tail-v1")
        # 素材叫「尾盘选股法」，但买入必须在次日开盘——实测尾盘买每笔多付约 0.11pp。
        self.assertEqual(engine.entry_timing, "next_open")
        self.assertEqual(engine.screen_top_n, 1)
        self.assertEqual(engine.screen_hold_days, 2)
        self.assertEqual(engine.screen_rank_factor, "当日涨幅(%)")
        self.assertEqual(engine.screen_schedule["run_hour"], 15)
        self.assertEqual(engine.screen_schedule["run_minute"], 30)
        self.assertFalse(engine.screen_force_spot_refresh)

    def test_1450_variant_is_gone_for_good(self) -> None:
        """14:50 档已整体下线：注册表不认这个 slug，也不再挂任何定时。"""
        with self.assertRaises(StrategyError):
            get("yangshi-tail-1450")

    def test_source_gate_defaults_match_the_material(self) -> None:
        """闸门阈值必须与素材原文一致；调参会让「照抄素材」这个说法失效。"""
        params = YangshiTailPickerV1().default_params()
        self.assertEqual(params["shares_max"], 2e8)  # 原文「流通股本小于20000万股」
        self.assertEqual(params["price_max"], 12.0)  # 原文「现价小于12元」
        self.assertEqual(params["pct_chg_min"], 1.0)  # 原文「涨幅大于1%」
        self.assertEqual(params["pct_chg_max"], 5.0)  # 原文「涨幅小于5%」
        self.assertEqual(params["turnover_min"], 0.02)  # 原文「换手率大于2%」


class SourceGateTests(unittest.TestCase):
    """四条素材闸门逐条验证：每条都要能单独把一只票挡掉。"""

    def _last_row(self, panels: dict[str, pd.DataFrame], **params: object) -> list[bool]:
        merged = {"weak_breadth_skip": None, "top_n": 0, **params}
        result = YangshiTailPickerV1().compute(panels, merged)
        return result.signals.iloc[-1].tolist()

    def test_gain_band_excludes_both_ends(self) -> None:
        # 涨幅依次 0.5% / 1.5% / 3% / 5.5% / 8%，只有中间三只落在 (1%, 5%) 内。
        panels = _panels(last_close=[10.05, 10.15, 10.30, 10.55, 10.80])
        self.assertEqual(
            self._last_row(panels), [False, True, True, False, False]
        )

    def test_float_share_ceiling_excludes_large_caps(self) -> None:
        panels = _panels(
            last_close=[10.3] * 5, shares_yi=[0.5, 1.9, 2.0, 2.5, 9.0]
        )
        # 恰好 2 亿股不算「小于 2 亿股」，必须被挡。
        self.assertEqual(
            self._last_row(panels), [True, True, False, False, False]
        )

    def test_price_ceiling_uses_unadjusted_close(self) -> None:
        """「现价 < 12 元」是绝对价格，必须读未复权价而不是前复权价。"""
        panels = _panels(last_close=[10.3] * 5, prev_close=10.0)
        raw = panels["close"] * 3.0  # 前复权把价格压低了三倍的老票
        panels["__raw_close"] = raw
        self.assertEqual(self._last_row(panels), [False] * 5)

        panels["__raw_close"] = panels["close"]
        self.assertEqual(self._last_row(panels), [True] * 5)

    def test_turnover_floor_excludes_illiquid(self) -> None:
        panels = _panels(
            last_close=[10.3] * 5, turnover=[0.005, 0.02, 0.021, 0.08, 0.30]
        )
        # 恰好 2% 不算「大于 2%」。
        self.assertEqual(
            self._last_row(panels), [False, False, True, True, True]
        )

    def test_amount_floor_excludes_thin_trading(self) -> None:
        panels = _panels(last_close=[10.3] * 5)
        panels["amount"] = panels["amount"] * 0.0 + 1_000_000.0
        self.assertEqual(self._last_row(panels), [False] * 5)


class RankAndWeakMarketTests(unittest.TestCase):
    def test_top_one_goes_to_the_largest_gain_within_the_band(self) -> None:
        """排序在 1%~5% 窄带内做，取的是带内最靠上的一只，不是全市场追涨。"""
        panels = _panels(last_close=[10.15, 10.45, 10.25, 10.35, 10.11])
        result = YangshiTailPickerV1().compute(panels, {"weak_breadth_skip": None})
        picked = [
            code
            for code, flag in result.signals.iloc[-1].items()
            if bool(flag)
        ]
        # 涨幅 4.5%（600002）最大；3.5%（600004）是第二名，Top1 不取。
        self.assertEqual(picked, ["600002"])
        self.assertEqual(
            result.picks_on(panels["close"].index[-1], rank_by="当日涨幅(%)"),
            ["600002"],
        )

    def test_weak_market_demotes_everything_to_watch(self) -> None:
        """上涨家数 <40% 时正式信号清空，合格票降级为观察。"""
        # 五只里只有两只上涨（40% 不到？两只/五只 = 40%，恰好等于阈值→可交易）。
        # 这里让只有一只上涨，占比 20%，触发空仓。
        panels = _panels(last_close=[10.3, 9.0, 9.0, 9.0, 9.0])
        result = YangshiTailPickerV1().compute(panels)
        self.assertEqual(result.signals.iloc[-1].tolist(), [False] * 5)
        self.assertIsNotNone(result.watch_signals)
        assert result.watch_signals is not None
        self.assertEqual(
            result.watch_signals.iloc[-1].tolist(), [True, False, False, False, False]
        )

    def test_strong_market_keeps_formal_signals(self) -> None:
        panels = _panels(last_close=[10.3, 10.2, 10.4, 10.35, 9.0])
        result = YangshiTailPickerV1().compute(panels)
        self.assertTrue(bool(result.signals.iloc[-1].any()))
        assert result.watch_signals is not None
        self.assertFalse(bool(result.watch_signals.iloc[-1].any()))


def _wide_price_panels(seed: int, rows: int, cols: int) -> dict[str, pd.DataFrame]:
    """共享夹具的价格全部起于 20 元，「现价 <12 元」与「股本 <2 亿股」两组票不相交，
    交集恒为空——那样的前视测试是恒真通过，没有意义。

    这里按票缩放价格水平，让横截面覆盖约 4~30 元。只改本测试的输入，不动
    ``synthetic_panels`` 本身，避免扰动潜龙那几条依赖既有价格分布的回归断言。
    """
    panels = synthetic_panels(seed=seed, rows=rows, cols=cols)
    codes = panels["close"].columns
    scale = pd.Series(
        np.linspace(0.2, 1.5, len(codes)), index=codes, dtype=float
    )
    for field in ("open", "high", "low", "close"):
        panels[field] = panels[field].mul(scale, axis=1)
    panels["amount"] = panels["close"] * panels["volume"]
    return panels


class LookAheadTests(unittest.TestCase):
    def test_truncation_keeps_signals_identical_on_real_shaped_panels(self) -> None:
        """截断一致性：只喂到当天为止，当天的信号必须一模一样。

        用带真实信号的随机面板——恒等为假的信号通不过任何前视检验。
        """
        panels = _wide_price_panels(seed=20260812, rows=180, cols=60)
        engine = YangshiTailPickerV1()
        full = engine.compute(panels).signals
        self.assertTrue(bool(full.to_numpy().any()), "夹具没能造出任何信号，前视测试无意义")

        index = panels["close"].index
        for position in (len(index) - 1, len(index) - 7, len(index) - 30):
            cut_date = index[position]
            truncated = {
                field: panel.iloc[: position + 1] for field, panel in panels.items()
            }
            partial = engine.compute(truncated).signals
            pd.testing.assert_series_equal(
                full.loc[cut_date].astype(bool),
                partial.loc[cut_date].astype(bool),
                check_names=False,
                obj=f"{cut_date} 的信号依赖了未来数据",
            )


if __name__ == "__main__":
    unittest.main()
