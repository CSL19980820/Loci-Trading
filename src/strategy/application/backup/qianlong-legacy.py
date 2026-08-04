"""潜龙出海：把通达信云阳标准买点选股公式忠实翻译成向量化信号。

## 翻译中必须留神的两处

1. **辰星线的怪异构造。** 原式跳过 ``REF(YTSL,19)`` 却纳入 ``REF(YTSL,20)``，
   且分母 211 与权重和 210 不等。照抄，不"修正"——改它等于改策略。
2. **前视偏差。** 信号用到当日 CLOSE，只能次日开盘入场（``entry_timing=next_open``）。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import COUNT, CROSS, EXIST, MA, REF, weighted_ref_sum
from src.strategy.domain.base import SignalResult, merge_params, register

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


class QianlongCloseePicker:
    """潜龙出海·云阳标准买点（盘后选股）。

    通达信原式（突破日当日亮 XG，用到收盘，只能次日开盘入）::

        曾死叉:=EXIST(CROSS(黄色线,白色线),20);
        白线下运行:=COUNT(CLOSE<白色线,10)>=3;
        突破日:=(CLOSE>OPEN AND CLOSE>=6)
               AND (CLOSE>白色线 AND REF(CLOSE,1)<=REF(白色线,1))
               AND (VOL>MA(VOL,5)*1.3)
               AND (CLOSE>白色线*1.002);
        XG:曾死叉 AND 白线下运行 AND 突破日 AND 白线向上;
    """

    slug = "qianlong-close"
    name = "潜龙出海"
    description = "20日曾死叉 + 10日曾趴白线下 + 当日放量阳线突破站稳且白线向上，盘后选、次日开盘入"
    entry_timing = "next_open"

    def default_params(self) -> dict[str, Any]:
        return {
            "death_lookback": 20,   # EXIST(死叉, N)
            "below_window": 10,     # COUNT(CLOSE<白线, N)
            "below_min": 3,         # 窗口内至少几天收在白线下
            "price_min": 6.0,       # CLOSE>=6
            "vol_boost": 1.3,       # VOL > MA(VOL,5) * 倍数
            "hold_ratio": 1.002,    # CLOSE > 白线 * 比例
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        # 辰星线需要 21 根，黄色线需要 26 根；CROSS 还要比较前一根，
        # EXIST(死叉,20) 因此要到第 46 根才会得到首个完整值。
        return 46

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        close, open_ = panels["close"], panels["open"]
        volume = panels["volume"]

        white = chenxing(panels)              # 白色线 / 辰星线
        yellow = MA(close, 26)                # 黄色线 / 牵牛线

        death_cross = CROSS(yellow, white)    # 黄线上穿白线 = 死叉
        had_death = EXIST(death_cross, int(p["death_lookback"]))
        ran_below = COUNT(close < white, int(p["below_window"])) >= int(p["below_min"])

        bullish = (close > open_) & (close >= float(p["price_min"]))
        breakout = (close > white) & (REF(close, 1) <= REF(white, 1))
        volume_up = volume > MA(volume, 5) * float(p["vol_boost"])
        hold = close > white * float(p["hold_ratio"])
        breakout_day = bullish & breakout & volume_up & hold

        white_rising = white > REF(white, 1)

        signals = had_death & ran_below & breakout_day & white_rising

        return SignalResult(
            signals=signals.fillna(False),
            factors={
                "辰星线": white,
                "牵牛线": yellow,
                "曾死叉": had_death,
                "白线下运行": ran_below,
                "突破日": breakout_day,
                "白线向上": white_rising,
            },
        )


class QianlongCloseePickerV2(QianlongCloseePicker):
    """潜龙出海选股优化版，保留原版 ``qianlong-close`` 作为对照。"""

    slug = "qianlong-close-v2"
    name = "潜龙出海（优化版）"
    description = "潜龙 V2：15 日内曾死叉且收盘价不低于 8 元，其他条件沿用原式"

    def default_params(self) -> dict[str, Any]:
        return {
            **super().default_params(),
            "death_lookback": 15,
            "price_min": 8.0,
        }


register(QianlongCloseePicker())
register(QianlongCloseePickerV2())
