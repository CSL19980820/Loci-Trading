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
        window_days: int | None = Query(
            default=None,
            ge=1,
            le=60,
            description="仅保留近 N 个交易日选出的候选（盘面近选跟踪用 5）",
        ),
        selected_only: bool = Query(
            default=False,
            description="仅精选；盘面近选跟踪传 true",
        ),
        as_of: str | None = Query(
            default=None,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="观察日（交易日）；默认取行情日历末日",
        ),
    ) -> dict[str, Any]:
        try:
            from src.review import evaluate_candidates, filter_recent_outcomes, summarize_candidates
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace, _market() as market:
            outcomes = evaluate_candidates(palace, market, limit=limit, benchmark=benchmark)
            if window_days is not None:
                calendar = market.trading_days()
                anchor = as_of or (calendar[-1] if calendar else "")
                outcomes = filter_recent_outcomes(
                    outcomes,
                    calendar,
                    as_of=anchor,
                    window_days=window_days,
                    selected_only=selected_only,
                )
            elif selected_only:
                outcomes = [row for row in outcomes if row.selected]
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

    @router.get("/api/review/drift", tags=["review"])
    def review_drift(
        strategy_tag: str = Query(default="", max_length=128),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        """回测-实盘偏离：计划（position_tracking）vs 真实成交（position_events）。"""
        try:
            from src.review import compute_drift
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace:
            return compute_drift(palace, strategy_tag, limit=limit).to_dict()

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
        """各战法胜率：精选候选 T+5 优先，手工复盘兜底。"""
        try:
            from src.review import strategy_winrate_summary
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace, _market() as market:
            return strategy_winrate_summary(palace, market)

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
