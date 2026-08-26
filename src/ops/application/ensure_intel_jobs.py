"""托管悟道情报采集任务（structured 池 ~3000/天）。"""
from __future__ import annotations

from typing import Any

MANAGED_INTEL_OPEN = "情报·开盘"
MANAGED_INTEL_INTRADAY = "情报·盘中"
MANAGED_INTEL_CLOSE = "情报·盘后"

MANAGED_INTEL_OPEN_CRON = "26 9 * * mon-fri"
MANAGED_INTEL_INTRADAY_CRON = "*/15 9-14 * * mon-fri"
MANAGED_INTEL_CLOSE_CRON = "40 15 * * mon-fri"


def ensure_managed_intel_jobs(store: Any, *, enabled: bool = True) -> dict[str, Any]:
    """幂等创建三档结构化情报 Job；未配 wudao Key 时仍可存在，执行时会软跳过。

    ``enabled`` 只作为**首次创建**的默认值。已存在的任务只补齐托管配置键，
    不回写 enabled / cron / 用户调过的参数——否则每次应用启动都会把用户在
    运维页关掉的任务重新打开、把改过的采集量还原成默认值。
    """
    specs = [
        (
            MANAGED_INTEL_OPEN,
            MANAGED_INTEL_OPEN_CRON,
            {"phase": "open", "theme_top_n": 150, "screener_count": 12},
        ),
        (
            MANAGED_INTEL_INTRADAY,
            MANAGED_INTEL_INTRADAY_CRON,
            {"phase": "intraday", "theme_top_n": 120, "stock_flow_top_n": 120},
        ),
        (
            MANAGED_INTEL_CLOSE,
            MANAGED_INTEL_CLOSE_CRON,
            {
                "phase": "close",
                "theme_top_n": 200,
                "stock_flow_top_n": 240,
                "screener_count": 16,
                "cache_max_age_minutes": 120,
            },
        ),
    ]
    created: list[str] = []
    updated: list[str] = []
    for name, cron, config in specs:
        existing = store.get_job_by_name(name)
        managed_config = {**config, "server": "wudao"}
        if existing is None:
            store.create_job(
                name=name,
                kind="intel_fetch",
                cron=cron,
                config=managed_config,
                enabled=enabled,
            )
            created.append(name)
        else:
            prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
            # 用户值优先；只补齐缺失的托管键
            store.update_job(existing["id"], config={**managed_config, **prev})
            updated.append(name)
    return {"created": created, "updated": updated, "enabled": enabled}
