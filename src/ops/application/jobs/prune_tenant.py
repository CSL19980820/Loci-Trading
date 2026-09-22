"""prune_tenant 执行器：清当前租户私有库与私有目录。

与系统级 ``prune`` 的分工（拆分理由见 ``ensure_prune_tenant_job`` 模块头）：

| kind | 谁跑 | 删什么 |
| --- | --- | --- |
| ``prune`` | 主租户一份 | ``data/intraday/`` + identity.db + community.db |
| ``prune_tenant`` | 每租户各跑 | 当前租户 ops.db 的只追加表 + skill_runs/ + research_runs/ |

四条硬约束，每条都有仓内先例，别在重构时顺手删掉：

1. **分批删**。首次开 15 天会一次删掉几十万行，单条 DELETE 把 WAL 撑爆并全程
   持写锁。SQLite 的 ``DELETE ... LIMIT`` 需要编译选项而 CPython 自带的没开，
   所以走 ``WHERE rowid IN (SELECT rowid ... LIMIT n)`` 循环，每批提交放锁。
   实现在 ``src.shared.sqlite_retention.delete_in_batches``。
2. **删行不会让文件变小**。SQLite 只把页标记为可复用。所以 payload 必须同时
   报 ``{table: {deleted, kept, ms}}`` 与 ``bytes_before/after``，否则「删了几十万
   行但库还是 5 GB」会被当成清理没生效。真要缩文件得显式 ``VACUUM``——那要重写
   整个库、需要等量空闲磁盘、期间独占写锁，**绝不塞进每晚的清理任务**。
3. **单段失败不带走整轮**。照 ``jobs/prune.py`` 对盘中留存带的做法：异常只写进
   payload 不外抛（统一经 ``sqlite_retention.segment``）。
4. **参数集中在 ``DEFAULT_PRUNE_TENANT_CONFIG``**，靠 ``{**DEFAULT, **prev}``
   给存量库补齐新键，不用写迁移。

## 存储上限（``user_quotas.storage_mb``）

常规保留期清完仍超限时进入**激进模式**：保留期除以 ``aggressive_factor``
（默认 2 = 减半）再清一轮，payload 报 ``over_quota: true`` 与前后体积。

**永远不拒绝写入**。超配额是「这个人的垃圾比别人多」，把他锁在门外（不让存
对话、不让跑技能）比留点垃圾糟得多，而且用户当场也没有可操作的补救手段。
"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError
from src.ops.application.tenant_storage import (
    prune_research_runs,
    prune_skill_runs,
    tenant_storage_usage,
)
from src.ops.application.ensure_prune_tenant_job import DEFAULT_PRUNE_TENANT_CONFIG
from src.shared.paths import research_runs_dir, skill_runs_dir
from src.shared.sqlite_retention import segment
from src.shared.tenancy import current_tenant
from src.ops.domain.retention_policy import RetentionPolicy
from src.ops.application.retention_settings import saved_policy

#: 当前租户 ops.db 里按**纯时间**截断的只追加表：``(表, 时间列, 是否纯日期列)``。
#:
#: 判据是「只追加 + 可重建 / 只用于近期回看」。**不在这张表里的东西不要顺手加**：
#: ``paper_fills`` / ``paper_positions`` / ``nextday_plans`` 是纸面账的事实，
#: ``paper_mem_*`` / ``paper_style_profiles`` / ``paper_lessons`` 是学出来的记忆，
#: ``strategy_docs`` / ``strategy_versions`` 是用户作品，一条都不能按天砍。
AGE_TRUNCATED_TABLES: tuple[tuple[str, str, bool], ...] = (
    # 盯盘运行历史：一天几十条，只用于近期复盘。
    ("monitor_runs", "started_at", False),
    # 价格提醒命中：*/5 的扫描 + 每票每桶一条，涨得很快。
    ("alert_hits", "trigger_time", False),
    # AI 决策留痕：单条可达几十 KB（prompt + 报价快照 + 原始回复）。
    ("ai_decisions", "created_at", False),
    # 龙头角色留痕：只追加的观测流，重扫即可再生。原先 60 天，收到 15 天。
    ("leader_role_snapshots", "trade_date", True),
    # 悟道 MCP 日配额计数：按天分池，过了当天就只是历史。
    ("mcp_quota", "trade_date", True),
)


def _int(config: dict[str, Any], key: str) -> int:
    """读一个整数配置项；缺键 / 写错一律回落默认值，不让配置错误炸掉清理。"""
    raw = config.get(key, DEFAULT_PRUNE_TENANT_CONFIG.get(key, 0))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(DEFAULT_PRUNE_TENANT_CONFIG.get(key, 0))


def _prune_tables(
    store: Any, *, keep_days: int, run_keep_min: int, run_keep_max: int,
    session_keep: int, batch: int, policy: RetentionPolicy | None = None,
) -> dict[str, Any]:
    """清 ops.db 里的全部只追加表。每张各自 try，单张失败不带走其余。"""
    out: dict[str, Any] = {}
    if policy is not None:
        run_keep_min, run_keep_max = policy.job_keep_min, policy.job_keep_max
        session_keep = policy.ai_session_keep
    ages = {} if policy is None else {
        "monitor_runs": policy.monitor_days, "alert_hits": policy.alert_days,
        "ai_decisions": policy.decision_days, "leader_role_snapshots": policy.leader_days,
        "mcp_quota": policy.quota_days,
    }
    out["job_runs"] = segment(
        "job_runs",
        lambda: store.prune_runs_windowed(
            keep_min=run_keep_min,
            keep_max=run_keep_max,
            keep_days=policy.job_days if policy else keep_days,
            batch=batch,
        ),
    )
    for table, column, date_only in AGE_TRUNCATED_TABLES:
        out[table] = segment(
            table,
            lambda t=table, c=column, d=date_only: store.prune_by_age(
                t, c, keep_days=ages.get(t, keep_days), batch=batch, date_only=d
            ),
        )
    # AI 助手八张表在同一个 ops.db 里，复用同一条连接（别再开一条去抢写锁）。
    from src.ai import purge_ai_retention

    out.update(
        purge_ai_retention(
            store.conn,
            event_days=policy.ai_event_days if policy else keep_days,
            grant_days=policy.ai_grant_days if policy else keep_days,
            session_keep=session_keep,
            batch=batch,
        )
    )
    return out


def _prune_artifacts(*, keep_days: int, max_delete: int, policy: RetentionPolicy | None = None) -> dict[str, Any]:
    """清落在磁盘上的 run 产物。删不掉是磁盘问题，不该让整轮红掉。"""
    return {
        "skill_runs": segment(
            "skill_runs",
            lambda: prune_skill_runs(
                skill_runs_dir(), keep_days=policy.skill_days if policy else keep_days, max_delete=max_delete
            ),
        ),
        "research_runs": segment(
            "research_runs",
            lambda: prune_research_runs(
                research_runs_dir(), keep_days=policy.research_days if policy else keep_days, max_delete=max_delete
            ),
        ),
    }


#: identity 里 ``storage_mb=0`` 的含义是「用系统默认」，默认值与
#: ``identity/infrastructure/store_platform.DEFAULT_QUOTAS`` 保持一致。
#: 不 import 那个常量：跨上下文只能走 ``from src.identity import IdentityStore``。
DEFAULT_STORAGE_MB = 2048

def _quota_storage_mb(tenant_id: str) -> int:
    """从 identity.db 取该租户的 ``storage_mb``。取不到一律返回 0（= 不限）。

    取不到就不限，是刻意的 fail-open：桌面单机根本没有 identity.db，
    此时把限额当成 0 才是对的；服务端偶发读不动身份库时，宁可这一晚不进激进
    模式，也不能凭一次读失败去更狠地删用户数据。
    """
    from src.shared.paths import identity_db

    if not identity_db().is_file():
        return 0
    from src.identity import IdentityStore

    with IdentityStore() as store:
        # 一条 SQL 反查，而不是分页扫全表逐个比对 tenant_id：清理跑在 02:30 且
        # 持写锁，用户上千之后每个租户都扫一遍会把凌晨整段占住。
        user = store.get_user_by_tenant(tenant_id)
        if user is None:
            return 0
        limit = int(store.get_quota(user.id).get("storage_mb", 0) or 0)
    return DEFAULT_STORAGE_MB if limit == 0 else limit


def _resolve_storage_mb(config: dict[str, Any], tenant_id: str) -> tuple[int, str]:
    """返回 ``(上限MB, 来源)``。配置里显式写死的优先，否则现取身份库。"""
    configured = _int(config, "storage_mb")
    if configured != 0:
        return configured, "config"
    try:
        return _quota_storage_mb(tenant_id), "identity"
    except Exception as exc:  # noqa: BLE001 — 读不到配额不该让清理红掉
        return 0, f"unavailable: {type(exc).__name__}"


def execute_prune_tenant(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """清当前租户的 ops.db 只追加表 + skill_runs/ + research_runs/。"""
    store = context.ops_store
    if store is None:
        raise JobError("缺少运维库连接")
    policy = saved_policy(store) if callable(getattr(store, "get_setting", None)) else None
    if policy is not None and not policy.enabled:
        return {"skipped": "保留策略已暂停", "tenant": current_tenant()}
    tenant = current_tenant()
    keep_days = max(0, _int(config, "keep_days"))
    batch = max(1, _int(config, "batch"))
    session_keep = _int(config, "ai_session_keep")
    max_delete = max(1, _int(config, "artifact_max_delete"))

    before = tenant_storage_usage(tenant)
    tables = _prune_tables(
        store,
        keep_days=keep_days,
        run_keep_min=_int(config, "run_keep_min"),
        run_keep_max=_int(config, "run_keep_max"),
        session_keep=session_keep,
        batch=batch, policy=policy,
    )
    artifacts = _prune_artifacts(keep_days=keep_days, max_delete=max_delete, policy=policy)
    after = tenant_storage_usage(tenant)

    limit_mb, source = _resolve_storage_mb(config, tenant)
    payload: dict[str, Any] = {
        "tenant": tenant,
        "keep_days": keep_days,
        "tables": tables,
        "artifacts": artifacts,
        "bytes_before": before["bytes"],
        "bytes_after": after["bytes"],
        "usage": after,
        "storage_mb": limit_mb,
        "storage_mb_source": source,
        "over_quota": False,
        # 删行不会让文件变小；缩文件要显式 VACUUM，不在本任务里做。见模块头。
        "vacuum": "not_run",
    }
    if policy is not None:
        # Explicit user retention must never be silently shortened by quota mode.
        payload["policy"] = policy.model_dump()
        payload["over_quota"] = limit_mb > 0 and after["mb"] > limit_mb
        return payload
    if limit_mb <= 0 or after["mb"] <= limit_mb:
        return payload

    factor = max(2, _int(config, "aggressive_factor"))
    tight_days = max(1, keep_days // factor)
    tight_sessions = max(1, session_keep // factor) if session_keep > 0 else 0
    aggressive_tables = _prune_tables(
        store,
        keep_days=tight_days,
        run_keep_min=_int(config, "run_keep_min"),
        run_keep_max=max(1, _int(config, "run_keep_max") // factor),
        session_keep=tight_sessions,
        batch=batch,
    )
    aggressive_artifacts = _prune_artifacts(keep_days=tight_days, max_delete=max_delete)
    final = tenant_storage_usage(tenant)
    payload["over_quota"] = True
    payload["aggressive"] = {
        "keep_days": tight_days,
        "ai_session_keep": tight_sessions,
        "tables": aggressive_tables,
        "artifacts": aggressive_artifacts,
        "bytes_before": after["bytes"],
        "bytes_after": final["bytes"],
        # 仍然**不拒绝写入**：把人锁在门外比留点垃圾更糟。见模块头。
        "writes_blocked": False,
    }
    payload["bytes_after"] = final["bytes"]
    payload["usage"] = final
    return payload


__all__ = ["AGE_TRUNCATED_TABLES", "execute_prune_tenant"]
