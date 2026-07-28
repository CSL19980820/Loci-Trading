"""prune 任务执行器：清理历史执行记录。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError


def execute_prune(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """清理历史执行记录。

    定时任务是每天跑的，job_runs 不清理会无限增长，最终把几百 KB 的运维库
    撑到几百 MB。按任务保留最近 N 条即可——更早的记录除了占地方没有用处，
    真要追溯久远的问题，那时也早该看行情仓和账本了。
    """
    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    keep = int(config.get("keep_per_job", 200))
    removed = context.ops_store.prune_runs(keep_per_job=keep)
    return {"removed": removed, "keep_per_job": keep}
