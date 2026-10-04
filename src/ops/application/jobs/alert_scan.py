"""价格提醒扫描任务。"""
from __future__ import annotations
from typing import Any
from src.ops.application.jobs.context import JobContext, JobError

def execute_alert_scan(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    from src.ops.application.alert_rules import scan_alert_rules

    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    return scan_alert_rules(
        context.ops_store,
        dry_run=bool(config.get("dry_run")),
    )
