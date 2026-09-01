"""托管：盘中留存带每日采集（幂等确保）。

**为什么必须托管**：这批数据上游没有历史——AkShare 侧 21 个接口只有当天快照，
东财 `trends2` 的 `ndays` 上限是 5。漏一天就永久缺一天，靠人记得每天点一次等于
一定会漏。见 `docs/adr/ADR-014-encrypted-intraday-tape-retention.md`。

**为什么是 15:35**：收盘 15:00 后数据才定型；托管「行情日终重刷」在 15:10，
15:30 起是选股时段。15:35 让开这两处，且早于 02:30 的运维清理。

采集全部是**全市场单次调用**（一次覆盖全市场，不逐票循环），一轮六次请求，
不占配额也不与行情写锁冲突——它根本不写 `market.db`。
"""
from __future__ import annotations

from typing import Any

#: 任务名。与其它托管任务一样用中文名做幂等键。
MANAGED_INTRADAY_CAPTURE = "托管盘中留存采集"

#: 工作日 15:35。理由见模块 docstring。
INTRADAY_CAPTURE_CRON = "35 15 * * mon-fri"

#: 缺省不限制 datasets：清单由 `default_specs()` 决定，改清单不必改任务配置。
DEFAULT_INTRADAY_CAPTURE_CONFIG: dict[str, Any] = {}


def ensure_managed_intraday_capture_job(store: Any) -> dict[str, Any]:
    """确保「盘中留存采集」托管任务存在（工作日 15:35，首次默认开启）。

    已有任务只补配置，不强行改 enabled / cron——尊重运维页开关，语义与
    `ensure_managed_prune_job` 一致。
    """
    existing = store.get_job_by_name(MANAGED_INTRADAY_CAPTURE)
    if existing is None:
        store.create_job(
            name=MANAGED_INTRADAY_CAPTURE,
            kind="intraday_capture",
            cron=INTRADAY_CAPTURE_CRON,
            config=dict(DEFAULT_INTRADAY_CAPTURE_CONFIG),
            enabled=True,
        )
        return {"created": 1, "updated": 0}
    prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    merged = {**DEFAULT_INTRADAY_CAPTURE_CONFIG, **prev}
    store.update_job(existing["id"], config=merged)
    return {"created": 0, "updated": 1}


__all__ = [
    "DEFAULT_INTRADAY_CAPTURE_CONFIG",
    "INTRADAY_CAPTURE_CRON",
    "MANAGED_INTRADAY_CAPTURE",
    "ensure_managed_intraday_capture_job",
]
