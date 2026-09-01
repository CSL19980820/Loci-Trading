"""专属战法 Skill 配置：盘后 skill Job + 盘中 skill_watch Job。

**时间归系统**：SKILL.md 不声明 cron / schedule。这里给出系统默认档位，
用户在「工坊 → 技能 → 配置」里改，落到 job.config.schedule。
"""
from __future__ import annotations

from typing import Any, Literal

ScheduleMode = Literal["off", "once", "interval"]

SCREEN_JOB_PREFIX = "skill:"
WATCH_JOB_PREFIX = "监测·"


def default_watch_push_wecom(slug: str) -> bool:
    """新建监测任务时是否默认推企微。"""
    from src.ops.application.skill_watch.engine_registry import (
        default_watch_push_wecom as _default_push,
    )

    return _default_push(slug)


def watch_job_name(slug: str) -> str:
    """监测任务对外显示名（中文），config.skill 仍存英文 slug。"""
    from src.ops.application.skill_watch.watch_labels import watch_job_title

    return watch_job_title(slug=slug)


def _find_watch_job(store: Any, slug: str) -> dict[str, Any] | None:
    """兼容旧名「监测·dragon-return」与新名「监测·龙回头」。"""
    for name in (watch_job_name(slug), f"{WATCH_JOB_PREFIX}{slug}"):
        job = store.get_job_by_name(name)
        if job is not None:
            return job
    for job in store.list_jobs() or []:
        if str(job.get("kind") or "") != "skill_watch":
            continue
        cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
        if str(cfg.get("skill") or "") == slug:
            return job
    return None

#: 盘后选股默认：交易日 15:40 定点跑一次
DEFAULT_SCREEN_SCHEDULE: dict[str, Any] = {
    "mode": "once",
    "run_hour": 15,
    "run_minute": 40,
    "interval_minutes": 10,
    "window_start_hour": 9,
    "window_start_minute": 30,
    "window_end_hour": 14,
    "window_end_minute": 50,
}

#: 盘中监测默认：交易时段每 10 分钟扫一次
DEFAULT_WATCH_SCHEDULE: dict[str, Any] = {
    "mode": "interval",
    "run_hour": 10,
    "run_minute": 0,
    "interval_minutes": 10,
    "window_start_hour": 9,
    "window_start_minute": 30,
    "window_end_hour": 14,
    "window_end_minute": 50,
}

DRAGON_RETURN_WATCH_SCHEDULE: dict[str, Any] = {
    **DEFAULT_WATCH_SCHEDULE,
    "window_start_minute": 20,
    "sessions": [
        {"start_hour": 9, "start_minute": 20, "end_hour": 11, "end_minute": 30},
        {"start_hour": 13, "start_minute": 0, "end_hour": 14, "end_minute": 50},
    ],
}

#: slug → 系统托管的固定盘中时段。新增托管战法加一条，不写 if 丛林。
MANAGED_WATCH_SCHEDULES: dict[str, dict[str, Any]] = {
    "dragon-return": DRAGON_RETURN_WATCH_SCHEDULE,
}

_SCHEDULE_FIELDS = (
    "run_hour",
    "run_minute",
    "interval_minutes",
    "window_start_hour",
    "window_start_minute",
    "window_end_hour",
    "window_end_minute",
)


def managed_watch_schedule(slug: str, schedule: dict[str, Any] | None) -> dict[str, Any]:
    """收口系统托管战法的固定盘中时段。"""
    resolved = dict(schedule or DEFAULT_WATCH_SCHEDULE)
    managed = MANAGED_WATCH_SCHEDULES.get(str(slug or "").strip())
    if managed is not None:
        resolved.update(managed)
        sessions = managed.get("sessions")
        if isinstance(sessions, list):
            resolved["sessions"] = [dict(session) for session in sessions]
    return resolved


def is_strategy_skill(skill: dict[str, Any]) -> bool:
    """专属战法 = 声明了 strategy_skill / signal_engine / signals 之一。"""
    meta = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
    if meta.get("strategy_skill") is True:
        return True
    return bool(meta.get("signal_engine") or meta.get("signals"))


def signal_engine_of(skill: dict[str, Any]) -> str:
    """信号引擎标识；未声明时退回 slug（内置扫描器按 slug 兜底）。"""
    meta = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
    engine = str(meta.get("signal_engine") or "").strip()
    return engine or str(skill.get("slug") or "").strip()


