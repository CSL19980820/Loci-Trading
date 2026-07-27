"""容量校验：回测里完美，实盘按你的仓位买不进去。

按目标仓位反查「成交额占比 ≤ X%」。
超了就标注 NOT_EXECUTABLE，不是禁止，是提示。
"""
from __future__ import annotations

from src.market.store import MarketStore


def check_capacity(
    picks: list[dict],
    market_store: MarketStore,
    position_size_yuan: float = 100_000,
    max_impact_pct: float = 5.0,
) -> list[dict]:
    """为每个 pick 标注流动性容量。

    读取近 5 日均成交额，计算仓位占比。
    超过 max_impact_pct 标注 capacity=limited，否则 ok。
    """
    results = []
    for pick in picks:
        code = str(pick.get("code", ""))
        annotated = dict(pick)

        if not code:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        rows = market_store.conn.execute(
            """
            SELECT amount FROM quotes_daily
            WHERE code = ?
            ORDER BY trade_date DESC
            LIMIT 5
            """,
            (code,),
        ).fetchall()

        if not rows:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        amounts = [float(r["amount"]) for r in rows if r["amount"] is not None]
        if not amounts:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        avg_daily_amount = sum(amounts) / len(amounts)
        if avg_daily_amount <= 0:
            annotated["capacity"] = "ok"
            results.append(annotated)
            continue

        impact_pct = position_size_yuan / avg_daily_amount * 100
        annotated["capacity"] = "limited" if impact_pct > max_impact_pct else "ok"
        results.append(annotated)

    return results
