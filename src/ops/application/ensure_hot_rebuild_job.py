"""托管：行情热库重建（幂等确保）。"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import MANAGED_HOT_REBUILD

#: 默认点：日终重刷（15:10）与盘后选股（15:30）之后，全量库当日数据已定稿。
HOT_REBUILD_CRON = "10 16 * * mon-fri"

DEFAULT_HOT_REBUILD_CONFIG: dict[str, Any] = {"window_trading_days": 700}


def ensure_managed_hot_rebuild_job(store: Any) -> dict[str, Any]:
    """确保「行情热库重建」托管任务存在（工作日 16:10）。

    已有任务：只补配置，不强行改 enabled / cron（尊重运维页开关，
    与行情托管 ensure_managed_market_sync_jobs 语义一致）。
    """
    existing = store.get_job_by_name(MANAGED_HOT_REBUILD)
    if existing is None:
        store.create_job(
            name=MANAGED_HOT_REBUILD,
            kind="hot_rebuild",
            cron=HOT_REBUILD_CRON,
            config=dict(DEFAULT_HOT_REBUILD_CONFIG),
            enabled=True,
        )
        return {"created": 1, "updated": 0}
    prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    merged = {**DEFAULT_HOT_REBUILD_CONFIG, **prev}
    store.update_job(existing["id"], config=merged)
    return {"created": 0, "updated": 1}