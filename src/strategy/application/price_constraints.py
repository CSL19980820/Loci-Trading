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
) -> None:
    """保留指标复权口径，同时给涨跌停判断提供未复权收盘价。"""
    if not enabled or adjust == "none" or "close" not in panels:
        return
    raw = store.load_panel(
        fields=("close",),
        codes=codes,
        start=start,
        end=end,
        adjust="none",
        min_bars=min_bars,
    ).get("close")
    if raw is None or raw.empty:
        return
    panels["__raw_close"] = raw.reindex(
        index=panels["close"].index,
        columns=panels["close"].columns,
    )
