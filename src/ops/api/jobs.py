"""定时任务 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.ops.api.schemas import JobCreate, JobUpdate
from src.shared.api_deps import missing_dependency, ops_store
from src.shared.paths import market_hot_db


class JobRunBatchDeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=500)


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
        # 托管任务由 lifespan 与 screen-skill 变更时 ensure；列表只读，避免读接口改写 ops.db
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
                        market_db=market_db,
                        market_hot_db=str(market_hot_db()),
                        ops_store=store,
                        palace_db=palace_db,
                    ),
                    trigger="api",
                )
            except OpsError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/api/jobs/runs", tags=["jobs"])
    def list_runs(
        job_id: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        status: str | None = Query(
            default=None,
            pattern="^(success|failed|running|skipped|cancelled|timed_out)$",
        ),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_runs(job_id=job_id, run_id=run_id, status=status, limit=limit)

    @router.post("/api/jobs/runs/{run_id}/cancel", tags=["jobs"], status_code=202)
    def cancel_run(run_id: str, _write: None = write_guard) -> dict[str, Any]:
        """请求协作式取消；执行器到安全检查点后写入 cancelled 终态。"""
        from src.ops import OpsError

        try:
            with _ops() as store:
                run = store.get_run(run_id)
                if run is None:
                    raise HTTPException(status_code=404, detail=f"未知运行：{run_id}")
                if run["status"] != "running":
                    return {
                        "run_id": run_id,
                        "status": run["status"],
                        "cancel_requested": bool(run.get("cancel_requested")),
                    }
                changed = store.request_cancel(run_id)
        except OpsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": run_id,
            "status": "cancellation_requested" if changed else "not_running",
            "cancel_requested": changed,
        }

    @router.post("/api/jobs/runs/batch-delete", tags=["jobs"])
    def batch_delete_runs(
        payload: JobRunBatchDeleteInput,
        _write: None = write_guard,
    ) -> dict[str, int]:
        from src.ops import OpsError

        try:
            with _ops() as store:
                removed = store.delete_runs(payload.ids)
        except OpsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"removed": removed}

    @router.get("/api/jobs/schedule", tags=["jobs"])
    def schedule_status() -> dict[str, Any]:
        """调度器到底在不在跑、下次什么时候触发。

        没有这个接口，"我的定时任务配好了吗"只能靠等到点看结果。
        调度器未启动时仍按 cron 推算 next_run_at，避免详情页永远是「—」。
        """
        from src.ops.infrastructure.scheduler import preview_upcoming_jobs

        reason: str | None = None
        running = False
        live: dict[str, dict[str, Any]] = {}
        timezone = "Asia/Shanghai"
        if scheduler_getter is None:
            reason = "本进程未启用调度器"
        else:
            scheduler = scheduler_getter()
            if scheduler is None:
                reason = "调度器未初始化"
            else:
                running = bool(scheduler.running)
                timezone = getattr(scheduler, "timezone", timezone) or timezone
                if not running:
                    reason = "调度器未运行"
                live = {item["id"]: item for item in scheduler.upcoming()}

        with _ops() as store:
            jobs = store.list_jobs(enabled_only=True)
        return {
            "running": running,
            "reason": reason,
            "jobs": preview_upcoming_jobs(jobs, timezone=timezone, live=live),
        }

    return router
