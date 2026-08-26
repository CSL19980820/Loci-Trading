"""兼容壳：竞价低开带已迁至 ``src.ops.application.paper_policy``。"""
from __future__ import annotations

from src.ops.application.paper_policy.auction_gap import (
    DEFAULT_ABANDON_GAP_PCT,
    DEFAULT_DOWNGRADE_GAP_PCT,
    LowOpenBand,
    classify_low_open_band,
)

__all__ = [
    "DEFAULT_ABANDON_GAP_PCT",
    "DEFAULT_DOWNGRADE_GAP_PCT",
    "LowOpenBand",
    "classify_low_open_band",
]
