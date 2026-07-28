"""执行器注册表与统一 run_job 入口。"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Any

from src.ops.application.jobs.backtest import execute_backtest
from src.ops.application.jobs.compare import execute_compare
from src.ops.application.jobs.context import Executor, JobContext
from src.ops.application.jobs.notify import _maybe_push_wecom, execute_notify
from src.ops.application.jobs.optimize import execute_optimize
from src.ops.application.jobs.prune import execute_prune
from src.ops.application.jobs.screen import execute_screen
from src.ops.application.jobs.skill import execute_skill
from src.ops.application.jobs.sync import execute_sync
from src.ops.infrastructure.store import OpsError, OpsStore

logger = logging.getLogger(__name__)

EXECUTORS: dict[str, Executor] = {
    "sync": execute_sync,
    "screen": execute_screen,
    "backtest": execute_backtest,
    "compare": execute_compare,
    "optimize": execute_optimize,
    "prune": execute_prune,
    "skill": execute_skill,
    "notify": execute_notify,
}


def run_job(
    store: OpsStore,
    job: dict[str, Any] | str,
    *,
    context: JobContext | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """执行一个任务并完整记录过程。

    无论成功失败都会留下一条 job_runs 记录。定时任务最怕的不是失败，
    是"静默地一直失败"——半年后才发现每天的盘后同步其实早就挂了。
    """
    if isinstance(job, str):
        resolved = store.get_job(job) or store.get_job_by_name(job)
        if resolved is None:
            raise OpsError(f"未知任务：{job}")
        job = resolved

    kind = job["kind"]
    executor = EXECUTORS.get(kind)
    if executor is None:
        raise OpsError(f"没有 {kind} 类型的执行器")

    ctx = context or JobContext(ops_store=store)
    if ctx.ops_store is None:
        ctx.ops_store = store

    run_id = store.start_run(job, trigger=trigger)
    started = time.monotonic()
    try:
        result = executor(dict(job.get("config") or {}), ctx)
    except Exception as exc:
        duration = int((time.monotonic() - started) * 1000)
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
        push_meta = _maybe_push_wecom(
            store=store, job=job, status="failed", result=None, error=str(exc)
        )
        if push_meta:
            # 失败记录仍以 error 为主；推送痕迹写进 result 便于排查
            store.finish_run(
                run_id,
                status="failed",
                error=detail,
                result=push_meta,
                duration_ms=duration,
            )
        else:
            store.finish_run(run_id, status="failed", error=detail, duration_ms=duration)
        logger.warning("任务 %s 执行失败：%s", job.get("name"), exc)
        return {"run_id": run_id, "status": "failed", "error": str(exc)}

    if isinstance(result, dict):
        push_meta = _maybe_push_wecom(store=store, job=job, status="success", result=result)
        if push_meta:
            result = {**result, **push_meta}

    # notify 模板可主动 skipped
    status = "success"
    if isinstance(result, dict) and result.get("skipped") and kind == "notify":
        status = "skipped"

    duration = int((time.monotonic() - started) * 1000)
    store.finish_run(run_id, status=status, result=result, duration_ms=duration)
    return {"run_id": run_id, "status": status, "duration_ms": duration, "result": result}
