"""对话式 Skill Run HTTP（runs / reply / events）。"""
from __future__ import annotations

import asyncio

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.ops.api.schemas import SkillRunCreate, SkillRunReply
from src.shared.api_deps import missing_dependency
from src.shared.tenancy import spawn_tenant_thread

logger = logging.getLogger(__name__)


def register_skill_run_routes(
    router: APIRouter,
    *,
    write_guard: Any,
    ops_factory: Callable[[], Any],
    market_db: str | None,
    ops_db: str | None,
    palace_db: str | None,
) -> None:
    def _ops():
        return ops_factory()

    def _skill_job_context(store):
        from src.ops.application.jobs import JobContext
        from src.shared.paths import market_hot_db

        return JobContext(
            market_db=market_db,
            market_hot_db=str(market_hot_db()),
            ops_store=store,
            palace_db=palace_db,
        )

    def _public_run(state: dict[str, Any]) -> dict[str, Any]:
        """对外脱敏：不把完整 messages 堆给列表/轮询。"""
        return {
            "id": state.get("id"),
            "skill": state.get("skill"),
            "provider": state.get("provider"),
            "status": state.get("status"),
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
            "pending_ask": state.get("pending_ask") or {},
            "subagents": state.get("subagents") or [],
            "error": state.get("error") or "",
            "result": {
                k: v
                for k, v in (state.get("result") or {}).items()
                if k
                in {
                    "output",
                    "rounds",
                    "model",
                    "stopped_reason",
                    "pending_ask",
                    "tool_calls",
                    "tool_trace",
                    "subagents",
                    "skill",
                    "skill_version",
                    "provider",
                }
            },
        }

    @router.post("/api/skills/{slug}/runs", tags=["skills"], status_code=201)
    def start_skill_run_api(
        slug: str, payload: SkillRunCreate, _write: None = write_guard
    ) -> dict[str, Any]:
        """对话式 Skill Run：支持 agents[] 弹药 + ask_user HITL。"""
        try:
            from src.ops import OpsStore, skill_runs
            from src.ops.application.jobs import JobError
            from src.ops.application.skill_runtime import drive_skill_run
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        skill = resolve_skill(slug)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"未找到技能：{slug}")
        if not skill.get("enabled", True):
            raise HTTPException(status_code=422, detail=f"技能 {slug} 已停用")

        cfg = dict(payload.config or {})
        if payload.model:
            cfg["model"] = payload.model
        state = skill_runs.create_run(skill=slug, provider=payload.provider, config=cfg)
        run_id = state["id"]

        if payload.background:

            def worker() -> None:
                try:
                    with OpsStore(ops_db) as store:
                        drive_skill_run(
                            run_id,
                            context=_skill_job_context(store),
                            allow_hitl=True,
                            run_subagents_first=True,
                        )
                except Exception as exc:
                    logger.exception("background skill run %s failed", run_id)
                    failed = skill_runs.load_run(run_id)
                    if failed is not None:
                        failed["status"] = "error"
                        failed["error"] = str(exc)
                        skill_runs.save_run(failed)
                        skill_runs.append_event(run_id, {"type": "error", "message": str(exc)})

            # 不能写成 threading.Thread(target=worker, ...)：ContextVar 不跨线程边界，
            # worker 里的 skill_runs.*（skill_runs_dir()，租户私有）与 resolve_skill
            # （skill_root()，同样租户私有）会全部解析到主租户目录，于是 run 记录建在
            # B 的目录、执行与回写落在管理员目录（split-brain），而且真正被执行的是
            # **管理员的技能包**——B 的同名技能改了什么都不作数。不报错，只是错人。
            spawn_tenant_thread(worker, name=f"skill-run-{run_id}")
            return {"run": _public_run(state)}

        with _ops() as store:
            try:
                outcome = drive_skill_run(
                    run_id,
                    context=_skill_job_context(store),
                    allow_hitl=True,
                    run_subagents_first=True,
                )
            except JobError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "run": _public_run(outcome["run"]),
            "result": outcome.get("result"),
        }

    @router.get("/api/skill-runs/{run_id}", tags=["skills"])
    def get_skill_run(run_id: str) -> dict[str, Any]:
        try:
            from src.ops import skill_runs
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        state = skill_runs.load_run(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"找不到 run：{run_id}")
        return _public_run(state)

    @router.post("/api/skill-runs/{run_id}/reply", tags=["skills"])
    def reply_skill_run_api(
        run_id: str, payload: SkillRunReply, _write: None = write_guard
    ) -> dict[str, Any]:
        try:
            from src.ops import OpsStore, skill_runs
            from src.ops.application.jobs import JobError
            from src.ops.application.skill_runtime import reply_skill_run
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        state = skill_runs.load_run(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"找不到 run：{run_id}")
        if payload.background:
            claimed = skill_runs.claim_user_reply(run_id, payload.reply)
            if claimed is None:
                current = skill_runs.load_run(run_id) or state
                raise HTTPException(
                    status_code=422,
                    detail=f"run 状态不是 waiting_user：{current.get('status')}",
                )

            def worker() -> None:
                try:
                    with OpsStore(ops_db) as store:
                        from src.ops.application.skill_runtime import drive_skill_run

                        drive_skill_run(
                            run_id,
                            context=_skill_job_context(store),
                            allow_hitl=True,
                            run_subagents_first=False,
                            user_reply=payload.reply,
                        )
                except Exception as exc:
                    logger.exception("background skill reply %s failed", run_id)
                    failed = skill_runs.load_run(run_id)
                    if failed is not None:
                        failed["status"] = "error"
                        failed["error"] = str(exc)
                        skill_runs.save_run(failed)

            # 同 start_skill_run_api：HITL 续跑仍要落在**发起回复那个租户**的目录里，
            # 裸 threading.Thread 会把续跑写进管理员目录。见 src/shared/tenancy.py。
            spawn_tenant_thread(worker, name=f"skill-reply-{run_id}")
            refreshed = skill_runs.load_run(run_id) or state
            return {"run": _public_run(refreshed)}

        with _ops() as store:
            try:
                outcome = reply_skill_run(
                    run_id, reply=payload.reply, context=_skill_job_context(store)
                )
            except JobError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "run": _public_run(outcome["run"]),
            "result": outcome.get("result"),
        }

    @router.get("/api/skill-runs/{run_id}/events", tags=["skills"])
    def skill_run_events(
        run_id: str,
        after: int = Query(default=0, ge=0),
        stream: bool = Query(default=False),
    ):
        """事件流：默认 JSON 轮询；``stream=1`` 时 SSE。"""
        try:
            from src.ops import skill_runs
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        if skill_runs.load_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"找不到 run：{run_id}")

        if not stream:
            events, cursor = skill_runs.read_events(run_id, after=after)
            return {"run_id": run_id, "events": events, "next_after": cursor}

        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import StreamingResponse
        import json as _json

        async def generate():
            """异步生成器:等待期间不占线程池令牌。

            这里**曾经是同步生成器 + `time.sleep(1)`**。Starlette 对同步迭代器走
            `iterate_in_threadpool`,每次 `next()` 占一个 AnyIO 令牌,而 sleep 正好
            落在 `next()` 里——空闲时每轮实打实占满 1 秒,`idle < 120` 意味着单条连接
            最长两分钟一直占着。该池默认 40 个令牌且被全仓 `def` 端点共用
            (本仓端点 100% 是 `def`),实测 45 条并发流会让 `/api/health` 时延
            从 2ms 劣化到 31ms。
            """
            cursor = after
            idle = 0
            while idle < 120:  # ~2 分钟无新事件则结束(前端可重连)
                previous_cursor = cursor
                batch, next_cursor = await run_in_threadpool(skill_runs.read_events, run_id, after=cursor)
                if batch:
                    idle = 0
                    for event in batch:
                        cursor = int(event.get("_seq", cursor)) + 1
                        yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
                    cursor = next_cursor
                    state = await run_in_threadpool(skill_runs.load_run, run_id) or {}
                    if state.get("status") in {"done", "error", "waiting_user"} and next_cursor - previous_cursor < 200:
                        payload = _json.dumps(
                            {"type": "status", "status": state.get("status")}, ensure_ascii=False
                        )
                        yield f"data: {payload}\n\n"
                        if state.get("status") in {"done", "error"} and next_cursor - previous_cursor < 200:
                            break
                else:
                    cursor = next_cursor
                    state = await run_in_threadpool(skill_runs.load_run, run_id) or {}
                    if state.get("status") in {"done", "error"}:
                        yield f'data: {_json.dumps({"type": "status", "status": state["status"]})}\n\n'
                        break
                    idle += 1
                    yield ": ping\n\n"
                    await asyncio.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

