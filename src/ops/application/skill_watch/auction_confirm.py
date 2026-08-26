"""竞价龙头确认：09:15–09:30 用集合竞价/开盘前报价核对龙头是否还在。

昨天的龙头今天竞价就砸，是最早能看到的退潮信号；反过来，竞价一字/大幅高开
且有委买承接，说明资金还认。本模块只给态度，不下单——是否跟随由纸面舱的
情景门闩决定（纸面默认 ≥09:30 才允许开仓成交）。
"""
from __future__ import annotations


def _wudao_keys():
    """悟道键名表。**延迟导入**：``src.intel.__init__`` 会反向 import ``src.ops``，
    模块级导入直接成环（ImportError: partially initialized module）。
    """
    from src.intel.application import wudao_keys

    return wudao_keys


from collections.abc import Mapping
from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.ops.application.skill_watch import payload as pl
from src.ops.application.paper_policy.auction_gap import classify_low_open_band
from src.ops.application.paper_policy.stances import (
    SCAN_ABANDONED,
    SCAN_CONFIRMED,
    SCAN_DOWNGRADED,
    SCAN_PENDING,
    map_low_open_to_scan_stance,
)
from src.ops.application.skill_watch.tuning import DEFAULT_AUCTION

_TZ = ZoneInfo("Asia/Shanghai")

AuctionStance = Literal["confirmed", "downgraded", "abandoned", "pending"]

STANCE_LABEL: dict[str, str] = {
    "confirmed": "竞价确认",
    "downgraded": "竞价降级",
    "abandoned": "竞价放弃",
    "pending": "竞价待定",
}


def in_auction_window(now: datetime | None = None) -> bool:
    """09:15–09:30 之间才有竞价可确认；其余时间这一段自动跳过。"""
    current = (now or datetime.now(_TZ)).astimezone(_TZ)
    if current.weekday() >= 5:
        return False
    clock = current.timetz().replace(tzinfo=None)
    return time(9, 15) <= clock < time(9, 30)


def _auction_rows(payload: Any, *, limit: int = 400) -> dict[str, dict[str, Any]]:
    return pl.rows_by_code(payload, limit=limit, inherit_keys=())


def _gap_pct(row: Mapping[str, Any]) -> float | None:
    direct = pl.field(row, "pct_chg")
    if direct is not None:
        return direct
    price = pl.field(row, "auctionPrice") or pl.field(row, "open") or pl.field(row, "price")
    prev = pl.field(row, "prevClose") or pl.field(row, "preClose") or pl.field(row, "昨收")
    if price is None or prev is None or prev <= 0:
        return None
    return (price / prev - 1.0) * 100.0


def _not_ready(payload: Any) -> bool:
    """悟道明确说竞价数据没就绪时按待定处理，不能拿 T-1 冒充今日。"""
    if isinstance(payload, Mapping):
        provenance = payload.get("provenance")
        if payload.get("degraded") or payload.get("unavailable") or (
            isinstance(provenance, Mapping) and provenance.get("degraded")
        ):
            return True
    warnings = pl.quality_warnings(payload, "auction")
    text = " ".join(warnings).upper()
    return "AUCTION_DATA_NOT_READY" in text or "NOT_READY" in text


def evaluate_auction(
    leaders: list[dict[str, Any]],
    snapshot: Any,
    *,
    params: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """对每个龙头给出竞价态度。纯函数，便于直接喂造好的快照测试。"""
    config = {**DEFAULT_AUCTION, **dict(params or {})}
    rows = _auction_rows(snapshot)
    pending_all = _not_ready(snapshot)
    results: list[dict[str, Any]] = []

    for leader in leaders:
        code = str(leader.get("code") or "")
        if not code:
            continue
        row = rows.get(code)
        base = {
            "code": code,
            "name": leader.get("name") or code,
            "role": leader.get("role"),
            "theme_name": leader.get("theme_name"),
        }
        if pending_all or row is None:
            results.append(
                {
                    **base,
                    "stance": SCAN_PENDING,
                    "gap_pct": None,
                    "reason": "竞价数据未就绪" if pending_all else "竞价快照里没有该标的",
                }
            )
            continue

        gap = _gap_pct(row)
        seal = pl.field(row, "limitBuyAmount") or pl.field(row, "finalSealAmount")
        if gap is None:
            results.append(
                {**base, "stance": SCAN_PENDING, "gap_pct": None, "reason": "缺竞价价格或昨收"}
            )
            continue

        band = classify_low_open_band(
            gap,
            abandon_gap_pct=float(config["abandon_gap_pct"]),
            downgrade_gap_pct=float(config["downgrade_gap_pct"]),
        )
        mapped = map_low_open_to_scan_stance(band)
        if mapped == SCAN_ABANDONED:
            stance, reason = SCAN_ABANDONED, f"竞价低开 {gap:.2f}%，龙头逻辑破坏"
        elif mapped == SCAN_DOWNGRADED:
            stance, reason = SCAN_DOWNGRADED, f"竞价低开 {gap:.2f}%，承接转弱"
        elif gap >= float(config["strong_gap_pct"]):
            stance, reason = SCAN_CONFIRMED, f"竞价高开 {gap:.2f}%，资金仍认"
        else:
            stance, reason = SCAN_CONFIRMED, f"竞价 {gap:+.2f}%，基本平开维持"
        if seal:
            reason += f"；涨停委买 {seal:.0f}"
        results.append(
            {**base, "stance": stance, "gap_pct": round(gap, 2), "seal_amount": seal, "reason": reason}
        )
    return results


def confirm_leaders(
    call_tool: Any,
    leaders: list[dict[str, Any]],
    *,
    trade_date: str,
    params: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """竞价窗内拉一次全景快照并给态度；窗外或无龙头时不打接口。"""
    if not leaders:
        return {"active": False, "reason": "无龙头可确认", "stances": []}
    if not in_auction_window(now):
        return {"active": False, "reason": "不在 09:15-09:30 竞价窗", "stances": []}

    snapshot = call_tool(
        "auction_opening_snapshot",
           _wudao_keys().with_date(
            "auction_opening_snapshot",
       trade_date,
     format="json",
 detailLevel="standard",
     ),
    )
    stances = evaluate_auction(leaders, snapshot, params=params)
    return {
        "active": True,
        "reason": "",
        "trade_date": trade_date,
        "stances": stances,
        "abandoned": [row["code"] for row in stances if row["stance"] == SCAN_ABANDONED],
        "downgraded": [row["code"] for row in stances if row["stance"] == SCAN_DOWNGRADED],
    }


__all__ = [
    "AuctionStance",
    "STANCE_LABEL",
    "confirm_leaders",
    "evaluate_auction",
    "in_auction_window",
]
