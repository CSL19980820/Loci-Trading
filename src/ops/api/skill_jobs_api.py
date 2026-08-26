"""专属战法 strategy-config + 技能定时 Job 绑定。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from src.ops.api.schemas import SkillJobConfig, SkillStrategyConfig
from src.shared.api_deps import missing_dependency


def register_skill_job_routes(
    router: APIRouter,
    *,
    write_guard: Any,
    ops_factory: Callable[[], Any],
    reload_scheduler: Callable[[], None],
) -> None:
    def _ops():
        return ops_factory()

    def _reload_scheduler() -> None:
        reload_scheduler()

    @router.get("/api/skills/{slug}/strategy-config", tags=["skills"])
    def get_skill_strategy_config(slug: str) -> dict[str, Any]:
        """专属战法：盘后 AI 选股 + 盘中监测配置。"""
        try:
            from src.ops.application.skill_strategy_config import (
                get_strategy_config,
                is_strategy_skill,
            )
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"未找到技能：{slug}")
        if not is_strategy_skill(skill):
            raise HTTPException(status_code=422, detail=f"技能 {slug} 不是专属战法包")
        with _ops() as store:
            return get_strategy_config(store, slug)

    @router.put("/api/skills/{slug}/strategy-config", tags=["skills"])
    def upsert_skill_strategy_config(
        slug: str, payload: SkillStrategyConfig, _write: None = write_guard
    ) -> dict[str, Any]:
        try:
            from src.ops import OpsError
            from src.ops.application.skill_strategy_config import (
                is_strategy_skill,
                save_strategy_config,
            )
            from src.ops.application.skills import resolve_skill
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        skill = resolve_skill(slug)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"未找到技能：{slug}")
        if not is_strategy_skill(skill):
            raise HTTPException(status_code=422, detail=f"技能 {slug} 不是专属战法包")
        with _ops() as store:
            try:
                saved = save_strategy_config(store, slug, payload)
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        _reload_scheduler()
        return saved

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


