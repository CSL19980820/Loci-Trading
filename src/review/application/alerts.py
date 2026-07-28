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
    """批量取各票最新收盘价；行情库缺失时返回空 dict。"""
    if market is None or not codes:
        return {}
    normalized = [normalize_code(code) for code in codes]
    placeholders = ",".join("?" * len(normalized))
    rows = market.conn.execute(
        f"""
        SELECT q.code, q.close
        FROM quotes_daily q
        INNER JOIN (
            SELECT code, MAX(trade_date) AS max_date
            FROM quotes_daily
            WHERE code IN ({placeholders})
            GROUP BY code
        ) latest ON q.code = latest.code AND q.trade_date = latest.max_date
        """,
        normalized,
    ).fetchall()
    return {str(row["code"]): float(row["close"]) for row in rows if row["close"] is not None}


def today_alerts_payload(palace: PalaceStore, market: MarketStore | None = None) -> list[dict[str, Any]]:
    """活跃预案 + 最新收盘 → 触价/接近提醒列表。"""
    rows = palace.conn.execute(
        """
        SELECT p.id, p.code, p.title, p.stop_price, p.target_price, s.name
        FROM plans p
        LEFT JOIN stocks s ON s.code = p.code
        WHERE p.status = 'active'
          AND (p.stop_price IS NOT NULL OR p.target_price IS NOT NULL)
        ORDER BY p.occurred_on DESC, p.created_at DESC
        """
    ).fetchall()
    if not rows:
        return []

    codes = [str(row["code"]) for row in rows]
    closes = latest_closes(market, codes)
    items: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        stop = float(row["stop_price"]) if row["stop_price"] is not None else None
        target = float(row["target_price"]) if row["target_price"] is not None else None
        last_close = closes.get(code)
        status, note = _classify(last_close, stop, target)
        items.append(
            {
                "code": code,
                "name": str(row["name"] or code),
                "plan_id": str(row["id"]),
                "title": str(row["title"]),
                "stop_price": stop,
                "target_price": target,
                "last_close": last_close,
                "status": status,
                "note": note,
            }
        )
    return items
