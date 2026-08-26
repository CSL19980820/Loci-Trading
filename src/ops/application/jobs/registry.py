"""执行器注册表与统一 run_job 入口。"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Any

from src.ops.application.jobs.backtest import execute_backtest
from src.ops.application.jobs.compare import execute_compare
from src.ops.application.jobs.context import (
    Executor,
    JobCancelled,
    JobContext,
    JobSkipped,
    JobTimedOut,
)
from src.ops.application.jobs.data_quality import execute_data_quality
from src.ops.application.jobs.hot_rebuild import execute_hot_rebuild
from src.ops.application.jobs.intel_fetch import execute_intel_fetch
from src.ops.application.jobs.market_gate import (
    market_heavy_slot,
    skip_reason_for_intraday_sync,
)
from src.ops.application.jobs.notify import _maybe_push_wecom, execute_notify
from src.ops.application.jobs.optimize import execute_optimize
from src.ops.application.jobs.outcome import execute_outcome
from src.ops.application.jobs.paper_quant import (
    execute_alert_scan,
    execute_paper_eod,
    execute_strategy_monitor,
)
from src.ops.application.jobs.prune import execute_prune
from src.ops.application.jobs.screen import execute_screen
from src.ops.application.jobs.skill import execute_skill
from src.ops.application.jobs.skill_watch import execute_skill_watch
from src.ops.application.jobs.sync import execute_sync
from src.ops.infrastructure.store import OpsError, OpsStore
from src.shared.observability import (
    correlation_scope,
    current as current_observation,
    event as observation_event,
    span as observation_span,
)

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
    "outcome": execute_outcome,
    "hot_rebuild": execute_hot_rebuild,
    "data_quality": execute_data_quality,
    "intel_fetch": execute_intel_fetch,
    "skill_watch": execute_skill_watch,
    "alert_scan": execute_alert_scan,
    "strategy_monitor": execute_strategy_monitor,
    "paper_eod": execute_paper_eod,
}


def _maybe_seed_nextday_plan(
    *,
    store: OpsStore,
    job: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """选股/技能成功且启用 paper_quant 时，自动写次日预案。

    仅 ``screen`` / ``skill``（收盘选股链路）种子并可推企微。
    ``skill_watch`` 盘中监测只推监测摘要，禁止改写/推送「次日预案」。
    """
    kind = str(job.get("kind") or "")
    if kind not in {"screen", "skill"}:
        return
    picks = result.get("picks")
    if not isinstance(picks, list) or not picks:
        return
    config = dict(job.get("config") or {})
    # skill 任务存 config.skill；runner 出口带 result.slug。
    # 禁止落到「监测·龙回头」这类中文任务名去建错舱。
    slug = str(
        config.get("slug")
        or config.get("skill")
        or result.get("slug")
        or result.get("skill")
        or result.get("strategy")
        or ""
    ).strip()
    if slug.startswith("screen:"):
        slug = slug[len("screen:") :]
    if slug.startswith("监测·") or ("·" in slug and any("\u4e00" <= c <= "\u9fff" for c in slug)):
        logger.warning("refuse seeding nextday plan with non-slug key %r", slug)
        return
    if not slug or "/" in slug or " " in slug:
        return
    from src.ops.application.retire_dragon_return import is_retired_paper_cabin

    if is_retired_paper_cabin(slug):
        return
    cabin = store.ensure_paper_cabin(slug)
    from src.ops.application.jobs.paper_quant_support import _paper_quant_config

    paper = _paper_quant_config(cabin.get("config") if isinstance(cabin.get("config"), dict) else {})
    if not (paper.get("enabled") or config.get("paper_quant_enabled")):
        return
    try:
        from src.ops.application.jobs.paper_quant import generate_nextday_plan

        plan = generate_nextday_plan(
            store,
            slug=slug,
            picks=[p for p in picks if isinstance(p, dict)],
            source=kind,
            notify=False,
        )
        result["nextday_plan"] = {
            "slug": slug,
            "plan_date": plan.get("plan_date"),
            "id": plan.get("id"),
        }
    except Exception:
        logger.exception("seed nextday plan failed for %s", slug)


def _job_timeout_seconds(job: dict[str, Any]) -> float | None:
    config = job.get("config") if isinstance(job.get("config"), dict) else {}
    raw = config.get("timeout_sec", config.get("timeout_seconds"))
    try:
        value = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _existing_run_result(
    store: OpsStore,
    run_id: str,
    *,
    idempotent: bool = False,
) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise OpsError("任务运行不存在或已被删除")
    if run["status"] == "running":
        return {
            "run_id": run_id,
            "status": "skipped",
            "reason": "任务正在执行",
        }
    return {
        "run_id": run_id,
        "status": run["status"],
        "idempotent": idempotent,
        "result": run.get("result") or {},
        **({"error": run["error_text"]} if run.get("error_text") else {}),
    }


def _job_finished_event(
    context: JobContext,
    *,
    level: int,
    kind: str,
    status: str,
) -> None:
    """终态落库后仍沿用同一条 run/job 相关性。"""
    with correlation_scope(
        trace_id=context.trace_id,
        run_id=context.run_id,
        job_id=context.job_id,
        source_id=context.source_id,
        tool_receipt_id=context.tool_receipt_id,
    ):
        observation_event(
            logger,
            level,
            "job_finished",
            fields={"operation": "execute", "kind": kind, "status": status},
        )


def _finish_skipped(
    *,
    store: OpsStore,
    context: JobContext,
    run_id: str,
    kind: str,
    reason: str,
    duration_ms: int,
) -> dict[str, Any]:
    """本轮无需执行：落 skipped 终态。不推企微、不种预案——没发生的事不播报。"""
    result = {"skipped": True, "reason": reason}
    try:
        store.finish_run(
            run_id,
            status="skipped",
            result=result,
            duration_ms=duration_ms,
        )
    except OpsError:
        return _existing_run_result(store, run_id)
    _job_finished_event(context, level=logging.INFO, kind=kind, status="skipped")
    return {
        "run_id": run_id,
        "status": "skipped",
        "duration_ms": duration_ms,
        "result": result,
    }


def run_job(
    store: OpsStore,
    job: dict[str, Any] | str,
    *,
    context: JobContext | None = None,
    trigger: str = "manual",
    run_id: str | None = None,
    idempotency_key: str | None = None,
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

    if idempotency_key and not run_id:
        existing = store.get_run_by_idempotency(idempotency_key)
        if existing is not None:
            return _existing_run_result(store, str(existing["id"]), idempotent=True)

    if not run_id:
        run_id, claimed = store.claim_run(
            job,
            trigger=trigger,
            idempotency_key=idempotency_key,
        )
        if not claimed:
            if idempotency_key:
                return _existing_run_result(store, run_id, idempotent=True)
            logger.info("任务 %s 已在运行，跳过重复触发", job.get("name"))
            return {
                "run_id": run_id,
                "status": "skipped",
                "reason": "任务正在执行",
            }
    else:
        existing = store.get_run(run_id)
        if existing is None:
            raise OpsError("任务运行不存在或已被删除")
        # 即时调用的旧适配器可能只提供 start/finish；只有真实的终态
        # 字符串才阻止执行，避免把 mock/兼容 store 的占位对象误判成终态。
        existing_status = existing.get("status") if isinstance(existing, dict) else None
        if existing_status and existing_status != "running":
            return _existing_run_result(store, run_id, idempotent=True)

    inherited = current_observation()
    timeout_seconds = _job_timeout_seconds(job)
    ctx = context or JobContext(ops_store=store)
    if ctx.ops_store is None:
        ctx.ops_store = store
    ctx.bind_run(
        run_id=run_id,
        job_id=str(job.get("id") or ""),
        trace_id=inherited.trace_id or ctx.trace_id,
        timeout_seconds=timeout_seconds,
    )
    ctx.heartbeat()
    started = time.monotonic()
    try:
        with observation_span(
            "job.execute",
            trace_id=ctx.trace_id,
            run_id=run_id,
            job_id=str(job.get("id") or ""),
            labels={"component": "ops", "operation": "execute", "kind": kind},
        ):
            skip_reason = skip_reason_for_intraday_sync(str(kind), job)
            if skip_reason:
                return _finish_skipped(
                    store=store,
                    context=ctx,
                    run_id=run_id,
                    kind=kind,
                    reason=skip_reason,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            with market_heavy_slot(str(kind), str(job.get("name") or job.get("id") or "")):
                ctx.check_cancelled()
                result = executor(dict(job.get("config") or {}), ctx)
                ctx.heartbeat()
                ctx.check_cancelled()
    except JobSkipped as exc:
        # 同批写入已有人在做（行情闸门），不是故障：不刷红运维页、不推企微。
        logger.info("任务 %s 本轮跳过：%s", job.get("name"), exc)
        return _finish_skipped(
            store=store,
            context=ctx,
            run_id=run_id,
            kind=kind,
            reason=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except JobCancelled as exc:
        duration = int((time.monotonic() - started) * 1000)
        detail = f"{type(exc).__name__}: {exc}"
        try:
            store.finish_run(
                run_id,
                status="cancelled",
                error=detail,
                duration_ms=duration,
            )
        except OpsError:
            return _existing_run_result(store, run_id)
        _job_finished_event(
            ctx,
            level=logging.WARNING,
            kind=kind,
            status="cancelled",
        )
        return {"run_id": run_id, "status": "cancelled", "error": str(exc)}
    except JobTimedOut as exc:
        duration = int((time.monotonic() - started) * 1000)
        detail = f"{type(exc).__name__}: {exc}"
        try:
            store.finish_run(
                run_id,
                status="timed_out",
                error=detail,
                duration_ms=duration,
            )
        except OpsError:
            return _existing_run_result(store, run_id)
        _job_finished_event(
            ctx,
            level=logging.WARNING,
            kind=kind,
            status="timed_out",
        )
        return {"run_id": run_id, "status": "timed_out", "error": str(exc)}
    except Exception as exc:
        duration = int((time.monotonic() - started) * 1000)
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
        push_meta = _maybe_push_wecom(
            store=store, job=job, status="failed", result=None, error=str(exc)
        )
        try:
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
        except OpsError:
            return _existing_run_result(store, run_id)
        logger.warning("任务 %s 执行失败：%s", job.get("name"), exc)
        _job_finished_event(
            ctx,
            level=logging.WARNING,
            kind=kind,
            status="failed",
        )
        return {"run_id": run_id, "status": "failed", "error": str(exc)}

    # 先定最终 status，再推企微 / 种子预案，避免库内红、企微绿
    status = "success"
    if (
        isinstance(result, dict)
        and result.get("skipped")
        and kind in {"notify", "intel_fetch", "skill_watch", "strategy_monitor", "paper_eod"}
    ):
        status = "skipped"
    elif (
        isinstance(result, dict)
        and kind == "intel_fetch"
        and not result.get("skipped")
        and int((result.get("stats") or {}).get("failed") or 0) > 0
    ):
        # 部分 MCP 失败不得假绿
        status = "failed"
    elif (
        isinstance(result, dict)
        and kind == "skill_watch"
        and isinstance(result.get("paper_monitor"), dict)
        and result["paper_monitor"].get("status") == "failed"
    ):
        # 统一盘中任务里纸面动作是同一职责，失败不能被扫描成功掩盖。
        status = "failed"
    elif (
        isinstance(result, dict)
        and kind == "sync"
        and int(result.get("failed") or 0) > 0
    ):
        # 历史日 K 硬失败不得假绿（现价软跳过不计入 failed）
        status = "failed"

    if isinstance(result, dict):
        push_meta = _maybe_push_wecom(store=store, job=job, status=status, result=result)
        if push_meta:
            result = {**result, **push_meta}
        if status == "success":
            _maybe_seed_nextday_plan(store=store, job=job, result=result)

    duration = int((time.monotonic() - started) * 1000)
    try:
        store.finish_run(run_id, status=status, result=result, duration_ms=duration)
    except OpsError:
        # stale recovery / another idempotent caller may have won the terminal transition.
        return _existing_run_result(store, run_id)
    _job_finished_event(
        ctx,
        level=logging.INFO if status in {"success", "skipped"} else logging.WARNING,
        kind=kind,
        status=status,
    )
    return {"run_id": run_id, "status": status, "duration_ms": duration, "result": result}
