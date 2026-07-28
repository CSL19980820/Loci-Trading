"""复盘 / 胜率 HTTP。"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query

from src.app.legacy.quant_common import (
    market_store,
    missing_dependency,
    palace_store,
)


def build_review_router(
    *,
    market_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()

    def _market():
        return market_store(market_db)

    def _palace():
        return palace_store(palace_db)

    @router.get("/api/review/equity", tags=["review"])
    def review_equity(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        benchmarks: str = Query(default="000300", max_length=64),
    ) -> dict[str, Any]:
        try:
            from src.review import build_equity_curve
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        codes = tuple(item.strip() for item in benchmarks.split(",") if item.strip())
        with _palace() as palace, _market() as market:
            return build_equity_curve(
                palace, market, start=start, end=end, benchmarks=codes
            ).to_dict()

    @router.get("/api/review/trips", tags=["review"])
    def review_trips(
        code: str | None = Query(default=None, pattern=r"^\d{6}$"),
    ) -> dict[str, Any]:
        try:
            from src.review import attribute_round_trips, round_trips, summarize_round_trips
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace, _market() as market:
            trips = attribute_round_trips(round_trips(palace, code=code), market)
            return {
                "trips": [trip.to_dict() for trip in trips],
                "summary": summarize_round_trips(trips),
            }

    @router.get("/api/review/candidates", tags=["review"])
    def review_candidates(
        limit: int = Query(default=300, ge=1, le=2000),
        benchmark: str | None = Query(default="000300", pattern=r"^\d{6}$"),
    ) -> dict[str, Any]:
        try:
            from src.review import evaluate_candidates, summarize_candidates
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace, _market() as market:
            outcomes = evaluate_candidates(palace, market, limit=limit, benchmark=benchmark)
            return {
                "outcomes": [outcome.to_dict() for outcome in outcomes],
                "summary": summarize_candidates(outcomes),
            }

    @router.get("/api/review/plans", tags=["review"])
    def review_plans() -> list[dict[str, Any]]:
        try:
            from src.review import evaluate_plans
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace, _market() as market:
            return evaluate_plans(palace, market)

    @router.get("/api/review/positions", tags=["review"])
    def review_positions(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> list[dict[str, Any]]:
        """回放某天收盘时的持仓。此前只能取"现在"。"""
        try:
            from src.review import positions_as_of
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace:
            return [
                {
                    "code": item.code,
                    "name": item.name,
                    "shares": item.shares,
                    "cost": item.cost,
                    "cost_value": item.cost_value,
                }
                for item in positions_as_of(palace, date)
            ]

    @router.get("/api/winrate/summary", tags=["review"])
    def winrate_summary() -> list[dict[str, Any]]:
        """各战法综合胜率（全时段汇总）。首页滚动卡片用。"""
        with _palace() as palace:
            return palace.strategy_winrates()

    @router.get("/api/winrate/trend", tags=["review"])
    def winrate_trend(
        granularity: Literal["month", "week"] = Query(default="month"),
        tags: str | None = Query(default=None, max_length=500),
    ) -> list[dict[str, Any]]:
        """按时间粒度分战法统计胜率趋势。tags 用逗号分隔多个战法名。"""
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        with _palace() as palace:
            return palace.winrate_trend(strategy_tags=tag_list, granularity=granularity)

    return router
