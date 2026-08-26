"""历史股票池和 point-in-time 事实的独立 HTTP 路由。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.research.api.temporal_models import (
    MembershipSnapshotImportRequest,
    MembershipSnapshotRequest,
    PointInTimeFactImportRequest,
    PointInTimeFactRequest,
)
from src.research.api.write_access import require_configured_research_write_access
from src.research.domain.temporal import TemporalDataError
from src.research.infrastructure import (
    MembershipSnapshotStore,
    PointInTimeFactStore,
    TemporalStoreError,
)


def _error(exc: TemporalStoreError | TemporalDataError) -> HTTPException:
    message = str(exc)
    if "已存在且内容不同" in message:
        return HTTPException(status_code=409, detail=message)
    if "无法读取" in message or "格式无效" in message:
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=422, detail=message)


def build_research_temporal_router(
    *,
    write_dependency: Callable[..., Any] | None = None,
    membership_store_factory: Callable[[], MembershipSnapshotStore] | None = None,
    fact_store_factory: Callable[[], PointInTimeFactStore] | None = None,
) -> APIRouter:
    """构造 PIT 写入接口；所有写入必须经过组合根鉴权。"""
    router = APIRouter()
    write_guard = Depends(write_dependency or require_configured_research_write_access)

    def memberships() -> MembershipSnapshotStore:
        return membership_store_factory() if membership_store_factory else MembershipSnapshotStore()

    def facts() -> PointInTimeFactStore:
        return fact_store_factory() if fact_store_factory else PointInTimeFactStore()

    @router.get("/api/research/membership-snapshots", tags=["research"])
    def list_membership_snapshots(
        universe_id: str | None = Query(default=None, min_length=1, max_length=128),
        as_of: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict[str, Any]:
        if as_of and not universe_id:
            raise HTTPException(status_code=422, detail="as_of 查询必须指定 universe_id")
        try:
            rows = memberships().list(universe_id=universe_id)
            response: dict[str, Any] = {
                "items": [item.to_dict() for item in rows],
                "total": len(rows),
            }
            if as_of and universe_id:
                response["resolved"] = memberships().resolve(
                    universe_id=universe_id, as_of=as_of
                ).to_dict()
            return response
        except (TemporalStoreError, TemporalDataError) as exc:
            raise _error(exc) from exc

    @router.post("/api/research/membership-snapshots", tags=["research"], status_code=201)
    def create_membership_snapshot(
        request: MembershipSnapshotRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            snapshot = memberships().record(request.to_domain())
            return {"snapshot": snapshot.to_dict(), "reused": False}
        except (TemporalStoreError, TemporalDataError) as exc:
            raise _error(exc) from exc

    @router.post(
        "/api/research/membership-snapshots/import",
        tags=["research"],
        status_code=201,
    )
    def import_membership_snapshots(
        request: MembershipSnapshotImportRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            snapshots = memberships().record_many(item.to_domain() for item in request.snapshots)
            return {
                "items": [item.to_dict() for item in snapshots],
                "total": len(snapshots),
            }
        except (TemporalStoreError, TemporalDataError) as exc:
            raise _error(exc) from exc

    @router.get("/api/research/point-in-time-facts", tags=["research"])
    def list_point_in_time_facts(
        entity_id: str | None = Query(default=None, min_length=1, max_length=64),
        fact_type: Literal["financial", "event", "other"] | None = Query(default=None),
        as_of: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict[str, Any]:
        if as_of and not entity_id:
            raise HTTPException(status_code=422, detail="as_of 查询必须指定 entity_id")
        try:
            rows = facts().list(entity_id=entity_id)
            if fact_type:
                rows = [item for item in rows if item.fact_type == fact_type]
            response: dict[str, Any] = {
                "items": [item.to_dict() for item in rows],
                "total": len(rows),
            }
            if as_of and entity_id:
                selected = facts().select(as_of=as_of, entity_id=entity_id, fact_type=fact_type)
                response["selected"] = selected.to_dict() if selected else None
            return response
        except (TemporalStoreError, TemporalDataError) as exc:
            raise _error(exc) from exc

    @router.post("/api/research/point-in-time-facts", tags=["research"], status_code=201)
    def create_point_in_time_fact(
        request: PointInTimeFactRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            fact = facts().record(request.to_domain())
            return {"fact": fact.to_dict(), "reused": False}
        except (TemporalStoreError, TemporalDataError) as exc:
            raise _error(exc) from exc

    @router.post(
        "/api/research/point-in-time-facts/import",
        tags=["research"],
        status_code=201,
    )
    def import_point_in_time_facts(
        request: PointInTimeFactImportRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            rows = facts().record_many(item.to_domain() for item in request.facts)
            return {"items": [item.to_dict() for item in rows], "total": len(rows)}
        except (TemporalStoreError, TemporalDataError) as exc:
            raise _error(exc) from exc

    return router


__all__ = ["build_research_temporal_router"]
