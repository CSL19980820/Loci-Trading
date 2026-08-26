"""分钟线均价脏值回正（东财 trends / 新浪手股混用共用）。"""
from __future__ import annotations

import pandas as pd


def sanitize_avg_price(avg: pd.Series, close: pd.Series) -> pd.Series:
    """相对收盘偏离过大时按 100 倍回正，仍离谱则置空。

    典型误用：量单位「手」未换算导致均价约 100×；或把振幅百分比字段当均价。
    """
    ratio = avg / close.replace(0, pd.NA)
    scaled = avg.where(~(ratio > 20), avg / 100.0)
    ratio2 = scaled / close.replace(0, pd.NA)
    return scaled.where((ratio2 > 0.2) & (ratio2 < 5.0))
