"""持仓周期归因：给每一段持仓补上 MAE / MFE 与持有天数，再分组汇总。

MAE（最大不利偏移）和 MFE（最大有利偏移）是复盘里信息量最大的两个数字：

- **MFE 远高于最终收益** → 浮盈拿不住，问题在退出纪律而不是选股
- **MAE 常年破某个幅度** → 买点太靠后或止损位设得不合理
- **赢家的 MAE 明显小于输家** → 说明"上来就套"是个有效的早期离场信号

这些靠人肉翻 K 线极难看出来，但对着账本 + 行情算是确定性的。
"""
from __future__ import annotations

from typing import Any

from src.market.store import MarketStore
from src.review.replay import RoundTrip


def attribute_round_trips(
    trips: list[RoundTrip], market: MarketStore
) -> list[RoundTrip]:
    """就地补齐每段持仓的 MAE / MFE / 持有天数。

    未清仓的周期用"至今"作为区间终点——扛着的浮亏同样是复盘素材，
    不能因为还没了结就把它排除在外。
    """
    calendar = market.trading_days()
    if not calendar:
        return trips
    position_of = {day: index for index, day in enumerate(calendar)}

    for trip in trips:
        start = _nearest_on_or_after(calendar, trip.opened_on)
        if start is None:
            continue
        end = trip.closed_on or calendar[-1]
        end = _nearest_on_or_before(calendar, end) or calendar[-1]
        if end < start:
            continue

        frame = market.history(trip.code, start=start, end=end, adjust="qfq")
        if frame.empty:
            continue

        entry = trip.avg_cost
        if not entry > 0:
            continue

        lows = [float(row.low) for row in frame.itertuples() if row.low is not None]
        highs = [float(row.high) for row in frame.itertuples() if row.high is not None]
        if lows:
            trip.mae_pct = round((min(lows) / entry - 1) * 100, 4)
        if highs:
            trip.mfe_pct = round((max(highs) / entry - 1) * 100, 4)

        start_index, end_index = position_of.get(start), position_of.get(end)
        if start_index is not None and end_index is not None:
            trip.hold_days = end_index - start_index
    return trips


def _nearest_on_or_after(calendar: list[str], day: str) -> str | None:
    for value in calendar:
        if value >= day:
            return value
    return None


def _nearest_on_or_before(calendar: list[str], day: str) -> str | None:
    result = None
    for value in calendar:
        if value <= day:
            result = value
        else:
            break
    return result


def summarize_round_trips(trips: list[RoundTrip]) -> dict[str, Any]:
    """按标的、月份、开放/已了结分组汇总。"""
    closed = [trip for trip in trips if not trip.is_open]
    open_trips = [trip for trip in trips if trip.is_open]

    returns = [trip.return_pct for trip in closed if trip.return_pct is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]

    summary: dict[str, Any] = {
        "total": len(trips),
        "closed": len(closed),
        "open": len(open_trips),
        "realized_pnl": round(sum(trip.realized_pnl for trip in closed), 2),
    }

    if returns:
        summary.update(
            {
                "win_rate": round(len(wins) / len(returns) * 100, 2),
                "avg_return_pct": round(sum(returns) / len(returns), 4),
                "best_pct": round(max(returns), 4),
                "worst_pct": round(min(returns), 4),
                "profit_factor": round(sum(wins) / abs(sum(losses)), 3)
                if losses and abs(sum(losses)) > 1e-9
                else None,
            }
        )

    maes = [trip.mae_pct for trip in closed if trip.mae_pct is not None]
    mfes = [trip.mfe_pct for trip in closed if trip.mfe_pct is not None]
    if maes:
        summary["avg_mae_pct"] = round(sum(maes) / len(maes), 4)
    if mfes:
        summary["avg_mfe_pct"] = round(sum(mfes) / len(mfes), 4)

    # 赢家与输家的 MAE 对比：若差距明显，"上来就套"就是个可用的离场信号。
    winner_maes = [t.mae_pct for t in closed if t.mae_pct is not None and (t.return_pct or 0) > 0]
    loser_maes = [t.mae_pct for t in closed if t.mae_pct is not None and (t.return_pct or 0) <= 0]
    if winner_maes and loser_maes:
        summary["winner_avg_mae_pct"] = round(sum(winner_maes) / len(winner_maes), 4)
        summary["loser_avg_mae_pct"] = round(sum(loser_maes) / len(loser_maes), 4)

    if mfes and returns:
        give_back = sum(mfes) / len(mfes) - sum(returns) / len(returns)
        summary["profit_give_back_pct"] = round(give_back, 4)
        if give_back > 3:
            summary["hint"] = (
                f"持有期内平均最大浮盈比最终收益高 {give_back:.1f} 个百分点，"
                "利润在回吐，问题更可能出在退出纪律而不是选股"
            )

    holds = [trip.hold_days for trip in closed if trip.hold_days is not None]
    if holds:
        summary["avg_hold_days"] = round(sum(holds) / len(holds), 2)

    by_code: dict[str, dict[str, Any]] = {}
    for trip in closed:
        bucket = by_code.setdefault(trip.code, {"name": trip.name, "count": 0, "realized_pnl": 0.0})
        bucket["count"] += 1
        bucket["realized_pnl"] = round(bucket["realized_pnl"] + trip.realized_pnl, 2)
    summary["by_code"] = dict(
        sorted(by_code.items(), key=lambda item: item[1]["realized_pnl"])
    )

    by_month: dict[str, dict[str, Any]] = {}
    for trip in closed:
        month = (trip.closed_on or trip.opened_on)[:7]
        bucket = by_month.setdefault(month, {"count": 0, "realized_pnl": 0.0})
        bucket["count"] += 1
        bucket["realized_pnl"] = round(bucket["realized_pnl"] + trip.realized_pnl, 2)
    summary["by_month"] = dict(sorted(by_month.items()))

    if len(closed) < 10:
        summary["caution"] = f"仅 {len(closed)} 段已了结持仓，统计量不稳定"
    return summary
