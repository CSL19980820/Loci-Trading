"""托管：运维库清理（幂等确保）。"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import MANAGED_PRUNE

#: 默认点：工作日凌晨 02:30。日终/选股/热库重建等盘后任务均已跑完，
#: 此时清理 job_runs 与 leader_role_snapshots 不会与业务任务争抢 IO。
PRUNE_CRON = "30 2 * * mon-fri"

DEFAULT_PRUNE_CONFIG: dict[str, Any] = {
    "keep_per_job": 200,
    "leader_role_keep_days": 60,
    # 盘中留存带 60 天不动（ADR-014）：上游取不到历史，删早了永久没有。
    "intraday_keep_days": 60,
    # 跨租户全局库。identity 只删过期会话/票据（没有天数概念，开关而已）；
    # community 只删动态流 / 榜单快照 / 当日信号广播三张可重建表。
    "identity_purge": True,
    "community_keep_days": 15,
}


def ensure_managed_prune_job(store: Any) -> dict[str, Any]:
    """确保「运维清理」托管任务存在（工作日 02:30）。

    已有任务：只补配置，不强行改 enabled / cron（尊重运维页开关，
    与 ensure_managed_hot_rebuild_job 语义一致）。
    """
    existing = store.get_job_by_name(MANAGED_PRUNE)
    if existing is None:
        store.create_job(
            name=MANAGED_PRUNE,
            kind="prune",
            cron=PRUNE_CRON,
            config=dict(DEFAULT_PRUNE_CONFIG),
            enabled=True,
        )
        return {"created": 1, "updated": 0}
    prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    merged = {**DEFAULT_PRUNE_CONFIG, **prev}
    store.update_job(existing["id"], config=merged)
    return {"created": 0, "updated": 1}
