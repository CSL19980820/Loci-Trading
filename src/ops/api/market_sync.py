"""行情同步设置 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.ops.api.schemas import MarketSyncSettings
from src.shared.api_deps import missing_dependency, ops_store


def build_market_sync_settings_router(
    *,
    write_dependency,
    ops_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    """构造行情同步设置路由。"""
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

    def _read_market_sync_settings(store: Any) -> dict[str, Any]:
        from src.ops.application.ensure_market_sync_jobs import DEFAULT_MARKET_SYNC

        defaults = dict(DEFAULT_MARKET_SYNC)
        stored = store.get_setting("market_sync", {}) or {}
        if not isinstance(stored, dict):
            stored = {}
        merged = {**defaults, **stored}
        # 从托管任务回填开关与 cron，避免设置与 jobs 表漂移
        from src.ops import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY

        intraday = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
        eod = store.get_job_by_name(MANAGED_SYNC_EOD)
        if intraday:
            merged["enabled_intraday"] = bool(intraday.get("enabled"))
            cron = str(intraday.get("cron") or "")
            parts = cron.split()
            if parts and parts[0].startswith("*/"):
                try:
                    merged["interval_minutes"] = int(parts[0][2:])
                except ValueError:
                    pass
            config = intraday.get("config") or {}
            if config.get("workers"):
                merged["workers"] = int(config["workers"])
            merged["push_wecom_on_fail"] = bool(config.get("push_wecom"))
        if eod:
            merged["enabled_eod"] = bool(eod.get("enabled"))
            cron = str(eod.get("cron") or "")
            parts = cron.split()
            if len(parts) >= 2:
                try:
                    merged["eod_minute"] = int(parts[0])
                    merged["eod_hour"] = int(parts[1])
                except ValueError:
                    pass
        return merged

    def _apply_market_sync_settings(store: Any, settings: dict[str, Any]) -> dict[str, Any]:
        from src.ops import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY

        interval = int(settings["interval_minutes"])
        workers = int(settings["workers"])
        push = bool(settings.get("push_wecom_on_fail"))
        intraday_cron = f"*/{interval} 9-14 * * mon-fri"
        eod_cron = f"{int(settings['eod_minute'])} {int(settings['eod_hour'])} * * mon-fri"

        store.ensure_job(
            name=MANAGED_SYNC_INTRADAY,
            kind="sync",
            cron=intraday_cron,
            config={
                "mode": "full",
                "workers": workers,
                "force": False,
                "with_factors": True,
                "push_wecom": push,
            },
            enabled=bool(settings["enabled_intraday"]),
        )
        store.ensure_job(
            name=MANAGED_SYNC_EOD,
            kind="sync",
            cron=eod_cron,
            config={
                "mode": "today_refresh",
                "workers": workers,
                "refresh_instruments": False,
                "with_factors": True,
                "push_wecom": push,
            },
            enabled=bool(settings["enabled_eod"]),
        )
        store.set_setting(
            "market_sync",
            {
                "enabled_intraday": bool(settings["enabled_intraday"]),
                "interval_minutes": interval,
                "enabled_eod": bool(settings["enabled_eod"]),
                "eod_hour": int(settings["eod_hour"]),
                "eod_minute": int(settings["eod_minute"]),
                "workers": workers,
                "push_wecom_on_fail": push,
            },
        )
        return _read_market_sync_settings(store)

    @router.get("/api/ops/market-sync", tags=["notify"])
    def get_market_sync() -> dict[str, Any]:
        with _ops() as store:
            settings = _read_market_sync_settings(store)
            from src.ops import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY

            settings["intraday_job"] = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
            settings["eod_job"] = store.get_job_by_name(MANAGED_SYNC_EOD)
        if scheduler_getter is not None:
            scheduler = scheduler_getter()
            if scheduler is not None and scheduler.running:
                upcoming = {item["id"]: item for item in scheduler.upcoming()}
                for key in ("intraday_job", "eod_job"):
                    job = settings.get(key)
                    if job and job.get("id") in upcoming:
                        job = {**job, "next_run_at": upcoming[job["id"]].get("next_run_at")}
                        settings[key] = job
        return settings

    @router.put("/api/ops/market-sync", tags=["notify"])
    def put_market_sync(
        payload: MarketSyncSettings, _write: None = write_guard
    ) -> dict[str, Any]:
        try:
            from src.ops import SchedulerError, validate_cron
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        settings = payload.model_dump()
        intraday_cron = f"*/{settings['interval_minutes']} 9-14 * * mon-fri"
        eod_cron = f"{settings['eod_minute']} {settings['eod_hour']} * * mon-fri"
        try:
            validate_cron(intraday_cron)
            validate_cron(eod_cron)
        except SchedulerError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with _ops() as store:
            result = _apply_market_sync_settings(store, settings)
            from src.ops import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY

            result["intraday_job"] = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
            result["eod_job"] = store.get_job_by_name(MANAGED_SYNC_EOD)
        _reload_scheduler()
        return result

    return router
