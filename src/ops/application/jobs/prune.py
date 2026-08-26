"""prune 任务执行器：清理历史执行记录与角色留痕。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import JobContext, JobError

#: 角色留痕默认保留天数。留痕是可重建的观测流，不是账本事实。
DEFAULT_LEADER_ROLE_KEEP_DAYS = 60

#: 二波触发留痕保留天数。比角色留痕长一倍：这张表是「强度分是否有效」的
#: 唯一样本来源，观察期至少要覆盖几个月才能回答那个问题。
DEFAULT_SECOND_WAVE_KEEP_DAYS = 180


def execute_prune(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """清理历史执行记录与角色留痕。

    定时任务是每天跑的，job_runs 不清理会无限增长，最终把几百 KB 的运维库
    撑到几百 MB。按任务保留最近 N 条即可——更早的记录除了占地方没有用处，
    真要追溯久远的问题，那时也早该看行情仓和账本了。

    龙头角色留痕同理：它是**只追加**的观测流，一天可能写几十次，
    不设保留窗就是第二个无限增长源。``leader_role_keep_days=0`` 可关闭该段清理。

    二波触发留痕（``second_wave_signals``）默认留 180 天——它是「强度分是否有效」
    的唯一样本来源，砍太短就把还没验完的观察期数据删了。``second_wave_keep_days=0``
    可关闭该段清理。
    """
    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    # 至少留 1 条：配成 0 会把每个任务的历史清空，连"最近一次跑没跑过"都查不到。
    keep = max(1, int(config.get("keep_per_job", 200)))
    removed = context.ops_store.prune_runs(keep_per_job=keep)

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()

    keep_days = int(config.get("leader_role_keep_days", DEFAULT_LEADER_ROLE_KEEP_DAYS))
    roles_removed = 0
    if keep_days > 0:
        cutoff = today - timedelta(days=keep_days)
        roles_removed = context.ops_store.prune_leader_roles(before_date=cutoff.isoformat())

    wave_days = int(config.get("second_wave_keep_days", DEFAULT_SECOND_WAVE_KEEP_DAYS))
    wave_removed = 0
    if wave_days > 0:
        cutoff = today - timedelta(days=wave_days)
        wave_removed = context.ops_store.prune_second_wave(before_date=cutoff.isoformat())

    return {
        "removed": removed,
        "keep_per_job": keep,
        "leader_roles_removed": roles_removed,
        "leader_role_keep_days": keep_days,
        "second_wave_removed": wave_removed,
        "second_wave_keep_days": wave_days,
    }
