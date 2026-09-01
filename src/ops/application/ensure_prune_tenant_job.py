"""托管：租户库清理（``prune_tenant``，每租户各跑一份）。

为什么要新增一个 kind 而不是复用 ``prune``：``prune`` 在
``tenant_jobs.SYSTEM_JOB_KINDS`` 里，**子租户一条都不装载**，于是子租户的
``ops.db`` 从建库那天起没人清过——按每租户 7~8 条托管任务的默认频率粗算，
``job_runs`` 一年就是 **580 MB/人**，再加上从不清理的八张 ``ai_*`` 表。
``tenant_jobs.py`` 模块头早就写好了正解：把 prune 拆成 system 段（全局产物）
与 tenant 段（租户私有库），而不是把 prune 整个挪出那个集合。

本模块就是 tenant 段。它**不进** ``SYSTEM_JOB_KINDS``——默认即租户级，
``JobScheduler.start()` 已经会为每个活跃子租户跑一遍 ``ensure_tenant_jobs``，
零额外装载代码。

## cron 错峰

所有租户挤在同一分钟清库，等于 N 条线程在 02:30 同时对各自的 SQLite 做大批量
DELETE：磁盘 IO 被打满，WAL 一起膨胀，本来 30 秒的清理拖成几分钟。

主租户固定 ``30 2``（与既有 ``MANAGED_PRUNE`` 同点，方便对照运维页）；子租户按
``job_stagger.tenant_minute_offset``（``crc32(tenant_id) % 60``）散进
``02:30``–``03:29`` 的 60 个分钟槽——错峰算法全仓只有那一份实现。
用 crc32 而不是随机数，是为了**确定性**：同一个租户每次 ensure 算出的时间必须
一样，否则每次应用启动都在改用户的 cron（还会把用户自己调过的时间冲掉）。

## 每天跑，不是工作日跑

``MANAGED_PRUNE`` 是 ``mon-fri``（它清的是随交易日增长的东西）。租户段不一样：
AI 对话、技能 run、研究 run 周末照样产生，跳过周末只是让周一多删两天的量。
"""
from __future__ import annotations

from typing import Any

from src.ops.application.job_stagger import tenant_minute_offset
from src.ops.infrastructure.store_helpers import MANAGED_PRUNE_TENANT

#: 错峰窗口：起点 02:30，宽 60 分钟。
_CRON_BASE_MINUTES = 2 * 60 + 30
_CRON_SPREAD = 60

#: 租户段的全部可调参数。``{**DEFAULT, **prev}`` 合并即可给存量库补齐新键，
#: 不需要写迁移——用户在运维页调过的值永远优先，缺的键才用默认值填上。
DEFAULT_PRUNE_TENANT_CONFIG: dict[str, Any] = {
    # 只追加表的统一保留天数。
    "keep_days": 15,
    # job_runs 三参数双闸门：保底条数 / 硬上限 / 中间地带的时间闸。
    # 单参数 keep_per_job=200 对 */5 任务只有 2.8 天、对日更任务是 10 个月，
    # 同一个数字给出两个数量级的保留期，两头都不对。
    "run_keep_min": 5,
    "run_keep_max": 200,
    # AI 会话按**条数**截断（对话是用户资产，不按 15 天砍）。
    "ai_session_keep": 500,
    # 分批删除的批大小。SQLite 的 DELETE...LIMIT 需编译选项，CPython 没开，
    # 所以走 WHERE rowid IN (SELECT ... LIMIT n) 循环，每批提交一次放锁。
    "batch": 5000,
    # 磁盘产物（skill_runs / research_runs）单轮删除上限。
    "artifact_max_delete": 5000,
    # 存储上限（MB）。0 = 现取 identity.db 里该用户的 user_quotas.storage_mb；
    # 负数 = 不限。清完常规保留期仍超限时进入激进模式。
    "storage_mb": 0,
    # 激进模式的收紧倍数：保留期除以它再清一轮（2 = 减半）。
    "aggressive_factor": 2,
}


def prune_tenant_cron(tenant_id: str | None = None) -> str:
    """该租户的清理时点。主租户 ``30 2``；子租户确定性地散到 02:30-03:29。

    偏移复用 ``job_stagger.tenant_minute_offset``（同一套 ``crc32 % span``，
    主租户恒为 0），但**不能**直接用 ``staggered_cron``：那个函数刻意拒绝跨整点
    （盘后任务越过 16:00 是另一件事），而本任务的 60 分钟窗本来就要从 02:30
    跨进 03:xx。所以只借偏移，小时进位在这里自己算。
    """
    offset = tenant_minute_offset(_CRON_SPREAD, tenant_id)
    total = _CRON_BASE_MINUTES + offset
    return f"{total % 60} {total // 60} * * *"


def ensure_prune_tenant_job(store: Any, *, tenant_id: str | None = None) -> dict[str, Any]:
    """确保「租户库清理」托管任务存在。

    已有任务：**只补缺失的配置键**，不回写 ``enabled`` / ``cron``（与其余
    ``ensure_*`` 一致）。用户在运维页关掉的清理、改过的时点不会被 ensure 顶回去
    ——每次启动都还原用户设置的 ensure 才是真正会被投诉的那种。
    """
    cron = prune_tenant_cron(tenant_id)
    existing = store.get_job_by_name(MANAGED_PRUNE_TENANT)
    if existing is None:
        store.create_job(
            name=MANAGED_PRUNE_TENANT,
            kind="prune_tenant",
            cron=cron,
            config=dict(DEFAULT_PRUNE_TENANT_CONFIG),
            enabled=True,
        )
        return {"created": 1, "updated": 0, "cron": cron}
    prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    store.update_job(existing["id"], config={**DEFAULT_PRUNE_TENANT_CONFIG, **prev})
    return {"created": 0, "updated": 1, "cron": existing.get("cron") or cron}


__all__ = [
    "DEFAULT_PRUNE_TENANT_CONFIG",
    "MANAGED_PRUNE_TENANT",
    "ensure_prune_tenant_job",
    "prune_tenant_cron",
]
