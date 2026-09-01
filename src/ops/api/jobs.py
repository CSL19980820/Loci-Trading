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


#: 非主租户建 cron 的最小间隔。真正的数值在 ``src.ops`` 里，这里只是给守卫
#: 函数一个导入失败时的兜底，免得闸门因为 apscheduler 缺失而整个消失。
_FALLBACK_CRON_FLOOR_SECONDS = 300


def guard_system_job_kind(kind: Any, *, action: str) -> None:
    """非主租户一律拒绝系统级 kind（403）。

    调度侧本来有两道挡板（装载 ``tenant_job_rows`` + 执行 ``run_tenant_job``），
    但它们只管**定时**这条路。HTTP 手动触发 ``POST /api/jobs/{id}/run`` 完全绕开
    了它们：一个普通成员点一下就能跑起 ``execute_sync``，独占全局 ``market.db``
    写锁最长 45 分钟（``MARKET_SYNC_STUCK_SEC``），期间所有人的选股一起排队。
    所以 create / update / trigger 三个写口都要各自挡一次。

    主租户（= 管理员、单机存量用户）行为不变。
    """
    from src.ops.application.tenant_jobs import is_system_job_kind
    from src.shared.tenancy import is_primary_tenant

    if not is_system_job_kind(kind) or is_primary_tenant():
        return
    raise HTTPException(
        status_code=403,
        detail=(
            f"当前账号不能{action}系统级任务（kind={kind}）。行情同步 / 热库重建 / "
            "库体检 / 运维清理 / 盘中留存写的是全局共享的行情库，只由主账号跑一份："
            "子账号各跑一份会撞同一个 SQLite 写锁（最长 45 分钟），并把上游行情源"
            "打成限频 403，连主账号原本能跑通的那一份也会一起挂。"
        ),
    )


def guard_tenant_cron_floor(cron: str) -> None:
    """非主租户不得建比 5 分钟更密的 cron（422）。

    ``* * * * *`` 语法完全合法，一条就够一个普通成员每分钟拉起一轮选股，把租户
    线程池长期占满。判据不自己解析 cron 字段，而是让 ``CronTrigger`` 报出接下来
    两次触发的间隔——它怎么理解表达式，闸门就怎么判。
    """
    from src.shared.tenancy import is_primary_tenant

    text = (cron or "").strip()
    if not text or is_primary_tenant():
        return
    floor = _FALLBACK_CRON_FLOOR_SECONDS
    try:
        from src.ops import MIN_TENANT_CRON_INTERVAL_SECONDS, cron_interval_seconds

        floor = int(MIN_TENANT_CRON_INTERVAL_SECONDS)
        interval = cron_interval_seconds(text)
    except ImportError:  # pragma: no cover - 缺 apscheduler 时上游已经 503 了
        return
    except Exception:  # noqa: BLE001 — 算不出来不代表非法，交给 validate_cron 判
        return
    if interval is None or interval >= floor:
        return
    raise HTTPException(
        status_code=422,
        detail=(
            f"定时频率过高：{text!r} 每 {int(interval)} 秒触发一次，"
            f"当前账号最快只能 {floor // 60} 分钟一次。"
            "再密也只会排队等并发槽位，不会更快拿到结果。"
        ),
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
        # 托管任务由 lifespan 与 screen-skill 变更时 ensure；列表只读，避免读接口改写 ops.db
        with _ops() as store:
            return store.list_jobs()

    @router.post("/api/jobs", tags=["jobs"], status_code=201)
    def create_job(payload: JobCreate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import JobQuotaExceeded, OpsError, check_job_quota
            from src.ops import SchedulerError, validate_cron
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        if payload.cron:
            try:
                validate_cron(payload.cron)
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        # 三道闸门都在 API 层：系统级 kind、cron 频率下限、自建条数配额。
        # 它们**不能**下沉到 OpsStore——托管任务的确保路径也走 create_job，
        # 而 ensure 的异常只打一行 warning，闸门放那儿会让启动期静默失败。
        guard_system_job_kind(payload.kind, action="创建")
        guard_tenant_cron_floor(payload.cron)
        with _ops() as store:
            try:
                check_job_quota(store)
            except JobQuotaExceeded as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
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
        guard_tenant_cron_floor(str(fields.get("cron") or ""))
        with _ops() as store:
            existing = store.get_job(job_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"未知任务：{job_id}")
            # 改 cron / 改 enabled 同样是「让系统级任务按我的节奏跑」，一并挡住。
            guard_system_job_kind(existing.get("kind"), action="修改")
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
            # 先取出任务本体：手动触发这条路绕开了调度侧的两道挡板，系统级 kind
            # 必须在这里挡住，否则普通成员点一下就能独占全局行情写锁 45 分钟。
            # 按 id 找不到再按名字找，与 run_job 自己的解析顺序保持一致。
            job = store.get_job(job_id) or store.get_job_by_name(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail=f"未知任务：{job_id}")
            guard_system_job_kind(job.get("kind"), action="手动触发")
            try:
                return run_job(
                    store, job,
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

    @router.get("/api/jobs/quota", tags=["jobs"])
    def job_quota() -> dict[str, Any]:
        """当前账号的自建任务额度：``{used, limit, unlimited, managed}``。

        ``managed`` 是被豁免的系统托管任务条数——不报出来的话，用户看到「上限 5」
        却在列表里数出 12 条，只会以为额度算错了。
        """
        try:
            from src.ops import job_quota_status
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _ops() as store:
            return job_quota_status(store)

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
