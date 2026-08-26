"""托管：行情盘中增量 + 日终重刷（幂等确保）。"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY

#: 日终重刷默认点：收盘后、盘后选股（15:30）之前，保证选票吃到当日定稿 spot
EOD_HOUR = 15
EOD_MINUTE = 10

#: 托管语义键：历史遗留配置不得覆盖。盘中增量一旦被写成 ``force=true``，
#: 每 5 分钟就会把全市场历史重拉一遍（watermark 近窗增量彻底失效）。
_MANAGED_KEYS = frozenset(
    {"mode", "force", "with_factors", "refresh_instruments_daily"}
)

DEFAULT_MARKET_SYNC: dict[str, Any] = {
    "enabled_intraday": True,
    "interval_minutes": 5,
    "enabled_eod": True,
    "eod_hour": EOD_HOUR,
    "eod_minute": EOD_MINUTE,
    "workers": 4,
    "push_wecom_on_fail": False,
}


def ensure_managed_market_sync_jobs(store: Any) -> dict[str, Any]:
    """确保两条行情托管任务存在；首次无配置时默认开启盘中+日终。

    - 任务已存在：不强制改用户的 enabled（尊重运维页开关）
    - 任务缺失：按 settings / 默认值创建
    - 日终 ``today_refresh`` 带 ``with_factors=True``，避免只刷 OHLC、复权长期不更新
    """
    stored = store.get_setting("market_sync", {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    settings = {**DEFAULT_MARKET_SYNC, **stored}

    interval = int(settings.get("interval_minutes") or 5)
    if interval < 1:
        interval = 5
    workers = int(settings.get("workers") or 4)
    push = bool(settings.get("push_wecom_on_fail"))
    eod_hour = int(settings.get("eod_hour") if settings.get("eod_hour") is not None else EOD_HOUR)
    eod_minute = int(
        settings.get("eod_minute") if settings.get("eod_minute") is not None else EOD_MINUTE
    )

    intraday_cron = f"*/{interval} 9-14 * * mon-fri"
    eod_cron = f"{eod_minute} {eod_hour} * * mon-fri"

    created = 0
    updated = 0
    for name, kind_cron, config, default_enabled in (
        (
            MANAGED_SYNC_INTRADAY,
            intraday_cron,
            {
                "mode": "full",
                "workers": workers,
                "force": False,
                "with_factors": True,
                "refresh_instruments_daily": True,
                "push_wecom": push,
            },
            bool(settings["enabled_intraday"]),
        ),
        (
            MANAGED_SYNC_EOD,
            eod_cron,
            {
                "mode": "today_refresh",
                "workers": workers,
                "refresh_instruments": False,
                "refresh_instruments_daily": True,
                "with_factors": True,
                "push_wecom": push,
            },
            bool(settings["enabled_eod"]),
        ),
    ):
        existing = store.get_job_by_name(name)
        if existing is None:
            store.create_job(
                name=name,
                kind="sync",
                cron=kind_cron,
                config=config,
                enabled=default_enabled,
            )
            created += 1
        else:
            # 补齐 with_factors 等关键配置，但不强行改 enabled / cron（用户可能调过）
            prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
            merged = {**config, **{k: v for k, v in prev.items() if k not in _MANAGED_KEYS}}
            merged.update({k: v for k, v in config.items() if k in _MANAGED_KEYS})
            merged["with_factors"] = True
            store.update_job(existing["id"], config=merged)
            updated += 1

    store.set_setting(
        "market_sync",
        {
            "enabled_intraday": bool(settings["enabled_intraday"]),
            "interval_minutes": interval,
            "enabled_eod": bool(settings["enabled_eod"]),
            "eod_hour": eod_hour,
            "eod_minute": eod_minute,
            "workers": workers,
            "push_wecom_on_fail": push,
        },
    )
    return {
        "created": created,
        "updated": updated,
        "intraday_cron": intraday_cron,
        "eod_cron": eod_cron,
        "enabled_intraday": bool(settings["enabled_intraday"]),
        "enabled_eod": bool(settings["enabled_eod"]),
    }
