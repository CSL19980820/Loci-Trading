"""当日预案触价提醒（MVP）。"""
from __future__ import annotations

from typing import Any, Literal

from src.market import MarketStore
from src.ledger import PalaceStore, normalize_code

AlertStatus = Literal["stop_hit", "target_hit", "near_stop", "near_target", "ok", "no_quote"]

NEAR_PCT = 0.02
ACTIONABLE_STATUSES = frozenset({"stop_hit", "target_hit", "near_stop", "near_target"})


def _classify(
    last_close: float | None,
    stop: float | None,
    target: float | None,
) -> tuple[AlertStatus, str]:
    if last_close is None:
        return "no_quote", "暂无行情"
    if stop is not None and last_close <= float(stop):
        return "stop_hit", f"昨收 {last_close:.3f} ≤ 止损 {float(stop):.3f}"
    if target is not None and last_close >= float(target):
        return "target_hit", f"昨收 {last_close:.3f} ≥ 目标 {float(target):.3f}"
    if stop is not None and last_close > float(stop):
        gap = (last_close - float(stop)) / float(stop)
        if gap <= NEAR_PCT:
            return "near_stop", f"距止损 {gap * 100:.1f}%"
    if target is not None and last_close < float(target):
        gap = (float(target) - last_close) / float(target)
        if gap <= NEAR_PCT:
            return "near_target", f"距目标 {gap * 100:.1f}%"
    return "ok", "价格在预案区间内"


def latest_closes(market: MarketStore | None, codes: list[str]) -> dict[str, float]:
    """批量取各票最新收盘价；行情库缺失时返回空 dict。

    经 ``MarketStore.latest_bars``，禁止 review 直捅 ``market.conn``。
    """
    if market is None or not codes:
        return {}
    normalized = [normalize_code(code) for code in codes]
    try:
        bars = market.latest_bars(normalized)
    except Exception:  # noqa: BLE001 — 触价提醒缺行情时降级空
        return {}
    out: dict[str, float] = {}
    for code, bar in (bars or {}).items():
        if not isinstance(bar, dict):
            continue
        close = bar.get("close")
        if close is None:
            continue
        try:
            out[str(code)] = float(close)
        except (TypeError, ValueError):
            continue
    return out


def today_alerts_payload(palace: PalaceStore, market: MarketStore | None = None) -> list[dict[str, Any]]:
    """活跃预案 + 最新收盘 → 触价/接近提醒列表。"""
    rows = palace.active_plans_with_stops()
    if not rows:
        return []

    codes = [str(row["code"]) for row in rows]
    closes = latest_closes(market, codes)
    items: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        stop = row.get("stop_price")
        target = row.get("target_price")
        stop_f = float(stop) if stop is not None else None
        target_f = float(target) if target is not None else None
        last_close = closes.get(code)
        status, note = _classify(last_close, stop_f, target_f)
        items.append(
            {
                "code": code,
                "name": str(row.get("name") or code),
                "plan_id": str(row["id"]),
                "title": str(row["title"]),
                "stop_price": stop_f,
                "target_price": target_f,
                "last_close": last_close,
                "status": status,
                "note": note,
            }
        )
    return items
