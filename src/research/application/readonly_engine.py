"""研究只读输入的可回滚计算引擎旁路。

研究 DTO 仍由 pandas 生成；Polars 只负责把已从公开 MarketStore API 取得的
只读 frame 做等价转换，便于基准比较。未安装或转换失败时原 frame 原样返回。
"""
from __future__ import annotations

import os

import pandas as pd


def polars_research_enabled() -> bool:
    raw = (os.environ.get("LOCI_RESEARCH_POLARS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def readonly_frame(frame: pd.DataFrame, *, engine: str | None = None) -> pd.DataFrame:
    """按显式 engine 选择研究只读 frame；默认保持 pandas。"""
    selected = (engine or ("polars" if polars_research_enabled() else "pandas")).lower()
    if selected != "polars" or frame.empty:
        return frame
    try:
        import polars as pl

        index = frame.index.copy()
        columns = frame.columns.copy()
        polars_frame = pl.DataFrame(frame.reset_index(drop=True).to_dict(orient="records"))
        converted = pd.DataFrame(polars_frame.to_dicts(), columns=columns)
        converted.index = index
        converted.columns = columns
        return converted
    except (ImportError, OSError, AttributeError, RuntimeError, TypeError, ValueError):
        return frame


__all__ = ["polars_research_enabled", "readonly_frame"]
