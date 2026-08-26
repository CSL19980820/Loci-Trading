"""竞价低开带：扫描确认与纸面预案共用的纯判定。"""
from __future__ import annotations

from typing import Literal

LowOpenBand = Literal["abandon", "downgrade", "ok"]

DEFAULT_ABANDON_GAP_PCT = -5.0
DEFAULT_DOWNGRADE_GAP_PCT = -2.0


def classify_low_open_band(
    gap_pct: float,
    *,
    abandon_gap_pct: float = DEFAULT_ABANDON_GAP_PCT,
    downgrade_gap_pct: float = DEFAULT_DOWNGRADE_GAP_PCT,
) -> LowOpenBand:
    """按相对昨收的涨跌幅%划分低开带。

    ``gap <= abandon`` 放弃，``gap <= downgrade`` 降级，其余 ok。
    调用方用 ``map_low_open_to_scan_stance`` 映射扫描词汇。
    """
    abandon = float(abandon_gap_pct)
    downgrade = float(downgrade_gap_pct)
    if gap_pct <= abandon:
        return "abandon"
    if gap_pct <= downgrade:
        return "downgrade"
    return "ok"


__all__ = [
    "DEFAULT_ABANDON_GAP_PCT",
    "DEFAULT_DOWNGRADE_GAP_PCT",
    "LowOpenBand",
    "classify_low_open_band",
]
