"""纸面候选可开仓判定：扫描侧竞价放弃不得进入预案/开仓。

唯一过滤口径：``auction_stance`` + ``open_blocked``，禁止解析中文文案启发式。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.ops.application.paper_policy.stances import (
    SCAN_DOWNGRADED,
    SCAN_PENDING,
    is_scan_block_stance,
)


def planned_layers_from_pick(item: Mapping[str, Any], *, default: float = 1.0) -> float:
    """读 pick/预案项层数：planned_layers_max → planned_layers → layers。"""
    for key in ("planned_layers_max", "planned_layers", "layers"):
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def is_auction_abandoned(entry: Mapping[str, Any]) -> bool:
    """扫描侧已放弃/待定 → 不可开仓。

    ``pending`` fail-closed。兼容旧纸面词 ``abandon``（映射为扫描 abandoned）。
    不再用中文 reason/role_basis 启发式判废。
    """
    if entry.get("open_blocked") is True:
        return True
    stance = str(entry.get("auction_stance") or "").strip().lower()
    if stance == "abandon":
        return True
    return is_scan_block_stance(stance)


def is_auction_downgraded(entry: Mapping[str, Any]) -> bool:
    return str(entry.get("auction_stance") or "").strip().lower() == SCAN_DOWNGRADED


def is_observe_intent(entry: Mapping[str, Any] | None) -> bool:
    """次日观察票：进预案但不允许开/加仓。"""
    if not isinstance(entry, dict):
        return False
    return str(entry.get("intent") or "").strip().lower() == "observe"


def has_actionable_picks(picks: list[Any] | None) -> bool:
    """是否存在可执行候选。仅观察 / 空列表都不算。

    缺 ``intent``/``action`` 视为可执行，兼容未打标的引擎 picks；显式
    ``observe``/``watch``（含统一池默认观察行）不算，避免盘中「仅观察」刷企微。
    """
    for raw in picks or []:
        if not isinstance(raw, dict):
            continue
        if not str(raw.get("code") or "").strip():
            continue
        if is_observe_intent(raw):
            continue
        action = str(raw.get("action") or raw.get("intent") or "").strip().lower()
        if action in {"observe", "watch"}:
            continue
        return True
    return False


def apply_downgrade_conservative(pick: dict[str, Any]) -> dict[str, Any]:
    """竞价降级保留候选，但层数与情景更保守（半层、高开不追）。

    以 ``auction.downgraded`` 做幂等短路，避免 filter 链路上重复追加 thesis。
    """
    existing_auction = pick.get("auction") if isinstance(pick.get("auction"), dict) else {}
    if existing_auction.get("downgraded"):
        return pick
    out = dict(pick)
    layers = planned_layers_from_pick(out, default=0.5)
    capped = min(layers, 0.5)
    out["planned_layers"] = capped
    out["planned_layers_max"] = capped
    if "layers" in out:
        out["layers"] = capped
    auction = dict(out.get("auction") or {})
    auction["downgraded"] = True
    auction["gap_up_chase"] = False
    out["auction"] = auction
    veto = list(out.get("veto") or [])
    note = "竞价降级：仅半层、高开不追"
    if note not in veto:
        veto.append(note)
    out["veto"] = veto
    if out.get("thesis"):
        out["thesis"] = f"{out['thesis']}；{note}"
    else:
        out["thesis"] = note
    return out


def filter_openable_picks(
    picks: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """分离可进预案候选与竞价放弃票；降级票就地收紧参数。"""
    openable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in picks or []:
        if not isinstance(raw, dict):
            continue
        if is_auction_abandoned(raw):
            excluded.append(raw)
            continue
        openable.append(apply_downgrade_conservative(raw) if is_auction_downgraded(raw) else raw)
    return openable, excluded


def scan_auction_block_reason(item: Mapping[str, Any]) -> str | None:
    """预案项若扫描侧已放弃/待定，返回硬拒绝理由。"""
    if not is_auction_abandoned(item):
        return None
    stance = str(item.get("auction_stance") or "").strip().lower()
    reason = str(item.get("auction_reason") or item.get("role_basis") or "").strip()
    if stance == SCAN_PENDING or stance == "pending":
        if reason:
            return f"扫描竞价待定：{reason}"
        return "扫描竞价待定，不可开仓"
    if reason:
        return f"扫描竞价放弃：{reason}"
    return "扫描竞价放弃，不可开仓"


__all__ = [
    "apply_downgrade_conservative",
    "filter_openable_picks",
    "has_actionable_picks",
    "is_auction_abandoned",
    "is_auction_downgraded",
    "is_observe_intent",
    "planned_layers_from_pick",
    "scan_auction_block_reason",
]
