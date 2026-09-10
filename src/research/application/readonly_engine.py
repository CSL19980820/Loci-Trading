"""兼容旧研究输入入口；不再进行没有计算收益的 DataFrame 往返转换。"""
from __future__ import annotations

import pandas as pd


def polars_research_enabled() -> bool:
    """旧 POC 已退出执行链路；保留导入兼容，但不能再宣称已启用加速。"""
    return False


def readonly_frame(frame: pd.DataFrame, *, engine: str | None = None) -> pd.DataFrame:
    """保持输入对象及 dtype；旧 engine 参数仅为调用兼容而保留。"""
    return frame


__all__ = ["polars_research_enabled", "readonly_frame"]
