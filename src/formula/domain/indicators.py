"""常用技术指标的向量化实现。

这些函数只负责数值计算，不负责行情加载或信号裁决。Series 与 DataFrame
共用同一条路径，保证单票调试结果可以直接推广到全市场面板。
"""
from __future__ import annotations

from typing import TypeAlias

import numpy as np
import pandas as pd

from src.formula.domain.functions import (
    ABS,
    AVEDEV,
    EMA,
    HHV,
    LLV,
    MA,
    MAX,
    REF,
    SMA,
    STD,
)

Frame: TypeAlias = pd.Series | pd.DataFrame

__all__ = [
    "ATR",
    "BOLL_LOWER",
    "BOLL_MID",
    "BOLL_UPPER",
    "CCI",
    "MACD",
    "MACD_DEA",
    "MACD_DIF",
    "OBV",
    "ROC",
    "RSI",
    "TR",
    "WR",
]


def _require_period(periods: int, name: str) -> int:
    if isinstance(periods, bool) or not isinstance(periods, int) or periods <= 0:
        raise ValueError(f"{name} 的周期必须是正整数")
    return periods


def _valid_prefix(source: Frame, minimum: int) -> Frame:
    valid = source.notna().cumsum(axis=0)
    return valid >= minimum


def _mask_prefix(result: Frame, source: Frame, minimum: int) -> Frame:
    return result.where(_valid_prefix(source, minimum))


def _safe_divide(numerator: Frame, denominator: Frame, fallback: float | None = None) -> Frame:
    with np.errstate(divide="ignore", invalid="ignore"):
        result = numerator / denominator
    if fallback is not None:
        result = result.where(denominator != 0, fallback)
    return result


def TR(high: Frame, low: Frame, close: Frame) -> Frame:
    """TR(HIGH, LOW, CLOSE)：真实波幅。首根因缺少昨收而为空。"""
    previous_close = REF(close, 1)
    return MAX(high - low, MAX(ABS(high - previous_close), ABS(low - previous_close)))


def ATR(high: Frame, low: Frame, close: Frame, periods: int) -> Frame:
    """ATR(HIGH, LOW, CLOSE, N)：N 周期真实波幅均值。"""
    periods = _require_period(periods, "ATR")
    return MA(TR(high, low, close), periods)


def RSI(series: Frame, periods: int = 14) -> Frame:
    """RSI(X, N)：按通达信 SMA 递推口径计算的相对强弱指标（0-100）。"""
    periods = _require_period(periods, "RSI")
    delta = series - REF(series, 1)
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    average_gain = SMA(gain, periods, 1.0)
    average_loss = SMA(loss, periods, 1.0)
    total = average_gain + average_loss
    result = _safe_divide(average_gain * 100.0, total, fallback=50.0)
    return _mask_prefix(result, series, periods + 1)


def ROC(series: Frame, periods: int) -> Frame:
    """ROC(X, N)：N 周期价格变化率，单位为百分比。"""
    periods = _require_period(periods, "ROC")
    previous = REF(series, periods)
    return _safe_divide(series - previous, previous) * 100.0


def WR(high: Frame, low: Frame, close: Frame, periods: int) -> Frame:
    """WR(HIGH, LOW, CLOSE, N)：威廉指标，返回 -100 到 0。"""
    periods = _require_period(periods, "WR")
    highest = HHV(high, periods)
    lowest = LLV(low, periods)
    return _safe_divide((highest - close) * -100.0, highest - lowest, fallback=0.0)


def CCI(high: Frame, low: Frame, close: Frame, periods: int) -> Frame:
    """CCI(HIGH, LOW, CLOSE, N)：典型价格商品通道指标。"""
    periods = _require_period(periods, "CCI")
    typical = (high + low + close) / 3.0
    mean = MA(typical, periods)
    deviation = AVEDEV(typical, periods)
    return _safe_divide(typical - mean, deviation * 0.015, fallback=0.0)


def OBV(close: Frame, volume: Frame) -> Frame:
    """OBV(CLOSE, VOL)：按收盘涨跌方向累计成交量。"""
    change = close - REF(close, 1)
    direction = change.gt(0).astype(float) - change.lt(0).astype(float)
    valid = close.notna() & volume.notna()
    result = (volume.where(valid, 0.0) * direction.where(valid, 0.0)).cumsum(axis=0)
    return result.where(valid)


def MACD_DIF(close: Frame, fast: int = 12, slow: int = 26) -> Frame:
    """MACD_DIF(CLOSE, FAST, SLOW)：快慢 EMA 差值。"""
    fast = _require_period(fast, "MACD fast")
    slow = _require_period(slow, "MACD slow")
    if fast >= slow:
        raise ValueError("MACD fast 必须小于 slow")
    return EMA(close, fast) - EMA(close, slow)


def MACD_DEA(close: Frame, fast: int = 12, slow: int = 26, signal: int = 9) -> Frame:
    """MACD_DEA(CLOSE, FAST, SLOW, SIGNAL)：DIF 的信号线。"""
    signal = _require_period(signal, "MACD signal")
    return EMA(MACD_DIF(close, fast, slow), signal)


def MACD(close: Frame, fast: int = 12, slow: int = 26, signal: int = 9) -> Frame:
    """MACD(CLOSE, FAST, SLOW, SIGNAL)：(DIF-DEA)*2 柱值。"""
    dif = MACD_DIF(close, fast, slow)
    dea = EMA(dif, _require_period(signal, "MACD signal"))
    return (dif - dea) * 2.0


def BOLL_MID(series: Frame, periods: int) -> Frame:
    """BOLL_MID(X, N)：布林中轨。"""
    return MA(series, _require_period(periods, "BOLL"))


def BOLL_UPPER(series: Frame, periods: int, deviations: float = 2.0) -> Frame:
    """BOLL_UPPER(X, N, K)：布林上轨。"""
    periods = _require_period(periods, "BOLL")
    return MA(series, periods) + STD(series, periods) * float(deviations)


def BOLL_LOWER(series: Frame, periods: int, deviations: float = 2.0) -> Frame:
    """BOLL_LOWER(X, N, K)：布林下轨。"""
    periods = _require_period(periods, "BOLL")
    return MA(series, periods) - STD(series, periods) * float(deviations)
