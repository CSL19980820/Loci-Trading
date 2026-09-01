"""账本 HTTP 路由（candidates / plans / reviews / pools / timeline / alerts）。"""
import csv
import io
import logging
from collections.abc import Callable, Generator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from src.ledger import PalaceStore
from src.ledger.api.schemas import (
    CandidateBatchDeleteInput,
    CandidateInput,
    PlanInput,
    ReviewInput,
)

logger = logging.getLogger(__name__)


def build_ledger_router(
    *,
    write_dependency: Callable[..., None],
    get_store: Callable[..., Generator[PalaceStore, None, None]],
    market_db: str | None = None,
) -> APIRouter:
    """装配账本路由；写操作与 Store 依赖由组合根注入。

    注意：本模块不使用 ``from __future__ import annotations``。
    工厂内 ``Annotated[..., Depends(...)]`` 别名必须在路由 ``def`` 时求值为实体，
    否则 FastAPI 会把 ``store`` / 写依赖误判为 query 参数。
    """
    router = APIRouter()
    Store = Annotated[PalaceStore, Depends(get_store)]
    WriteAccess = Annotated[None, Depends(write_dependency)]

    @router.get("/api/candidates", tags=["candidates"])
    def candidates(
        store: Store,
        date_value: str | None = Query(default=None, alias="date"),
        include_backfill: bool = Query(
            default=False,
            description="true 时含区间回填；默认排除",
        ),
    ) -> list[dict[str, Any]]:
        return store.candidates_payload(
            date_value, include_backfill=include_backfill
        )

    @router.get("/api/candidates/list", tags=["candidates"])
    def candidates_list(
        store: Store,
        code: str | None = Query(default=None, max_length=16),
        strategy: str | None = Query(default=None, max_length=64),
        decision: str | None = Query(default=None, max_length=32),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=200, ge=1, le=1000),
        include_backfill: bool = Query(
            default=False,
            description="true 时含区间回填；默认排除",
        ),
    ) -> list[dict[str, Any]]:
        """跨日期候选列表。按战法/裁决/股票代码过滤，点进详情看单条。"""
        return store.candidates_list_payload(
            code=code,
            strategy=strategy,
            decision=decision,
            start=start,
            end=end,
            limit=limit,
            include_backfill=include_backfill,
        )

    @router.get("/api/plans", tags=["plans"])
    def plans(store: Store, status: str = "active") -> list[dict[str, Any]]:
        return store.plans_payload(status)

    @router.get("/api/timeline/{code}", tags=["timeline"])
    def timeline(code: str, store: Store) -> list[dict[str, Any]]:
        return store.timeline_payload(code)

    def _csv_attachment(
        rows: list[dict[str, Any]], columns: list[tuple[str, str]], filename: str
    ) -> Response:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([header for _, header in columns])
        for row in rows:
            writer.writerow([row.get(key, "") for key, _ in columns])
        return Response(
            content=buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/api/candidates/export.csv", tags=["candidates"])
    def export_candidates_csv(
        store: Store,
        strategy: str | None = Query(default=None, max_length=64),
        decision: str | None = Query(default=None, max_length=32),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=10_000, ge=1, le=10_000),
        include_backfill: bool = Query(default=False),
    ) -> Response:
        rows = store.candidates_list_payload(
            strategy=strategy,
            decision=decision,
            start=start,
            end=end,
            limit=limit,
            include_backfill=include_backfill,
        )
        columns = [
            ("date", "日期"),
            ("code", "代码"),
            ("name", "名称"),
            ("decision", "裁决"),
            ("score", "评分"),
            ("reason", "理由"),
            ("pool_id", "候选池"),
            ("rule_version", "战法"),
        ]
        return _csv_attachment(rows, columns, "candidates.csv")

    @router.get("/api/alerts/today", tags=["plans"])
    def today_alerts(store: Store) -> list[dict[str, Any]]:
        from src.review.application.alerts import today_alerts_payload

        try:
            from src.market import open_market_hot

            with open_market_hot() as market:
                return today_alerts_payload(store, market)
        except Exception:
            logger.debug("热读库不可用，触价提醒降级为无报价", exc_info=True)
            return today_alerts_payload(store, None)

    @router.get("/api/reviews", tags=["review"])
    def reviews(
        store: Store, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        return store.reviews_payload(limit=limit)

    @router.get("/api/pools", tags=["candidates"])
    def pools(store: Store) -> list[dict[str, Any]]:
        return store.pool_dates_payload()

    @router.get("/api/pools/day", tags=["candidates"])
    def pool_day(
        store: Store,
        date_value: str | None = Query(default=None, alias="date"),
        pool_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return store.pool_day_payload(date_value, pool_id)

    @router.post("/api/candidates", status_code=201, tags=["candidates"])
    def create_candidate(
        payload: CandidateInput, store: Store, _: WriteAccess
    ) -> dict[str, str]:
        return {"id": store.record_candidate(**payload.model_dump())}

    @router.delete("/api/candidates/{candidate_id}", tags=["candidates"])
    def delete_candidate(
        candidate_id: str, store: Store, _: WriteAccess
    ) -> dict[str, bool]:
        if not store.delete_candidate(candidate_id):
            raise HTTPException(status_code=404, detail=f"未找到候选：{candidate_id}")
        return {"removed": True}

    @router.post("/api/candidates/batch-delete", tags=["candidates"])
    def batch_delete_candidates(
        payload: CandidateBatchDeleteInput,
        store: Store,
        _: WriteAccess,
    ) -> dict[str, int]:
        return {"removed": store.delete_candidates(payload.ids)}

    @router.post("/api/plans", status_code=201, tags=["plans"])
    def create_plan(payload: PlanInput, store: Store, _: WriteAccess) -> dict[str, str]:
        return {"id": store.record_plan(**payload.model_dump())}

    @router.post("/api/reviews", status_code=201, tags=["review"])
    def create_review(payload: ReviewInput, store: Store, _: WriteAccess) -> dict[str, str]:
        return {"id": store.record_review(**payload.model_dump())}

    return router