def declared_signals(skill: dict[str, Any]) -> list[str]:
    meta = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
    raw = meta.get("signals")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _schedule_from_payload(mode: ScheduleMode, payload: Any, *, prefix: str) -> dict[str, Any]:
    defaults = DEFAULT_WATCH_SCHEDULE if prefix == "watch_" else DEFAULT_SCREEN_SCHEDULE
    schedule: dict[str, Any] = {"mode": mode}
    for field in _SCHEDULE_FIELDS:
        schedule[field] = int(getattr(payload, f"{prefix}{field}", defaults[field]))
    return schedule


def _hydrate_schedule(schedule: dict[str, Any], target: dict[str, Any], *, prefix: str) -> None:
    mode = str(schedule.get("mode") or "off")
    if mode not in {"once", "interval"}:
        return
    target[f"{prefix}schedule_mode"] = mode
    for field in _SCHEDULE_FIELDS:
        if field in schedule:
            target[f"{prefix}{field}"] = int(schedule[field])


def _preview(mode: str, schedule: dict[str, Any]) -> list[str]:
    if mode not in {"once", "interval"}:
        return []
    from src.ops.application.trading_schedule import preview_trading_runs

    try:
        return preview_trading_runs(
            mode,  # type: ignore[arg-type]
            run_hour=int(schedule["run_hour"]),
            run_minute=int(schedule["run_minute"]),
            interval_minutes=int(schedule["interval_minutes"]),
            window_start_hour=int(schedule["window_start_hour"]),
            window_start_minute=int(schedule["window_start_minute"]),
            window_end_hour=int(schedule["window_end_hour"]),
            window_end_minute=int(schedule["window_end_minute"]),
            sessions=schedule.get("sessions"),
            limit=1 if mode == "once" else 5,
        )
    except Exception:
        return []


def _base_config(slug: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "slug": slug,
        "strategy_skill": True,
        "provider": "",
        "model": "",
        "thinking": "medium",
        "push_wecom": True,
        "push_watch": default_watch_push_wecom(slug),
        "watch_use_ai": False,
        "screen_schedule_mode": "off",
        "watch_schedule_mode": "off",
        "screen_bound": False,
        "watch_bound": False,
        "screen_next_runs": [],
        "watch_next_runs": [],
        "watch_available": False,
        "watch_unavailable_reason": "",
    }
    for field in _SCHEDULE_FIELDS:
        out[f"screen_{field}"] = DEFAULT_SCREEN_SCHEDULE[field]
        out[f"watch_{field}"] = DEFAULT_WATCH_SCHEDULE[field]
    if slug in MANAGED_WATCH_SCHEDULES:
        managed = managed_watch_schedule(slug, DEFAULT_WATCH_SCHEDULE)
        for field in _SCHEDULE_FIELDS:
            out[f"watch_{field}"] = managed[field]
    return out


def get_strategy_config(store: Any, slug: str) -> dict[str, Any]:
    """读回两个 Job 的配置；未绑定时给系统默认档位供 UI 预填。"""
    out = _base_config(slug)
    from src.ops.application.skill_watch import wudao_availability_for_watch

    availability = wudao_availability_for_watch()
    out["watch_available"] = bool(availability["available"])
    out["watch_unavailable_reason"] = str(availability["reason"])
    screen_job = store.get_job_by_name(f"{SCREEN_JOB_PREFIX}{slug}")
    watch_job = _find_watch_job(store, slug)

    if screen_job:
        cfg = screen_job.get("config") if isinstance(screen_job.get("config"), dict) else {}
        out["screen_bound"] = True
        out["provider"] = str(cfg.get("provider") or "")
        out["model"] = str(cfg.get("model") or "")
        out["thinking"] = str(cfg.get("thinking") or "medium")
        out["push_wecom"] = cfg.get("push_wecom", True) is not False
        schedule = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else {}
        _hydrate_schedule(schedule, out, prefix="screen_")
        out["screen_next_runs"] = _preview(
            str(out["screen_schedule_mode"]),
            {field: out[f"screen_{field}"] for field in _SCHEDULE_FIELDS},
        )

    if watch_job:
        cfg = watch_job.get("config") if isinstance(watch_job.get("config"), dict) else {}
        out["watch_bound"] = True
        if not out["provider"]:
            out["provider"] = str(cfg.get("provider") or "")
        if not out["model"]:
            out["model"] = str(cfg.get("model") or "")
        out["push_watch"] = cfg.get("push_wecom", True) is not False
        out["watch_use_ai"] = cfg.get("watch_use_ai", False) is not False
        schedule = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else {}
        _hydrate_schedule(schedule, out, prefix="watch_")
        out["watch_next_runs"] = _preview(
            str(out["watch_schedule_mode"]),
            {
                **{field: out[f"watch_{field}"] for field in _SCHEDULE_FIELDS},
                "sessions": schedule.get("sessions"),
            },
        )

    return out


