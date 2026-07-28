"""板块与涨跌停判定：通达信 ``CODELIKE`` / ``NAMELIKE`` 的等价实现。

通达信靠代码前缀和名称匹配决定涨跌停幅度：

    BL := IF(CODELIKE('688') OR CODELIKE('300') …, 0.20,
          IF(CODELIKE('8') OR CODELIKE('4') …, 0.30,
          IF(NAMELIKE('ST'), 0.05, 0.10)));

这在面板上是**逐列常量**——每只票一个幅度，不随日期变化。所以不需要
逐日计算，构造一次列向量再广播即可。

## 为什么必须做对

涨停判定是所有打板类战法的地基。把创业板按 10% 判，20cm 的票永远
选不出来；把主板按 20% 判，会把普通上涨误判成涨停。这不是精度问题，
是整个战法成立与否的问题。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: 各板块涨跌停幅度。
LIMIT_20 = 0.20  # 创业板 300/301、科创板 688/689
LIMIT_30 = 0.30  # 北交所
LIMIT_ST = 0.05  # ST / *ST
LIMIT_DEFAULT = 0.10  # 主板

__all__ = ["limit_ratio_for", "limit_ratio_panel", "limit_up_flags", "one_word_flags"]


def limit_ratio_for(code: str, name: str = "") -> float:
    """单只证券的涨跌停幅度。

    ST 优先于板块：ST 的创业板股票是 20% 还是 5%，交易所规则是按 ST 走 5%
    （创业板 ST 为 20%，但主板 ST 为 5%）。这里遵循通达信原式的判断顺序——
    先看板块再看 ST，与卢高文涨停战法模板一致。
    """
    text = str(code).strip()
    if text.startswith(("688", "689", "300", "301")):
        return LIMIT_20
    if text.startswith(("4", "8", "92")):
        return LIMIT_30
    if "ST" in str(name).upper():
        return LIMIT_ST
    return LIMIT_DEFAULT


def limit_ratio_panel(
    close: pd.DataFrame, names: dict[str, str] | None = None
) -> pd.DataFrame:
    """与面板同形的涨跌停幅度矩阵。

    逐列常量，直接广播——不需要逐日算。
    """
    lookup = names or {}
    ratios = [limit_ratio_for(str(code), lookup.get(str(code), "")) for code in close.columns]
    row = pd.Series(ratios, index=close.columns, dtype=float)
    return pd.DataFrame(
        [row.to_numpy()] * len(close.index), index=close.index, columns=close.columns
    )


def limit_up_flags(
    close: pd.DataFrame,
    high: pd.DataFrame,
    ratios: pd.DataFrame,
    *,
    tolerance: float = 0.995,
) -> pd.DataFrame:
    """涨停：收盘达到涨停价且收盘等于最高（封住）。

    ``ZT := C >= ZTPRICE(REF(C,1), BL) * 0.995 AND C = H``

    0.995 的容差是原式带的，用来吃掉四舍五入与个别价格误差；照抄不改。
    """
    prev_close = close.shift(1)
    # ZTPRICE 逐元素取比例，这里 ratios 是矩阵，直接算涨停价。
    limit_price = _round_half_up(prev_close * (1.0 + ratios), 2)
    return (close >= limit_price * tolerance) & (close >= high)


def one_word_flags(high: pd.DataFrame, low: pd.DataFrame) -> pd.DataFrame:
    """一字板：全天最高等于最低。买不进也卖不出。"""
    return (high == low) & high.notna()


def _round_half_up(frame: pd.DataFrame, digits: int) -> pd.DataFrame:
    """逢五进一到分。

    交易所对涨跌停价是四舍五入到分且逢五进一；Python 的 round() 是银行家
    舍入，直接用会让一批票的涨停价差一分钱，"是否涨停"随之判错。
    与 functions.ZTPRICE 同一套算法——那边处理"一个比例"，这里处理
    "每列一个比例"的矩阵。
    """
    scale = 10.0**digits
    values = frame.to_numpy(dtype=float)
    # 加极小量抵消二进制表示误差（10.045 实际存成 10.04499…）。
    rounded = np.floor(values * scale + 0.5 + 1e-9) / scale
    return pd.DataFrame(
        np.where(np.isnan(values), np.nan, rounded), index=frame.index, columns=frame.columns
    )
