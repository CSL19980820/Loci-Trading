"""Skill 包与对话式 Skill Run HTTP。"""
from __future__ import annotations

from pathlib import Path
import logging
import tempfile
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.app.legacy.quant_common import (
    MAX_UPLOAD_BYTES,
    SkillGenerateRequest,
    SkillRunCreate,
    SkillRunReply,
    missing_dependency,
    ops_store,
)

logger = logging.getLogger(__name__)


def build_skills_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    @router.get("/api/skills", tags=["skills"])
    def list_skills() -> list[dict[str, Any]]:
        """扫描 data/skills/*/SKILL.md（不写 ops.db）。"""
        try:
            from src.ops.application.skills import discover_skills
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return [
            {k: v for k, v in pkg.to_record().items() if k != "instructions"}
            for pkg in discover_skills()
        ]

    @router.get("/api/skills/{slug}", tags=["skills"])
    def get_skill(slug: str) -> dict[str, Any]:
        try:
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None:
            raise HTTPException(
                status_code=404,
                detail=f"未找到技能：{slug}（请复制到 data/skills/{slug}/SKILL.md）",
            )
        return skill

    @router.post("/api/skills/rescan", tags=["skills"])
    def rescan_skills(_write: None = write_guard) -> dict[str, Any]:
        """重新扫描 data/skills（只读磁盘，不写库）。"""
        try:
            from src.ops.application.skills import discover_skills
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        packages = discover_skills()
        return {"count": len(packages), "slugs": [pkg.slug for pkg in packages]}

    @router.post("/api/skills", tags=["skills"], status_code=201)
    async def install_skill_api(
        file: UploadFile = File(...), _write: None = write_guard
    ) -> dict[str, Any]:
        """上传并安装技能包 zip 到 data/skills/。"""
        try:
            from src.ops import install_skill
            from src.ops.application.skills import SkillError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=422, detail="技能包必须是 .zip 文件")

        with tempfile.TemporaryDirectory(prefix="skill-upload-") as tmp:
            target = Path(tmp) / "package.zip"
            written = 0
            with open(target, "wb") as handle:
                while chunk := await file.read(1024 * 256):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"技能包超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                        )
                    handle.write(chunk)
            try:
                package = install_skill(target)
            except SkillError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        record = package.to_record()
        return {key: value for key, value in record.items() if key != "instructions"}

    @router.delete("/api/skills/{slug}", tags=["skills"])
    def remove_skill(slug: str, _write: None = write_guard) -> dict[str, bool]:
        try:
            from src.ops import uninstall_skill
            from src.ops.application.skills import SkillError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            removed_fs = uninstall_skill(slug)
        except SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not removed_fs:
            raise HTTPException(status_code=404, detail=f"未安装的技能：{slug}")
        return {"removed": True}


    def _skill_job_context(store):
        from src.ops.application.jobs import JobContext

        return JobContext(market_db=market_db, ops_store=store, palace_db=palace_db)

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

            threading.Thread(target=worker, daemon=True, name=f"skill-run-{run_id}").start()
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
        if state.get("status") != "waiting_user":
            raise HTTPException(
                status_code=422,
                detail=f"run 状态不是 waiting_user：{state.get('status')}",
            )

        if payload.background:
            # 先标 running，避免重复 reply
            state["status"] = "running"
            state["pending_ask"] = {}
            skill_runs.save_run(state)
            skill_runs.append_event(run_id, {"type": "user_reply", "text": payload.reply[:500]})

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

            threading.Thread(target=worker, daemon=True, name=f"skill-reply-{run_id}").start()
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
            events = skill_runs.list_events(run_id, after=after)
            return {"run_id": run_id, "events": events, "next_after": after + len(events)}

        from fastapi.responses import StreamingResponse
        import json as _json

        def generate():
            cursor = after
            idle = 0
            while idle < 120:  # ~2 分钟无新事件则结束（前端可重连）
                batch = skill_runs.list_events(run_id, after=cursor)
                if batch:
                    idle = 0
                    for event in batch:
                        cursor = int(event.get("_seq", cursor)) + 1
                        yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
                    state = skill_runs.load_run(run_id) or {}
                    if state.get("status") in {"done", "error", "waiting_user"}:
                        yield f"data: {_json.dumps({'type': 'status', 'status': state.get('status')}, ensure_ascii=False)}\n\n"
                        if state.get("status") in {"done", "error"}:
                            break
                else:
                    idle += 1
                    yield ": ping\n\n"
                    time.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/skills/generate", tags=["skills"])
    def generate_skill_md(
        payload: SkillGenerateRequest, _write: None = write_guard
    ) -> dict[str, Any]:
        """根据描述让 AI 生成 SKILL.md 内容。

        返回生成的文本，用户可以复制或直接下载为 .zip 安装包。
        此接口不自动安装，安装走 POST /api/skills（上传 zip）。
        """
        try:
            from src.ai import resolve_config
            from src.strategy.application.converter import build_skill_prompt
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        with _ops() as store:
            try:
                provider = resolve_config(
                    store, payload.provider,
                    model=payload.model,
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"供应商配置错误：{exc}") from exc

        prompt = build_skill_prompt(
            description=payload.description,
            slug=payload.slug,
            name=payload.name,
            context_hints=payload.context_hints,
        )
        try:
            from src.ai import ChatMessage, chat
            messages = [ChatMessage(role="user", content=prompt)]
            response = chat(
                provider,
                messages,
                max_tokens=2048,
                temperature=0.3,
                thinking=payload.thinking,
            )
            skill_md = response.text.strip()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM 请求失败：{exc}") from exc

        return {
            "slug": payload.slug,
            "name": payload.name,
            "skill_md": skill_md,
        }

    return router
