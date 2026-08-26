"""纸面跨链路策略口径：开仓过滤 + 竞价低开带。

与 skill_watch 扫描引擎解耦：改监测文案不应误伤开仓门闩。
"""
from __future__ import annotations

from src.ops.application.paper_policy.auction_gap import (
    DEFAULT_ABANDON_GAP_PCT,
    DEFAULT_DOWNGRADE_GAP_PCT,
    LowOpenBand,
    classify_low_open_band,
)
from src.ops.application.paper_policy.eligibility import (
    apply_downgrade_conservative,
    filter_openable_picks,
    is_auction_abandoned,
    is_auction_downgraded,
    is_observe_intent,
    planned_layers_from_pick,
    scan_auction_block_reason,
)
from src.ops.application.paper_policy.stances import (
    PAPER_ABANDON,
    SCAN_ABANDONED,
    SCAN_CONFIRMED,
    SCAN_DOWNGRADED,
    SCAN_PENDING,
    is_scan_block_stance,
    map_low_open_to_scan_stance,
)

__all__ = [
    "DEFAULT_ABANDON_GAP_PCT",
    "DEFAULT_DOWNGRADE_GAP_PCT",
    "LowOpenBand",
    "PAPER_ABANDON",
    "SCAN_ABANDONED",
    "SCAN_CONFIRMED",
    "SCAN_DOWNGRADED",
    "SCAN_PENDING",
    "apply_downgrade_conservative",
    "classify_low_open_band",
    "filter_openable_picks",
    "is_auction_abandoned",
    "is_auction_downgraded",
    "is_observe_intent",
    "is_scan_block_stance",
    "map_low_open_to_scan_stance",
    "planned_layers_from_pick",
    "scan_auction_block_reason",
]
