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
    SkillJobConfig,
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
            try:
                scheduler.reload()
            except Exception:
                logger.exception("reload scheduler after skill job change failed")

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
            if str(pkg.metadata.get("capability") or "").strip().lower() != "screen"
        ]

    @router.get("/api/skills/{slug}", tags=["skills"])
    def get_skill(slug: str) -> dict[str, Any]:
        try:
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None or str((skill.get("metadata") or {}).get("capability") or "").strip().lower() == "screen":
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
        agent_skills = [
            pkg for pkg in packages
            if str(pkg.metadata.get("capability") or "").strip().lower() != "screen"
        ]
        return {"count": len(agent_skills), "slugs": [pkg.slug for pkg in agent_skills]}

    @router.post("/api/skills", tags=["skills"], status_code=201)
    def install_skill_api(
        file: UploadFile = File(...), _write: None = write_guard
    ) -> dict[str, Any]:
        """上传并安装技能包 zip 到 data/skills/。"""
        try:
            from src.ops import install_skill
            from src.ops.application.screen import ScreenPackageError, read_screen_archive
            from src.ops.application.screen.storage import archive_declares_screen_capability
            from src.ops.application.skills import SkillError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=422, detail="技能包必须是 .zip 文件")

        with tempfile.TemporaryDirectory(prefix="skill-upload-") as tmp:
            target = Path(tmp) / "package.zip"
            written = 0
            with open(target, "wb") as handle:
                while chunk := file.file.read(1024 * 256):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"技能包超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                        )
                    handle.write(chunk)
            try:
                read_screen_archive(target)
            except ScreenPackageError as exc:
                if archive_declares_screen_capability(target):
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            else:
                raise HTTPException(
                    status_code=422,
                    detail="capability=screen 的包请走 /api/screen-skills/import",
                )
            try:
                package = install_skill(target)
            except SkillError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        record = package.to_record()
        return {key: value for key, value in record.items() if key != "instructions"}

    @router.delete("/api/skills/{slug}", tags=["skills"])
    def remove_skill(slug: str, _write: None = write_guard) -> dict[str, bool]:
        try:
            from src.ops import resolve_skill, uninstall_skill
            from src.ops.application.skills import SkillError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is not None and str((skill.get("metadata") or {}).get("capability") or "").strip().lower() == "screen":
            raise HTTPException(status_code=404, detail=f"未安装的技能：{slug}")
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

    @router.get("/api/skills/{slug}/job", tags=["skills"])
    def get_skill_job(slug: str) -> dict[str, Any]:
        """读取技能绑定的定时任务（name=skill:{slug}）。"""
        try:
            from src.ops.application.skills import resolve_skill
            from src.ops.application.trading_schedule import preview_trading_runs
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None or str((skill.get("metadata") or {}).get("capability") or "").strip().lower() == "screen":
            raise HTTPException(status_code=404, detail=f"未找到技能：{slug}")
        job_name = f"skill:{slug}"
        with _ops() as store:
            job = store.get_job_by_name(job_name)
        if job is None:
            return {"slug": slug, "bound": False, "next_runs": []}
        schedule = (job.get("config") or {}).get("schedule")
        schedule = schedule if isinstance(schedule, dict) else {}
        mode = str(schedule.get("mode") or "off")
        next_runs: list[str] = []
        if mode in {"once", "interval"}:
            try:
                next_runs = preview_trading_runs(
                    mode,  # type: ignore[arg-type]
                    run_hour=int(schedule.get("run_hour", 15)),
                    run_minute=int(schedule.get("run_minute", 30)),
                    interval_minutes=int(schedule.get("interval_minutes", 10)),
                    window_start_hour=int(schedule.get("window_start_hour", 9)),
                    window_start_minute=int(schedule.get("window_start_minute", 30)),
                    window_end_hour=int(schedule.get("window_end_hour", 14)),
                    window_end_minute=int(schedule.get("window_end_minute", 50)),
                    limit=1 if mode == "once" else 5,
                )
            except Exception:
                next_runs = []
        return {"slug": slug, "bound": True, "next_runs": next_runs, **job}

    @router.put("/api/skills/{slug}/job", tags=["skills"])
    def upsert_skill_job(
        slug: str, payload: SkillJobConfig, _write: None = write_guard
    ) -> dict[str, Any]:
        """给技能绑定（或更新）定时任务；``push_wecom`` 控制结束后是否推企微。"""
        try:
            from src.ops import OpsError, SchedulerError, validate_cron
            from src.ops.application.skills import resolve_skill
            from src.ops.application.trading_schedule import (
                TradingScheduleError,
                compose_trading_cron,
                preview_trading_runs,
                schedule_dict_from_payload,
            )
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        skill = resolve_skill(slug)
        if skill is None or str((skill.get("metadata") or {}).get("capability") or "").strip().lower() == "screen":
            raise HTTPException(status_code=404, detail=f"未找到技能：{slug}")

        job_name = f"skill:{slug}"
        if payload.schedule_mode == "off":
            with _ops() as store:
                existing = store.get_job_by_name(job_name)
                if existing is not None:
                    store.delete_job(existing["id"])
            _reload_scheduler()
            return {"slug": slug, "bound": False, "next_runs": []}

        provider = payload.provider.strip()
        if not provider:
            raise HTTPException(status_code=422, detail="开启技能定时必须指定 LLM 供应商")

        cron = payload.cron.strip()
        enabled = payload.enabled
        schedule = schedule_dict_from_payload(payload)
        if payload.schedule_mode is not None:
            try:
                cron = compose_trading_cron(
                    payload.schedule_mode,
                    run_hour=payload.run_hour,
                    run_minute=payload.run_minute,
                    interval_minutes=payload.interval_minutes,
                    window_start_hour=payload.window_start_hour,
                    window_start_minute=payload.window_start_minute,
                    window_end_hour=payload.window_end_hour,
                    window_end_minute=payload.window_end_minute,
                )
            except TradingScheduleError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            enabled = True

        if cron:
            try:
                validate_cron(cron)
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        context = [str(item).strip() for item in payload.context if str(item).strip()]
        config: dict[str, Any] = {
            "skill": slug,
            "provider": provider,
            "model": payload.model.strip(),
            "thinking": payload.thinking.strip(),
            "push_wecom": bool(payload.push_wecom),
            "context": context,
            "schedule": schedule,
        }
        ctx_strategy = payload.context_strategy.strip()
        if ctx_strategy:
            config["context_strategy"] = ctx_strategy

        with _ops() as store:
            existing = store.get_job_by_name(job_name)
            try:
                if existing is None:
                    job_id = store.create_job(
                        name=job_name,
                        kind="skill",
                        cron=cron,
                        config=config,
                        enabled=enabled,
                    )
                else:
                    job_id = existing["id"]
                    store.update_job(
                        job_id, cron=cron, config=config, enabled=enabled,
                    )
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)

        _reload_scheduler()
        next_runs: list[str] = []
        if schedule.get("mode") in {"once", "interval"}:
            try:
                next_runs = preview_trading_runs(
                    schedule["mode"],
                    run_hour=int(schedule["run_hour"]),
                    run_minute=int(schedule["run_minute"]),
                    interval_minutes=int(schedule["interval_minutes"]),
                    window_start_hour=int(schedule["window_start_hour"]),
                    window_start_minute=int(schedule["window_start_minute"]),
                    window_end_hour=int(schedule["window_end_hour"]),
                    window_end_minute=int(schedule["window_end_minute"]),
                    limit=1 if schedule["mode"] == "once" else 5,
                )
            except TradingScheduleError:
                next_runs = []
        return {"slug": slug, "bound": True, "next_runs": next_runs, **(job or {})}

    @router.delete("/api/skills/{slug}/job", tags=["skills"])
    def unbind_skill_job(slug: str, _write: None = write_guard) -> dict[str, bool]:
        """解除技能的定时绑定。"""
        job_name = f"skill:{slug}"
        with _ops() as store:
            job = store.get_job_by_name(job_name)
            if job is None:
                raise HTTPException(status_code=404, detail=f"技能 {slug} 没有绑定定时任务")
            store.delete_job(job["id"])
        _reload_scheduler()
        return {"removed": True}

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
