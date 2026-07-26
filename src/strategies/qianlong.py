"""潜龙出海：把通达信选股公式忠实翻译成向量化信号。

源公式：``tdx/潜龙出海_选股.txt``（9:25 竞价版）与 ``tdx/潜龙出海_选股_原版.txt``
（盘后收盘宽松版）。两者形态条件相近但**入场时点完全不同**，因此注册成
两个独立策略，而不是一个策略加个开关——混用会让回测结论失真。

## 翻译中必须留神的三处

1. **换手率单位。** 通达信的 ``HSL`` 是百分数（5 表示 5%），而行情仓里
   ``turnover`` 存的是新浪口径的小数（0.05 表示 5%）。公式里"昨换手>=5"
   若直接拿小数比，等于要求 500% 换手，永远选不出票。这里统一乘 100。
2. **辰星线的怪异构造。** 原式跳过 ``REF(YTSL,19)`` 却纳入 ``REF(YTSL,20)``，
   且分母 211 与权重和 210 不等。照抄，不"修正"——改它等于改策略。
3. **前视偏差。** 9:25 版用到当日 OPEN，这在集合竞价结束时是已知的，
   所以入场记为当日开盘；原版用到当日 CLOSE/LOW，只能次日开盘入场。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import ABS, BARSLAST, COUNT, MA, REF, weighted_ref_sum
from src.strategies.base import SignalResult, StrategyEngine, merge_params, register

#: 辰星线权重表：{REF 偏移: 权重}。offset 19 缺席是原式如此，不是笔误。
CHENXING_WEIGHTS: dict[int, float] = {offset: float(20 - offset) for offset in range(19)}
CHENXING_WEIGHTS[20] = 1.0
CHENXING_DIVISOR = 211.0


def ytsl(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """YTSL := (3*CLOSE + LOW + OPEN + HIGH) / 6"""
    return (3 * panels["close"] + panels["low"] + panels["open"] + panels["high"]) / 6


def chenxing(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """辰星线：当期权重最大的加权均线，照抄原式的跳项与分母。"""
    return weighted_ref_sum(ytsl(panels), CHENXING_WEIGHTS, CHENXING_DIVISOR)


def turnover_pct(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """把行情仓的小数换手率换算成通达信 HSL 的百分数口径。"""
    return panels["turnover"] * 100.0


class QianlongAuctionPicker:
    """潜龙出海·9:25 竞价版（tdx/潜龙出海_选股.txt）。

    逻辑主线：昨日首次突破辰星线且形态干净（阳线、收在上沿、有振幅有实体、
    不是横盘织布），量能换手落在特定区间，今日平开或小幅高开且不破辰星线。
    """

    slug = "qianlong-auction"
    name = "潜龙出海·竞价版"
    description = "昨日首破辰星线 + 量能换手区间 + 今日竞价不破线，9:25 可执行"
    entry_timing = "open"

    def default_params(self) -> dict[str, Any]:
        return {
            "gain_min": 2.0,          # 昨日涨幅下限（%）
            "gain_max": 8.0,          # 昨日涨幅上限（%）
            "amplitude_min": 4.0,     # 昨日振幅下限（%），过滤横盘织布
            "body_min": 2.0,          # 昨日实体下限（%）
            "close_upper_ratio": 0.35,  # 昨收须落在昨日区间上沿 35% 内
            "narrow_max": 2,          # 近 5 日窄幅天数上限
            "vol_ratio_min": 1.5,     # 昨日量比下限
            "vol_ratio_max": 3.5,     # 昨日量比上限
            "turnover_min": 5.0,      # 昨日换手下限（%）
            "turnover_max": 10.0,     # 昨日换手上限（%）
            "turnover_vs_ma5": 1.2,   # 昨换手须高于 5 日均换手的倍数
            "turnover_x_volratio_min": 9.0,  # 换手×量比的合力下限
            "breakout_count_max": 2,  # 近 12 日突破次数上限，排除反复假突破
            "open_low_ratio": 0.999,  # 今开不低于昨收的比例
            "open_high_ratio": 1.03,  # 今开不高于昨收的比例
            "open_vs_chenxing": 1.001,  # 今开须站在辰星线之上的比例
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume", "turnover")

    def min_bars(self) -> int:
        # 辰星线要 21 根，再往前 REF 2 根，量能要 5 日均再 REF 1 根，
        # COUNT(...,12) 要 12 根；留足余量避免边界上算出半截指标。
        return 40

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        close, open_, high, low = panels["close"], panels["open"], panels["high"], panels["low"]
        volume = panels["volume"]
        hsl = turnover_pct(panels)

        white = chenxing(panels)              # 辰星线
        yellow = MA(close, 26)                # 牵牛线

        prev_close, prev_open = REF(close, 1), REF(open_, 1)
        prev_high, prev_low = REF(high, 1), REF(low, 1)
        prev_white, prev_yellow = REF(white, 1), REF(yellow, 1)
        before_close, before_white = REF(close, 2), REF(white, 2)

        # 当日突破：收盘上穿辰星线且收阳
        breakout = (close > white) & (REF(close, 1) <= REF(white, 1)) & (close > open_)

        prev_gain = (prev_close - before_close) / before_close * 100
        shape_ok = (
            REF(breakout, 1).fillna(False).astype(bool)
            & (BARSLAST(breakout) == 1)
            & (prev_close > prev_white)
            & (before_close <= before_white)
            & (prev_close > prev_open)
            & (prev_close > prev_white)
            & (prev_close > prev_yellow)
            & (prev_gain >= p["gain_min"])
            & (prev_gain <= p["gain_max"])
        )

        prev_amplitude = (prev_high - prev_low) / prev_close * 100
        prev_body = ABS(prev_close - prev_open) / prev_close * 100
        close_near_high = prev_close >= prev_high - (prev_high - prev_low) * p["close_upper_ratio"]
        narrow_days = COUNT((REF(high, 1) - REF(low, 1)) / REF(close, 1) * 100 < 3, 5)
        not_choppy = (
            (prev_amplitude >= p["amplitude_min"])
            & (prev_body >= p["body_min"])
            & close_near_high
            & (narrow_days <= p["narrow_max"])
        )

        prev_vol_ratio = REF(volume, 1) / REF(MA(volume, 5), 1)
        prev_hsl = REF(hsl, 1)
        hsl_ma5 = REF(MA(hsl, 5), 1)
        volume_ok = (
            (prev_vol_ratio >= p["vol_ratio_min"])
            & (prev_vol_ratio <= p["vol_ratio_max"])
            & (prev_hsl >= p["turnover_min"])
            & (prev_hsl <= p["turnover_max"])
            & (prev_hsl >= hsl_ma5 * p["turnover_vs_ma5"])
            & (prev_hsl * prev_vol_ratio >= p["turnover_x_volratio_min"])
            & (COUNT(breakout, 12) <= p["breakout_count_max"])
        )

        open_ok = (open_ >= prev_close * p["open_low_ratio"]) & (
            open_ <= prev_close * p["open_high_ratio"]
        )
        open_above_white = open_ >= prev_white * p["open_vs_chenxing"]
        tradable = high > low  # 一字板买不进，排除

        signals = shape_ok & not_choppy & volume_ok & open_ok & open_above_white & tradable

        return SignalResult(
            signals=signals.fillna(False),
            factors={
                "辰星线": white,
                "牵牛线": yellow,
                "昨涨幅": prev_gain,
                "昨振幅": prev_amplitude,
                "昨实体": prev_body,
                "昨量比": prev_vol_ratio,
                "昨换手": prev_hsl,
                "近5窄幅": narrow_days,
                "形态OK": shape_ok,
                "非织布": not_choppy,
                "量能OK": volume_ok,
                "竞价OK": open_ok & open_above_white,
            },
        )


class QianlongCloseePicker:
    """潜龙出海·原版（盘后收盘宽松，tdx/潜龙出海_选股_原版.txt）。

    条件比竞价版松：只要昨日放量阳线首破辰星线并站稳，今日平开/高开、
    不破线、白线向上即可。因为用到当日收盘与最低价，只能次日开盘入场。
    """

    slug = "qianlong-close"
    name = "潜龙出海·原版"
    description = "昨日放量突破并站稳 + 今日不破辰星线且白线向上，盘后选、次日开盘入"
    entry_timing = "next_open"

    def default_params(self) -> dict[str, Any]:
        return {
            "vol_boost": 1.2,        # 昨量须高于 5 日均量的倍数
            "hold_ratio": 1.001,     # 昨收站稳辰星线的比例
            "open_low_ratio": 0.995,
            "open_high_ratio": 1.06,
            "low_vs_white": 0.997,   # 今日最低不破辰星线的比例
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 30

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        close, open_, high, low = panels["close"], panels["open"], panels["high"], panels["low"]
        volume = panels["volume"]

        white = chenxing(panels)

        prev_bullish = REF(close, 1) > REF(open_, 1)
        prev_breakout = (REF(close, 1) > REF(white, 1)) & (REF(close, 2) <= REF(white, 2))
        prev_volume_up = REF(volume, 1) > REF(MA(volume, 5), 1) * p["vol_boost"]
        prev_hold = REF(close, 1) >= REF(white, 1) * p["hold_ratio"]
        broke_yesterday = prev_bullish & prev_breakout & prev_volume_up & prev_hold

        open_ok = (open_ >= REF(close, 1) * p["open_low_ratio"]) & (
            open_ <= REF(close, 1) * p["open_high_ratio"]
        )
        holds_white = (low >= white * p["low_vs_white"]) & (close >= white)
        white_rising = white >= REF(white, 1)
        tradable = high > low

        signals = broke_yesterday & open_ok & holds_white & white_rising & tradable

        return SignalResult(
            signals=signals.fillna(False),
            factors={
                "辰星线": white,
                "昨日突破": broke_yesterday,
                "今开合理": open_ok,
                "守住白线": holds_white,
                "白线向上": white_rising,
            },
        )


register(QianlongAuctionPicker())
register(QianlongCloseePicker())
