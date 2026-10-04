"""为需要真实交易价格约束的策略补充原始价格面板。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd


def attach_raw_limit_close(
    store: Any,
    panels: dict[str, pd.DataFrame],
    *,
    enabled: bool,
    adjust: str,
    codes: Sequence[str],
    start: str,
    end: str,
    min_bars: int,
    include_ohlc: bool = False,
) -> None:
    """提供未复权收盘价；需要高低价范围判断的引擎可显式请求完整 OHLC。"""
    if not enabled or "close" not in panels:
        return
    fields = ("open", "high", "low", "close") if include_ohlc else ("close",)
    # MarketStore can preserve the unadjusted prices in the original read.
    # Older/custom stores keep the separate-load compatibility path below.
    if all(isinstance(panels.get(f"__raw_{field}"), pd.DataFrame)
           and panels[f"__raw_{field}"].index.equals(panels["close"].index)
           and panels[f"__raw_{field}"].columns.equals(panels["close"].columns)
           for field in fields):
        return
    if adjust == "none":
        for field in fields:
            if field in panels:
                panels[f"__raw_{field}"] = panels[field]
        return
    raw = store.load_panel(
        fields=fields,
        codes=codes,
        start=start,
        end=end,
        adjust="none",
        min_bars=min_bars,
    )
    for field in fields:
        panel = raw.get(field)
        if panel is not None and not panel.empty:
            panels[f"__raw_{field}"] = panel.reindex(
                index=panels["close"].index, columns=panels["close"].columns,
            )
