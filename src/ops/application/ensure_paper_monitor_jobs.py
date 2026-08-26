"""纸面舱启用时幂等挂上 strategy_monitor / paper_eod 定时任务。"""
from __future__ import annotations

from typing import Any

from src.ops.application.retire_dragon_return import (
    is_retired_paper_cabin,
    remove_jobs_for_slug,
    retire_dragon_return,
)
from src.ops.application.skill_watch.watch_labels import watch_short_name

DEFAULT_MONITOR_CRON = "*/15 9-14 * * mon-fri"
DEFAULT_EOD_CRON = "30 15 * * mon-fri"


def monitor_job_name(slug: str) -> str:
    return f"纸面盯盘·{watch_short_name(slug=slug)}"


def eod_job_name(slug: str) -> str:
    return f"盘后复盘·{watch_short_name(slug=slug)}"


def _find_job_by_slug(store: Any, *, kind: str, slug: str) -> dict[str, Any] | None:
    key = str(slug or "").strip()
    if not key:
        return None
    for job in store.list_jobs() or []:
        if str(job.get("kind") or "") != kind:
            continue
        cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
        if str(cfg.get("slug") or cfg.get("skill") or "").strip() == key:
            return job
    return None


def ensure_paper_monitor_jobs(
    store: Any,
    slug: str,
    *,
    enabled: bool,
    interval: str = DEFAULT_MONITOR_CRON,
    eod_cron: str = DEFAULT_EOD_CRON,
) -> dict[str, Any]:
    """按舱配置同步盘中/日终 Job；enabled=false 时停用（不删历史）。

    已退役的纸面舱（龙回头 / 龙池）只删残留任务，不再创建。
    """
    key = str(slug or "").strip()
    if not key:
        return {"slug": "", "monitor": None, "eod": None}
    if is_retired_paper_cabin(key):
        removed = remove_jobs_for_slug(store, key)
        return {
            "slug": key,
            "retired": True,
            "removed_jobs": removed,
            "actions": {"retired": "removed" if removed else "absent"},
            "monitor": None,
            "eod": None,
        }
    cron = str(interval or "").strip() or DEFAULT_MONITOR_CRON
    eod = str(eod_cron or "").strip() or DEFAULT_EOD_CRON
    actions: dict[str, str] = {}

    for kind, name, job_cron in (
        ("strategy_monitor", monitor_job_name(key), cron),
        ("paper_eod", eod_job_name(key), eod),
    ):
        config = {"slug": key}
        existing = _find_job_by_slug(store, kind=kind, slug=key) or store.get_job_by_name(name)
        if existing is None:
            if not enabled:
                actions[kind] = "absent"
                continue
            store.create_job(
                name=name,
                kind=kind,
                cron=job_cron,
                config=config,
                enabled=True,
            )
            actions[kind] = "created"
            continue
        store.update_job(
            existing["id"],
            name=name,
            cron=job_cron,
            config=config,
            enabled=bool(enabled),
        )
        actions[kind] = "enabled" if enabled else "disabled"

    return {"slug": key, "actions": actions, "monitor_cron": cron, "eod_cron": eod}


def reconcile_dragon_return_jobs(store: Any) -> dict[str, Any]:
    """兼容旧启动入口：改为退役，不再把监测任务挂回去。"""
    return retire_dragon_return(store)
