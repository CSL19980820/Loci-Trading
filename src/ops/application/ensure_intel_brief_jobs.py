"""托管悟道简报推送任务：四档，各比悟道出稿时点晚 10 分钟。

## 时点为什么是 09:10 / 12:10 / 15:40 / 21:10

悟道侧的出稿时点是 09:00 / 12:00 / 15:30 / 21:00（其开发者页「每日市场动态中心」
明写「预计生成时间」）。**预计不等于准时**：AI 生成会排队、会重试。所以每一档都
往后让 10 分钟，并且**同一档挂多个触发分钟**（``10,25,40``）——第一次没出稿就记
``skipped``，第二次再看一眼；出稿后由防重标记保证只推一条。

收盘档挂在 ``40,55``：15:30 出稿、15:40 首推，而 ``情报·盘后``（``intel_fetch``）
也在 15:40 跑，两条都要打悟道。差 15 分钟的第二个触发点足够覆盖延迟，也不至于
在同一分钟里跟收盘采集抢每分钟名额。

## 默认开着，但不会吵

首次创建即 ``enabled=True`` + ``push_wecom=True``：用户配了悟道和企微就该自动收到，
这也是本轮需求的原话。它不会变成噪音的原因有三条：**没配悟道 → skipped**、
**没配企微 → 一条「没有可用渠道」的失败记录且不重试**、**没出稿 → skipped**。
不想要就在运维页把这四条任务关掉（或把 ``push_wecom`` 关掉只留取数）。
"""
from __future__ import annotations

from typing import Any

MANAGED_BRIEF_PREFIX = "简报·"

#: 四档任务名。**必须是独立的字符串常量**：``job_quota.managed_job_names()`` 靠
#: 「从 ensure_* 模块现取 ``MANAGED_*`` 字符串」认托管任务，认不出来的任务会去吃
#: 用户自建任务的 ``job_slots`` 额度（默认 5 条），四条简报一挂就占掉一大半。
MANAGED_BRIEF_OPEN = "简报·开盘"
MANAGED_BRIEF_MIDDAY = "简报·午间"
MANAGED_BRIEF_CLOSE = "简报·收盘"
MANAGED_BRIEF_EVENING = "简报·晚间"

#: slot → (任务名, cron)。cron 一律工作日：APScheduler 的数字星期 0=周一，
#: 所以只写 ``mon-fri``（历史上写 ``1-5`` 会整周跳过周一）。
MANAGED_BRIEF_SPECS: tuple[tuple[str, str, str], ...] = (
    ("open", MANAGED_BRIEF_OPEN, "10,25,40 9 * * mon-fri"),
    ("midday", MANAGED_BRIEF_MIDDAY, "10,25,40 12 * * mon-fri"),
    ("close", MANAGED_BRIEF_CLOSE, "40,55 15 * * mon-fri"),
    ("evening", MANAGED_BRIEF_EVENING, "10,25,40 21 * * mon-fri"),
)


def managed_brief_job_names() -> tuple[str, ...]:
    return tuple(name for _slot, name, _cron in MANAGED_BRIEF_SPECS)


def ensure_managed_intel_brief_jobs(store: Any, *, enabled: bool = True) -> dict[str, Any]:
    """幂等创建四档简报推送 Job。

    ``enabled`` 只作为**首次创建**的默认值；已存在的任务只补齐缺失的托管键，不回写
    ``enabled`` / ``cron`` / 用户改过的参数——否则每次启动都会把用户关掉的任务打开。
    """
    created: list[str] = []
    updated: list[str] = []
    for slot, name, cron in MANAGED_BRIEF_SPECS:
        managed_config: dict[str, Any] = {
            "slot": slot,
            "server": "wudao",
            "push_wecom": True,
            "full_text": True,
            "pool": "structured",
        }
        existing = store.get_job_by_name(name)
        if existing is None:
            store.create_job(
                name=name,
                kind="intel_brief",
                cron=cron,
                config=managed_config,
                enabled=enabled,
            )
            created.append(name)
            continue
        prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
        # 用户值优先；只补齐缺失的托管键
        store.update_job(existing["id"], config={**managed_config, **prev})
        updated.append(name)
    return {"created": created, "updated": updated, "enabled": enabled}


__all__ = [
    "MANAGED_BRIEF_PREFIX",
    "MANAGED_BRIEF_SPECS",
    "ensure_managed_intel_brief_jobs",
    "managed_brief_job_names",
]
