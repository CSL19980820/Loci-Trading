"""通达信公式的向量化实现。

## 为什么要单独做一层

通达信选全市场只要几秒，我们逐票跑 pandas 要几十分钟。差距不在语言，
在**形状**：通达信是 C 引擎逐票循环，而我们可以把全市场组织成一张
``DataFrame(index=交易日, columns=股票代码)`` 的面板，让 ``REF`` 变成
``shift``、``MA`` 变成 ``rolling.mean``——一次调用覆盖几千只票，走的是
pandas/numpy 的 C 路径，反而比逐票循环更快。

本模块所有函数对**面板 DataFrame 和单票 Series 一视同仁**：同一份实现，
既能全市场扫描，也能单票调试，不需要两套代码。

## 口径

函数语义对齐通达信，包括那些看起来别扭的地方（``MA`` 不足周期返回空值、
``SUM(X,0)`` 表示从头累计、``BARSLAST`` 当日成立时为 0）。翻译层不"修正"
原语义——那属于改策略，必须显式决策。
"""
from src.formula.board import (
    limit_ratio_for,
    limit_ratio_panel,
    limit_up_flags,
    one_word_flags,
)
from src.formula.chips import COST, WINNER, chip_cost_series, chip_winner_series
from src.formula.functions import (
    ABS,
    AVEDEV,
    BARSCOUNT,
    BARSLAST,
    BARSSINCE,
    COUNT,
    CROSS,
    DMA,
    EMA,
    EVERY,
    EXIST,
    FILTER,
    HHV,
    HHVBARS,
    IF,
    LLV,
    LLVBARS,
    MA,
    MAX,
    MIN,
    REF,
    SMA,
    STD,
    SUM,
    WMA,
    ZTPRICE,
    weighted_ref_sum,
)

__all__ = [
    "ABS",
    "COST",
    "WINNER",
    "chip_cost_series",
    "chip_winner_series",
    "limit_ratio_for",
    "limit_ratio_panel",
    "limit_up_flags",
    "one_word_flags",
    "AVEDEV",
    "BARSCOUNT",
    "BARSLAST",
    "BARSSINCE",
    "COUNT",
    "CROSS",
    "DMA",
    "EMA",
    "EVERY",
    "EXIST",
    "FILTER",
    "HHV",
    "HHVBARS",
    "IF",
    "LLV",
    "LLVBARS",
    "MA",
    "MAX",
    "MIN",
    "REF",
    "SMA",
    "STD",
    "SUM",
    "WMA",
    "ZTPRICE",
    "weighted_ref_sum",
]
