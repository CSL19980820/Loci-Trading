"""Screen Formula 已绑定调用的向量化函数分派。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.formula.domain.indicators import (
    ATR,
    BOLL_LOWER,
    BOLL_MID,
    BOLL_UPPER,
    CCI,
    MACD,
    MACD_DEA,
    MACD_DIF,
    OBV,
    ROC,
    RSI,
    TR,
    WR,
)
from src.formula.domain.functions import (
    ABS, AVEDEV, BARSCOUNT, BARSLAST, BARSSINCE, COUNT, CROSS, DMA, EMA,
    EVERY, EXIST, FILTER, HHV, HHVBARS, IF, LLV, LLVBARS, MA, MAX, MIN,
    REF, SMA, STD, SUM, WMA, ZTPRICE,
)


def apply_formula_call(
    name: str,
    values: tuple[Any, ...],
    truthy: Callable[[Any], Any],
) -> Any:
    if name == "REF": return REF(values[0], int(values[1]))
    if name == "MA": return MA(values[0], int(values[1]))
    if name == "EMA": return EMA(values[0], int(values[1]))
    if name == "SMA": return SMA(values[0], int(values[1]), float(values[2]))
    if name == "WMA": return WMA(values[0], int(values[1]))
    if name == "DMA": return DMA(values[0], values[1])
    if name == "SUM": return SUM(values[0], int(values[1]))
    if name == "HHV": return HHV(values[0], int(values[1]))
    if name == "LLV": return LLV(values[0], int(values[1]))
    if name == "STD": return STD(values[0], int(values[1]))
    if name == "AVEDEV": return AVEDEV(values[0], int(values[1]))
    if name == "COUNT": return COUNT(truthy(values[0]), int(values[1]))
    if name == "EVERY": return EVERY(truthy(values[0]), int(values[1]))
    if name == "EXIST": return EXIST(truthy(values[0]), int(values[1]))
    if name == "FILTER": return FILTER(truthy(values[0]), int(values[1]))
    if name == "BARSLAST": return BARSLAST(truthy(values[0]))
    if name == "BARSSINCE": return BARSSINCE(truthy(values[0]))
    if name == "BARSCOUNT": return BARSCOUNT(values[0])
    if name == "HHVBARS": return HHVBARS(values[0], int(values[1]))
    if name == "LLVBARS": return LLVBARS(values[0], int(values[1]))
    if name == "IF": return IF(truthy(values[0]), values[1], values[2])
    if name == "ABS": return ABS(values[0])
    if name == "MAX": return MAX(values[0], values[1])
    if name == "MIN": return MIN(values[0], values[1])
    if name == "CROSS": return CROSS(values[0], values[1])
    if name == "ZTPRICE": return ZTPRICE(values[0], float(values[1]))
    if name == "TR": return TR(values[0], values[1], values[2])
    if name == "ATR": return ATR(values[0], values[1], values[2], int(values[3]))
    if name == "RSI": return RSI(values[0], int(values[1]))
    if name == "ROC": return ROC(values[0], int(values[1]))
    if name == "WR": return WR(values[0], values[1], values[2], int(values[3]))
    if name == "CCI": return CCI(values[0], values[1], values[2], int(values[3]))
    if name == "OBV": return OBV(values[0], values[1])
    if name == "MACD_DIF": return MACD_DIF(values[0], int(values[1]), int(values[2]))
    if name == "MACD_DEA": return MACD_DEA(values[0], int(values[1]), int(values[2]), int(values[3]))
    if name == "MACD": return MACD(values[0], int(values[1]), int(values[2]), int(values[3]))
    if name == "BOLL_MID": return BOLL_MID(values[0], int(values[1]))
    if name == "BOLL_UPPER": return BOLL_UPPER(values[0], int(values[1]), float(values[2]))
    if name == "BOLL_LOWER": return BOLL_LOWER(values[0], int(values[1]), float(values[2]))
    raise AssertionError(f"unknown function {name}")
