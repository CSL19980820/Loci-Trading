"""战法胜率汇总：精选候选 T+N 优先，手工复盘兜底。

选股落池后走候选验证（T+1/T+3/T+5），不再依赖人工补 ``reviews.return_pct``
才有目录胜率。手工复盘仍保留，用于无候选样本的旧战法。
"""
from __future__ import annotations

from typing import Any

from src.ledger import PalaceStore
from src.market import MarketStore
from src.review.application.outcomes import (
    PRIMARY_HORIZONS,
    evaluate_candidates,
    summarize_by_strategy,
)


def strategy_winrate_summary(
    palace: PalaceStore,
    market: MarketStore,
    *,
    limit: int = 2000,
    primary_horizon: int = 5,
    benchmark: str | None = "000300",
) -> list[dict[str, Any]]:
    """目录 / 胜率页用的战法胜率表。

    优先精选候选在 ``primary_horizon``（默认 T+5）已兑现的样本；
    同名战法若候选样本为 0，再回退手工 ``reviews``。
    """
    outcomes = evaluate_candidates(palace, market, limit=limit, benchmark=benchmark)
    from_candidates = summarize_by_strategy(
        outcomes,
        selected_only=True,
        primary_horizon=primary_horizon,
    )
    by_tag = {row["strategy_tag"]: row for row in from_candidates if row.get("strategy_tag")}

    for row in palace.strategy_winrates():
        tag = str(row.get("strategy_tag") or "")
        if not tag:
            continue
        existing = by_tag.get(tag)
        if existing and int(existing.get("total") or 0) > 0:
            continue
        if existing and int(existing.get("sample_all") or 0) > 0:
            # 有入选但窗口未走完：保留候选行（胜率可能为空），不盖成复盘口径
            continue
        by_tag[tag] = {
            **row,
            "source": "reviews",
            "horizons": {},
            "observing": 0,
            "sample_all": int(row.get("total") or 0),
        }

    rows = list(by_tag.values())
    rows.sort(key=lambda r: (-int(r.get("total") or 0), -int(r.get("sample_all") or 0), str(r.get("strategy_tag"))))
    return rows


def primary_horizon_labels() -> list[int]:
    return list(PRIMARY_HORIZONS)