def save_strategy_config(store: Any, slug: str, payload: Any) -> dict[str, Any]:
    """写两个 Job；确定性盘中监测不依赖 LLM。"""
    from src.ops import OpsError, SchedulerError, validate_cron
    from src.ops.application.trading_schedule import (
        TradingScheduleError,
        compose_trading_cron,
    )

    screen_mode: ScheduleMode = getattr(payload, "screen_schedule_mode", None) or "off"
    watch_mode: ScheduleMode = getattr(payload, "watch_schedule_mode", None) or "off"
    provider = str(getattr(payload, "provider", "") or "").strip()
    watch_use_ai = bool(getattr(payload, "watch_use_ai", False))
    if (screen_mode != "off" or (watch_mode != "off" and watch_use_ai)) and not provider:
        raise OpsError("盘后 AI 选股或 AI 监测开启时，必须指定 LLM 供应商")

    def _upsert(
        *,
        name: str,
        kind: str,
        mode: ScheduleMode,
        schedule: dict[str, Any],
        config: dict[str, Any],
        existing: dict[str, Any] | None = None,
    ) -> None:
        row = existing if existing is not None else store.get_job_by_name(name)
        if mode == "off":
            if row is not None:
                store.delete_job(row["id"])
            return
        try:
            cron = compose_trading_cron(
                mode,
                run_hour=int(schedule["run_hour"]),
                run_minute=int(schedule["run_minute"]),
                interval_minutes=int(schedule["interval_minutes"]),
                window_start_hour=int(schedule["window_start_hour"]),
                window_start_minute=int(schedule["window_start_minute"]),
                window_end_hour=int(schedule["window_end_hour"]),
                window_end_minute=int(schedule["window_end_minute"]),
            )
            validate_cron(cron)
        except (TradingScheduleError, SchedulerError) as exc:
            raise OpsError(str(exc)) from exc
        if row is None:
            store.create_job(name=name, kind=kind, cron=cron, config=config, enabled=True)
        else:
            # 旧英文监测名一并改成中文短名
            store.update_job(row["id"], name=name, cron=cron, config=config, enabled=True)

    shared = {
        "provider": provider,
        "model": str(getattr(payload, "model", "") or "").strip(),
        "thinking": str(getattr(payload, "thinking", "") or "medium").strip(),
    }

    screen_schedule = _schedule_from_payload(screen_mode, payload, prefix="screen_")
    screen_config: dict[str, Any] = {
        "skill": slug,
        **shared,
        "push_wecom": bool(getattr(payload, "push_wecom", True)),
        "schedule": screen_schedule,
        "context": [str(x).strip() for x in getattr(payload, "context", []) if str(x).strip()],
    }
    ctx_strategy = str(getattr(payload, "context_strategy", "") or "").strip()
    if ctx_strategy:
        screen_config["context_strategy"] = ctx_strategy
    _upsert(
        name=f"{SCREEN_JOB_PREFIX}{slug}",
        kind="skill",
        mode=screen_mode,
        schedule=screen_schedule,
        config=screen_config,
    )

    watch_schedule = managed_watch_schedule(
        slug,
        _schedule_from_payload(watch_mode, payload, prefix="watch_"),
    )
    fields_set = getattr(payload, "model_fields_set", None) or set()
    if "push_watch" in fields_set:
        push_watch = bool(getattr(payload, "push_watch"))
    else:
        existing_watch = _find_watch_job(store, slug)
        if existing_watch is not None:
            cfg = (
                existing_watch.get("config")
                if isinstance(existing_watch.get("config"), dict)
                else {}
            )
            push_watch = cfg.get("push_wecom", True) is not False
        else:
            push_watch = default_watch_push_wecom(slug)
    watch_config: dict[str, Any] = {
        "skill": slug,
        **shared,
        "push_wecom": push_watch,
        "watch_use_ai": watch_use_ai,
        "schedule": watch_schedule,
    }
    _upsert(
        name=watch_job_name(slug),
        kind="skill_watch",
        mode=watch_mode,
        schedule=watch_schedule,
        config=watch_config,
        existing=_find_watch_job(store, slug),
    )

    return get_strategy_config(store, slug)
