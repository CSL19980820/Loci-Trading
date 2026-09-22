"""prune 任务执行器（**系统段**）：全局产物 + 跨租户全局库的保留期清理。

段划分（tenant 段见 ``jobs/prune_tenant.py``，两者合起来才是完整的垃圾回收）：

- 本模块：``data/intraday/`` 留存带目录（ADR-014，**60 天，别改小**——上游取
  不到历史，删早了就永久没有）、``identity.db``、``community.db``。这三样都是
  **全局唯一**的，只能在主租户跑一份；按租户各跑等于 N 个线程删同一个文件。
- ``prune_tenant``：当前租户 ``ops.db`` 的只追加表 + ``skill_runs/`` +
  ``research_runs/``。每个租户各跑一份。

``job_runs`` / ``leader_role_snapshots`` 这两段**保留在本模块里没有搬走**：
它们是主租户库的兜底，即使用户在运维页把租户段那条任务关掉，主租户也不至于
回到「一条都不清」。子租户的这两张表由 ``prune_tenant`` 负责（此前无人负责）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import JobContext, JobError

#: 角色留痕默认保留天数。留痕是可重建的观测流，不是账本事实。
DEFAULT_LEADER_ROLE_KEEP_DAYS = 60

#: 盘中留存带保留天数（ADR-014 的 30–60 天上沿）。这批数据上游没有历史，
#: 删早了就永久没有；但它也是全仓唯一按 GB 增长的滚动缓存，不能不删。
DEFAULT_INTRADAY_KEEP_DAYS = 60

#: identity.db / community.db 的保留天数。两个库都是**跨租户全局唯一**的，
#: 所以清理只能挂在系统级 prune 上（主租户一份）；按租户各跑一份会让 N 个
#: 线程同时删同一个文件。
DEFAULT_COMMUNITY_KEEP_DAYS = 15


def execute_prune(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """清理历史执行记录与角色留痕。

    定时任务是每天跑的，job_runs 不清理会无限增长，最终把几百 KB 的运维库
    撑到几百 MB。按任务保留最近 N 条即可——更早的记录除了占地方没有用处，
    真要追溯久远的问题，那时也早该看行情仓和账本了。

    龙头角色留痕同理：它是**只追加**的观测流，一天可能写几十次，
    不设保留窗就是第二个无限增长源。``leader_role_keep_days=0`` 可关闭该段清理。

    另外三段（盘中留存带 / identity / community）**异常一律只写进 payload 不
    外抛**：它们删的是目录或别的上下文的库，一次读不动不该让整条运维清理红掉。
    """
    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    from src.ops.application.retention_settings import saved_policy
    policy = saved_policy(context.ops_store) if callable(getattr(context.ops_store, "get_setting", None)) else None
    if policy is not None and not policy.enabled:
        return {"skipped": "保留策略已暂停"}
    # 至少留 1 条：配成 0 会把每个任务的历史清空，连"最近一次跑没跑过"都查不到。
    keep = max(1, int(config.get("keep_per_job", 200)))
    removed = (context.ops_store.prune_runs_windowed(
        keep_min=policy.job_keep_min, keep_max=policy.job_keep_max, keep_days=policy.job_days
    )["deleted"] if policy is not None else context.ops_store.prune_runs(keep_per_job=keep))

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()

    keep_days = policy.leader_days if policy else int(config.get("leader_role_keep_days", DEFAULT_LEADER_ROLE_KEEP_DAYS))
    roles_removed = 0
    if keep_days > 0:
        cutoff = today - timedelta(days=keep_days)
        roles_removed = context.ops_store.prune_leader_roles(before_date=cutoff.isoformat())

    # 盘中留存带的过期删除挂在这里，不新建任务类型（ADR-014）：它和 job_runs 清理
    # 是同一件事——「只追加的观测流必须有保留窗」。但它删的是**目录**而不是表行，
    # 所以失败只记进 payload 不抛：留存带删不掉是磁盘问题，不该让整条运维清理红掉。
    intraday_days = policy.intraday_days if policy else int(config.get("intraday_keep_days", DEFAULT_INTRADAY_KEEP_DAYS))
    intraday: dict[str, Any] = {"retention_days": intraday_days, "skipped": "未启用"}
    if intraday_days > 0:
        from src.market import prune_intraday
        from src.shared.paths import data_dir

        try:
            intraday = prune_intraday(
                data_dir(),
                retention_days=intraday_days,
                max_delete=int(config.get("intraday_max_delete", 30)),
            ).to_dict()
        except Exception as exc:
            intraday = {
                "retention_days": intraday_days,
                "error": f"{type(exc).__name__}: {exc}",
            }

    # ---- 跨租户全局库（identity.db / community.db）-------------------------
    # 这两段与上面的盘中留存带同样「异常只写进 payload 不外抛」：它们清的是
    # 别的上下文的库，一次读不动不该让本租户的运维清理刷红。
    #
    # identity：``IdentityStore.purge_expired()`` 在此之前是**全仓零调用点的
    # 死代码**——过期会话、oauth_states、未用的邮箱验证票据一条都没删过。
    # 跨上下文只能从包根导入（``.importlinter`` 的 protect-identity-infra）。
    identity: dict[str, Any] = {"skipped": "未启用"}
    if config.get("identity_purge", True):
        identity = (_purge_identity(notify_read_days=policy.notification_days, usage_keep_days=policy.usage_days,
                                    login_days=policy.login_days, audit_days=policy.audit_days)
                    if policy is not None else _purge_identity())

    community: dict[str, Any] = {"skipped": "未启用"}
    community_days = policy.community_days if policy else int(config.get("community_keep_days", DEFAULT_COMMUNITY_KEEP_DAYS))
    if community_days > 0:
        community = _purge_community(community_days)

    return {
        "removed": removed,
        "keep_per_job": keep,
        "leader_roles_removed": roles_removed,
        "leader_role_keep_days": keep_days,
        "intraday": intraday,
        "identity": identity,
        "community": community,
    }


def _purge_identity(*, notify_read_days: int = 15, usage_keep_days: int = 15, login_days: int = 0, audit_days: int = 0) -> dict[str, Any]:
    """清 identity.db 的过期会话、票据、站内通知与日用量计数。**不存在就不建**。

    桌面单机根本没有 identity.db；顺手把空库建出来会让「这台机器有没有启用
    账号体系」这个事实凭空改变（``tenant_jobs`` 的降级判据正是看这个文件在不在）。

    三段各自成段：会话票据、站内通知、日用量计数。审计日志 ``audit_log`` 刻意
    不在此列——那是合规留痕，保留期按 180 天单独议，不跟 15 天这一档走。
    """
    from src.shared.paths import identity_db

    if not identity_db().is_file():
        return {"skipped": "identity.db 不存在"}
    try:
        from src.identity import IdentityStore

        with IdentityStore() as store:
            return {
                "expired": int(store.purge_expired() or 0),
                "notifications": int(store.purge_notifications(read_days=notify_read_days) or 0) if notify_read_days > 0 else 0,
                "usage_counters": int(store.purge_usage_counters(keep_days=usage_keep_days) or 0) if usage_keep_days > 0 else 0,
                "logs": store.purge_audit_logs(login_days=login_days, audit_days=audit_days),
            }
    except Exception as exc:  # noqa: BLE001 — 单段失败不带走整轮
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _purge_community(keep_days: int) -> dict[str, Any]:
    """清 community.db 的动态流 / 榜单快照 / 当日信号广播。**不存在就不建**。

    只清这三张可重建的派生表。发布物、版本、评论、收藏、克隆留痕、订阅、关注
    都是用户作品，一条都不删（口径见 ``src/community/application/retention``）。
    """
    from src.shared.paths import community_db

    if not community_db().is_file():
        return {"skipped": "community.db 不存在"}
    try:
        from src.community import CommunityStore, purge_expired

        with CommunityStore() as store:
            result = purge_expired(
                store,
                feed_days=keep_days,
                board_days=keep_days,
                broadcast_days=keep_days,
            )
        return {"keep_days": keep_days, "tables": result}
    except Exception as exc:  # noqa: BLE001 — 单段失败不带走整轮
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
