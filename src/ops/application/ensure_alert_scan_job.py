r"""托管：价格提醒扫描（有规则才挂）。

**为什么要有它**：`alert_rules` 的冷却（`cooldown_minutes` 默认 5 分钟）、
每日触发上限（`max_triggers_per_day`）、`market_hours_mode='session'`
这些字段只有在「有人按固定节奏扫」时才有意义；ADR-008 也写明价格提醒的
运行时是 `alert_rules` / `alert_scan`。但仓里**从来没有任何代码创建过
`alert_scan` 任务**：规则存进库以后，只有人手点运维页的「扫描」按钮
（`POST /api/ops/alert-rules/scan`）才会命中——提醒不会自己响，冷却与
日上限也就永远用不上。这条 ensure 补的就是这个缺口。

**为什么「有规则才建」**：一条规则都没有时 `scan_alert_rules` 直接返回
`total_rules=0` 就走人。无条件托管等于给每台机器每天塞 48 条空 run：执行
历史被冲淡、运维页多一条永远没事干的任务，而绝大多数安装根本不用这个
功能。所以判据是**用户已经真的建了启用中的规则**——那时候他要的就是
自动扫描。

**时点**：``*/5 9-14 * * mon-fri``，与 `行情盘中增量` 同窗口、与规则默认
冷却（5 分钟）同节奏。`_can_trigger` 并不校验 `market_hours_mode`，
**cron 窗口就是唯一的时段闸门**，所以不要把它挪到盘后或改成全天。
"""
from __future__ import annotations

from typing import Any

#: 托管任务名（运维页按名找任务，勿改名）
MANAGED_ALERT_SCAN = "价格提醒扫描"

#: 默认点：盘中每 5 分钟。与规则默认冷却同节奏；再密只会被冷却吃掉。
ALERT_SCAN_CRON = "*/5 9-14 * * mon-fri"

#: ``dry_run=True`` 只算不落库不推送，留给排查用；托管默认真扫。
DEFAULT_ALERT_SCAN_CONFIG: dict[str, Any] = {"dry_run": False}



def _has_enabled_alert_rules(store: Any) -> bool:
    """库里有没有启用中的价格提醒规则。

    用 ``getattr`` 探测而不是直接调：``ensure_all_managed_jobs`` 收的是 ``Any``，
    老适配器 / 测试替身可能没有这张表的接口；探不到就当没规则，不该把整轮
    托管确保带崩。
    """
    lister = getattr(store, "list_alert_rules", None)
    if not callable(lister):
        return False
    return bool(lister(enabled_only=True))


def ensure_managed_alert_scan_job(store: Any) -> dict[str, Any]:
    """有启用规则时确保「价格提醒扫描」托管任务存在（工作日盘中每 5 分钟）。

    - 没有任何启用规则、任务也不存在：**不创建**，返回 ``skipped``
    - 任务已存在：只补齐缺失的配置键，不改 enabled / cron，也不因为规则被删光
        就停用或删除——用户可能只是临时清空规则，删了他调过的 cron 就找不回来
        （与其它 ``ensure_managed_*`` 同语义）
    """
    existing = store.get_job_by_name(MANAGED_ALERT_SCAN)
    if existing is None:
        if not _has_enabled_alert_rules(store):
            return {"created": 0, "updated": 0, "skipped": "no_alert_rules"}
        store.create_job(
            name=MANAGED_ALERT_SCAN,
            kind="alert_scan",
            cron=ALERT_SCAN_CRON,
            config=dict(DEFAULT_ALERT_SCAN_CONFIG),
            enabled=True,
        )
        return {"created": 1, "updated": 0}
    prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    merged = {**DEFAULT_ALERT_SCAN_CONFIG, **prev}
    store.update_job(existing["id"], config=merged)
    return {"created": 0, "updated": 1}


__all__ = [
    "ALERT_SCAN_CRON",
    "DEFAULT_ALERT_SCAN_CONFIG",
    "MANAGED_ALERT_SCAN",
    "ensure_managed_alert_scan_job",
]
