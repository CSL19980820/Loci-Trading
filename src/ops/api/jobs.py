"""定时任务 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.legacy.quant_common import (
    JobCreate,
    JobUpdate,
    missing_dependency,
    ops_store,
)


def build_jobs_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    palace_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    def _reload_scheduler() -> None:
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and scheduler.running:
            scheduler.reload()

    @router.get("/api/jobs", tags=["jobs"])
    def list_jobs() -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_jobs()

    @router.post("/api/jobs", tags=["jobs"], status_code=201)
    def create_job(payload: JobCreate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import OpsError
            from src.ops import SchedulerError, validate_cron
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        if payload.cron:
            try:
                validate_cron(payload.cron)
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        with _ops() as store:
            try:
                job_id = store.create_job(
                    name=payload.name, kind=payload.kind, cron=payload.cron,
                    config=payload.config, enabled=payload.enabled,
                )
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)
        _reload_scheduler()
        return job or {}

    @router.patch("/api/jobs/{job_id}", tags=["jobs"])
    def update_job(job_id: str, payload: JobUpdate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import OpsError
            from src.ops import SchedulerError, validate_cron
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        fields = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=422, detail="没有要更新的字段")
        if fields.get("cron"):
            try:
                validate_cron(fields["cron"])
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        with _ops() as store:
            if store.get_job(job_id) is None:
                raise HTTPException(status_code=404, detail=f"未知任务：{job_id}")
            try:
                store.update_job(job_id, **fields)
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)
        _reload_scheduler()
        return job or {}

    @router.delete("/api/jobs/{job_id}", tags=["jobs"])
    def delete_job(job_id: str, _write: None = write_guard) -> dict[str, bool]:
        with _ops() as store:
            if not store.delete_job(job_id):
                raise HTTPException(status_code=404, detail=f"未知任务：{job_id}")
        _reload_scheduler()
        return {"removed": True}

    @router.post("/api/jobs/{job_id}/run", tags=["jobs"])
    def trigger_job(job_id: str, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import JobContext, OpsError, run_job
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _ops() as store:
            try:
                return run_job(
                    store, job_id,
                    context=JobContext(
                        market_db=market_db, ops_store=store, palace_db=palace_db
                    ),
                    trigger="api",
                )
            except OpsError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/api/jobs/runs", tags=["jobs"])
    def list_runs(
        job_id: str | None = Query(default=None),
        status: str | None = Query(default=None, pattern="^(success|failed|running|skipped)$"),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_runs(job_id=job_id, status=status, limit=limit)

    @router.get("/api/jobs/schedule", tags=["jobs"])
    def schedule_status() -> dict[str, Any]:
        """调度器到底在不在跑、下次什么时候触发。

        没有这个接口，"我的定时任务配好了吗"只能靠等到点看结果。
        """
        if scheduler_getter is None:
            return {"running": False, "reason": "本进程未启用调度器", "jobs": []}
        scheduler = scheduler_getter()
        if scheduler is None:
            return {"running": False, "reason": "调度器未初始化", "jobs": []}
        return {"running": scheduler.running, "jobs": scheduler.upcoming()}

    return router
