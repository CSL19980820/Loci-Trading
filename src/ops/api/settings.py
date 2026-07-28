"""运维：线路 / 数据目录 / 企微 / 行情同步 HTTP。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.app.legacy.quant_common import (
    DataLocationUpdate,
    LaneProbeRequest,
    LaneProviderPatch,
    LaneSpeedtestRequest,
    MarketSyncSettings,
    WecomSettingsUpdate,
    market_store,
    missing_dependency,
    ops_store,
)


def build_ops_settings_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    def _ops():
        return ops_store(ops_db)

    def _reload_scheduler() -> None:
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and scheduler.running:
            scheduler.reload()

    def _data_location_snapshot() -> dict[str, Any]:
        from src.shared.paths import (
            MARKET_POPULATED_BYTES,
            config_path,
            data_dir,
            default_data_dir,
            discover_data_dirs,
            load_config,
            market_db,
            market_db_size,
            needs_setup,
            setup_done,
            writable_root,
        )

        root = data_dir()
        size = market_db_size(root)
        needed = True
        coverage: dict[str, Any] = {}
        try:
            with _market() as store:
                coverage = store.coverage()
            needed = int(coverage.get("rows") or 0) == 0
        except Exception:
            needed = size < MARKET_POPULATED_BYTES
        cfg = load_config()
        must_setup = needs_setup()
        return {
            "data_dir": str(root),
            "default_dir": str(default_data_dir()),
            "install_dir": str(writable_root()),
            "config_path": str(config_path()),
            "market_db": str(market_db()),
            "market_bytes": size,
            "needed_bootstrap": needed,
            "setup_done": setup_done() and not must_setup,
            "needs_setup": must_setup,
            "coverage": coverage,
            "discovered_dirs": discover_data_dirs(),
            "config": {
                "data_dir": cfg.get("data_dir"),
                "setup_done": bool(cfg.get("setup_done")),
            },
        }

    # ---- 数据线路（可接入 API 目录 / 同类比速） -----------------------

    _LANE_LABELS: dict[str, str] = {
        "hist_daily": "历史日 K",
        "spot_batch": "实时快照",
        "instruments": "证券列表",
        "adjust_factor": "复权因子",
        "minute_bars": "分钟 K",
        "capital_flow": "个股资金流",
        "intel_mcp": "外部情报",
    }
    _LANE_REQUIRED: dict[str, bool] = {
        "hist_daily": True,
        "spot_batch": True,
        "instruments": True,
        "adjust_factor": True,
        "minute_bars": False,
        "capital_flow": False,
        "intel_mcp": False,
    }

    def _lane_provider_prefs() -> dict[str, Any]:
        from src.shared.paths import load_config

        raw = load_config().get("lane_providers")
        return raw if isinstance(raw, dict) else {}

    def _provider_enabled(provider_id: str, prefs: dict[str, Any] | None = None) -> bool:
        table = prefs if prefs is not None else _lane_provider_prefs()
        entry = table.get(provider_id)
        if isinstance(entry, dict) and "enabled" in entry:
            return bool(entry["enabled"])
        return True

    @router.get("/api/ops/lanes", tags=["ops"])
    def get_lanes_catalog() -> dict[str, Any]:
        """可接入 API 目录 + 类目清单。转换规则在适配器代码里，这里只列名片。"""
        from src.market import ALL_LANES, list_catalog

        prefs = _lane_provider_prefs()
        providers = []
        for entry in list_catalog():
            pid = str(entry.get("id") or "")
            providers.append({**entry, "enabled": _provider_enabled(pid, prefs)})
        lanes = [
            {
                "id": lane_id,
                "label": _LANE_LABELS.get(lane_id, lane_id),
                "required": _LANE_REQUIRED.get(lane_id, False),
            }
            for lane_id in ALL_LANES
        ]
        return {"lanes": lanes, "providers": providers, "summary": {"ok": 0, "degraded": 0, "down": 0}}

    @router.post("/api/ops/lanes/probe", tags=["ops"])
    def post_lanes_probe(payload: LaneProbeRequest) -> dict[str, Any]:
        """探测连通性。类目内并行；未指定 lane 则逐类目探测。"""
        from src.market import (
            ALL_LANES,
            enabled_adapter_ids,
            get_adapter,
            list_catalog,
            probe_lane,
        )

        label_by_id = {str(e.get("id")): str(e.get("label") or e.get("id")) for e in list_catalog()}
        only_id = (payload.adapter_id or "").strip() or None
        if only_id:
            try:
                get_adapter(only_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=f"未知接入：{only_id}") from exc

        def ids_for(lane: str) -> list[str]:
            if only_id:
                adapter = get_adapter(only_id)
                return [only_id] if lane in adapter.meta.lanes else []
            return enabled_adapter_ids(lane)

        target = (payload.lane or "").strip() or None
        lane_ids = [target] if target else list(ALL_LANES)
        if target and target not in ALL_LANES:
            raise HTTPException(status_code=400, detail=f"未知类目：{target}")

        results: list[dict[str, Any]] = []
        for lane_id in lane_ids:
            ids = ids_for(lane_id)
            if not ids:
                continue
            for item in probe_lane(lane_id, adapter_ids=ids):
                row = item.to_dict()
                row["label"] = label_by_id.get(item.adapter_id, item.adapter_id)
                results.append(row)
        return {"results": results}

    @router.post("/api/ops/lanes/speedtest", tags=["ops"])
    def post_lanes_speedtest(payload: LaneSpeedtestRequest) -> dict[str, Any]:
        """同类下载测速。P0 仅支持历史日 K。"""
        from src.market import (
            LANE_HIST_DAILY,
            enabled_adapter_ids,
            list_catalog,
            speedtest_daily,
        )

        lane = (payload.lane or LANE_HIST_DAILY).strip()
        if lane != LANE_HIST_DAILY:
            raise HTTPException(
                status_code=400,
                detail="下载测速目前仅支持历史日 K（hist_daily）",
            )
        code = "".join(ch for ch in (payload.code or "600519") if ch.isdigit()).zfill(6)[-6:]
        ids = enabled_adapter_ids(LANE_HIST_DAILY)
        if not ids:
            return {"lane": lane, "code": code, "results": []}
        label_by_id = {str(e.get("id")): str(e.get("label") or e.get("id")) for e in list_catalog()}
        rows = []
        for item in speedtest_daily(code, adapter_ids=ids):
            row = item.to_dict()
            row["label"] = label_by_id.get(item.adapter_id, item.adapter_id)
            rows.append(row)
        return {"lane": lane, "code": code, "results": rows}

    @router.patch("/api/ops/lanes/providers/{provider_id}", tags=["ops"])
    def patch_lane_provider(
        provider_id: str,
        payload: LaneProviderPatch,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """启用/禁用某家接入。只改开关，不改转换规则。"""
        from src.market import get_adapter
        from src.shared.paths import load_config, save_config

        try:
            adapter = get_adapter(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"未知接入：{provider_id}") from exc
        cfg = load_config()
        table = cfg.get("lane_providers")
        if not isinstance(table, dict):
            table = {}
        table[provider_id] = {"enabled": bool(payload.enabled)}
        save_config({"lane_providers": table})
        if not payload.enabled:
            from src.market import clear_sticky

            # 停用后清粘性，避免下一次还钉着已关的源
            clear_sticky()
        return {
            "id": provider_id,
            "label": adapter.meta.label,
            "enabled": bool(payload.enabled),
        }

    @router.get("/api/ops/data-location", tags=["ops"])
    def get_data_location() -> dict[str, Any]:
        """当前数据目录、默认路径、是否需要初始化行情。"""
        return _data_location_snapshot()

    @router.post("/api/ops/data-location", tags=["ops"])
    def post_data_location(
        payload: DataLocationUpdate,
        request: Request,
    ) -> dict[str, Any]:
        """写入 loci.config.json，并初始化目录 / 三库空 schema。改路径通常需重启。

        首次向导（needs_setup）允许未登录确认；之后改路径需已登录。
        """
        from src.shared.paths import apply_data_dir, data_dir, initialize_data_layout, needs_setup

        if not needs_setup():
            write_dependency(request)

        raw = (payload.data_dir or "").strip()
        if not raw:
            raise HTTPException(status_code=422, detail="数据目录不能为空")
        target = Path(raw).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".loci-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=422, detail=f"无法写入该目录：{exc}"
            ) from exc

        before = data_dir().resolve()
        applied = apply_data_dir(target, mark_setup_done=payload.setup_done)
        try:
            initialize_data_layout(applied)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"初始化数据目录失败：{exc}"
            ) from exc
        restart_required = applied.resolve() != before
        snap = _data_location_snapshot()
        # snapshot 仍读旧进程内的 data_dir()（env/已加载路径）；用 applied 覆盖展示
        snap["data_dir"] = str(applied)
        snap["pending_data_dir"] = str(applied)
        snap["restart_required"] = restart_required
        snap["setup_done"] = True if payload.setup_done else snap["setup_done"]
        snap["needs_setup"] = False if payload.setup_done else snap.get("needs_setup", True)
        snap["message"] = (
            "已保存并初始化。请关闭并重新打开 Loci 使新目录生效。"
            if restart_required
            else "已保存并完成目录初始化。"
        )
        return snap

    @router.post("/api/ops/desktop-shortcut", tags=["ops"])
    def post_desktop_shortcut(_write: None = write_guard) -> dict[str, Any]:
        """在当前用户桌面创建 Loci 快捷方式。"""
        try:
            from src.shared.desktop_shortcut import create_desktop_shortcut

            info = create_desktop_shortcut()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, **info}

    @router.get("/api/ops/settings/wecom", tags=["notify"])
    def get_wecom_settings() -> dict[str, Any]:
        from src.ops.application.notify import mask_wecom_webhook

        with _ops() as store:
            raw = store.get_setting("wecom_webhook", {}) or {}
            url = str(raw.get("url") or "")
        return {
            "configured": bool(url),
            "url_masked": mask_wecom_webhook(url) if url else "",
        }

    @router.put("/api/ops/settings/wecom", tags=["notify"])
    def put_wecom_settings(
        payload: WecomSettingsUpdate, _write: None = write_guard
    ) -> dict[str, Any]:
        from src.ops.application.notify import NotifyError, mask_wecom_webhook, validate_wecom_webhook

        url = (payload.url or "").strip()
        with _ops() as store:
            if not url:
                store.delete_setting("wecom_webhook")
                return {"configured": False, "url_masked": ""}
            try:
                validated = validate_wecom_webhook(url)
            except NotifyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            store.set_setting("wecom_webhook", {"url": validated})
        return {"configured": True, "url_masked": mask_wecom_webhook(validated)}

    @router.post("/api/ops/settings/wecom/test", tags=["notify"])
    def test_wecom_settings(_write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.notify import NotifyError, send_wecom_markdown

        with _ops() as store:
            raw = store.get_setting("wecom_webhook", {}) or {}
            url = str(raw.get("url") or "")
        if not url:
            raise HTTPException(status_code=422, detail="尚未配置企业微信 Webhook")
        try:
            send_wecom_markdown(
                url,
                "### 记忆宫殿连通测试\n企微推送已接通。可在运维配置触价/选股/日终简报任务。",
            )
        except NotifyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True}

    def _read_market_sync_settings(store: Any) -> dict[str, Any]:
        defaults = {
            "enabled_intraday": False,
            "interval_minutes": 5,
            "enabled_eod": False,
            "eod_hour": 16,
            "eod_minute": 0,
            "workers": 4,
            "push_wecom_on_fail": False,
        }
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
            cfg = intraday.get("config") or {}
            if cfg.get("workers"):
                merged["workers"] = int(cfg["workers"])
            merged["push_wecom_on_fail"] = bool(cfg.get("push_wecom"))
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
        if interval not in {1, 5, 10, 15, 30, 60}:
            # 允许任意 1-60，但 cron 用 */N
            pass
        workers = int(settings["workers"])
        push = bool(settings.get("push_wecom_on_fail"))
        intraday_cron = f"*/{interval} 9-14 * * 1-5"
        eod_cron = f"{int(settings['eod_minute'])} {int(settings['eod_hour'])} * * 1-5"

        store.ensure_job(
            name=MANAGED_SYNC_INTRADAY,
            kind="sync",
            cron=intraday_cron,
            config={
                "mode": "full",
                "workers": workers,
                "force": False,
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
        intraday_cron = f"*/{settings['interval_minutes']} 9-14 * * 1-5"
        eod_cron = f"{settings['eod_minute']} {settings['eod_hour']} * * 1-5"
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
