"""竞价 stance 权威词汇：扫描侧与纸面侧分表，禁止第三套阈值。"""
from __future__ import annotations

from typing import Literal

from src.ops.application.paper_policy.auction_gap import LowOpenBand

#: 扫描竞价确认（auction_confirm）
ScanAuctionStance = Literal["confirmed", "downgraded", "abandoned", "pending"]
SCAN_CONFIRMED: ScanAuctionStance = "confirmed"
SCAN_DOWNGRADED: ScanAuctionStance = "downgraded"
SCAN_ABANDONED: ScanAuctionStance = "abandoned"
SCAN_PENDING: ScanAuctionStance = "pending"

#: 纸面情景门闩（scenario_gates）
PaperAuctionStance = Literal["follow", "revise", "abandon", "wait"]
PAPER_FOLLOW: PaperAuctionStance = "follow"
PAPER_REVISE: PaperAuctionStance = "revise"
PAPER_ABANDON: PaperAuctionStance = "abandon"
PAPER_WAIT: PaperAuctionStance = "wait"

_SCAN_BLOCK = frozenset({SCAN_ABANDONED, SCAN_PENDING})


def is_scan_block_stance(stance: str | None) -> bool:
    """扫描侧禁止开仓的 stance（放弃 / 待定 fail-closed）。"""
    return str(stance or "").strip().lower() in _SCAN_BLOCK


def map_low_open_to_scan_stance(band: LowOpenBand) -> ScanAuctionStance | None:
    """低开带 → 扫描 stance；ok 不映射（由高开/平开分支决定）。"""
    if band == "abandon":
        return SCAN_ABANDONED
    if band == "downgrade":
        return SCAN_DOWNGRADED
    return None


__all__ = [
    "PAPER_ABANDON",
    "PAPER_FOLLOW",
    "PAPER_REVISE",
    "PAPER_WAIT",
    "PaperAuctionStance",
    "SCAN_ABANDONED",
    "SCAN_CONFIRMED",
    "SCAN_DOWNGRADED",
    "SCAN_PENDING",
    "ScanAuctionStance",
    "is_scan_block_stance",
    "map_low_open_to_scan_stance",
]
