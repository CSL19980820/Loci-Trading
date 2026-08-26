"""选股历史 HTTP：单战法与批量（盘面聚合）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.shared.api_deps import palace_store


def _group_by_date(items: list[dict[str, Any]]) -> dict[str, list[dict]]:
    by_date: dict[str, list[dict]] = {}
    for item in items:
        by_date.setdefault(item["date"], []).append(item)
    return by_date


def build_screen_history_router(*, palace_db: str | None = None) -> APIRouter:
    router = APIRouter()

    def _palace():
        return palace_store(palace_db)

    @router.get("/api/screen/history", tags=["strategy"])
    def screen_history(
        strategy: str = Query(min_length=1, max_length=64),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=200, ge=1, le=1000),
        live_only: bool = Query(
            default=True,
            description="默认仅盘后/当日真选；false 时含区间回填（审计用）",
        ),
    ) -> dict[str, Any]:
        """按战法查历史选股记录（从账本候选池读取）。"""
        with _palace() as palace:
            items = palace.candidates_by_strategy(
                strategy, start=start, end=end, limit=limit, live_only=live_only
            )
        by_date = _group_by_date(items)
        return {
            "strategy": strategy,
            "total": len(items),
            "dates": sorted(by_date.keys(), reverse=True),
            "by_date": by_date,
        }

    @router.get("/api/screen/history/batch", tags=["strategy"])
    def screen_history_batch(
        strategies: str = Query(
            min_length=1,
            max_length=2000,
            description="逗号分隔战法 slug，最多 32 个",
        ),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=80, ge=1, le=200),
        live_only: bool = Query(
            default=True,
            description="默认仅盘后/当日真选；false 时含区间回填（审计用）",
        ),
    ) -> dict[str, Any]:
        """多战法选股历史一次返回，供盘面聚合，避免前端按策略 N+1。"""
        slugs = [part.strip() for part in strategies.split(",") if part.strip()]
        slugs = list(dict.fromkeys(slugs))[:32]
        if not slugs:
            raise HTTPException(status_code=422, detail="strategies 不能为空")
        with _palace() as palace:
            by_strategy_items = palace.candidates_by_strategies(
                slugs,
                start=start,
                end=end,
                limit_per_strategy=limit,
                live_only=live_only,
            )
        histories: list[dict[str, Any]] = []
        for slug in slugs:
            items = by_strategy_items.get(slug) or []
            by_date = _group_by_date(items)
            histories.append(
                {
                    "strategy": slug,
                    "total": len(items),
                    "dates": sorted(by_date.keys(), reverse=True),
                    "by_date": by_date,
                }
            )
        return {"strategies": slugs, "histories": histories}

    return router
