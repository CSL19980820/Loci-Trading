"""纸面量化 Job 注册入口与薄编排。

实现按阶段拆到同目录：

- ``paper_quant_support`` — 日期 / 舱配置 / 龙空龙闸门
- ``paper_quant_plan`` — 次日情景预案
- ``paper_quant_monitor`` — ``strategy_monitor``
- ``paper_quant_eod`` — ``paper_eod``

本文件只导出公开 Job 入口；测试与内部 helper 请直接从对应子模块导入。
"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError
from src.ops.application.jobs.paper_quant_eod import execute_paper_eod
from src.ops.application.jobs.paper_quant_monitor import execute_strategy_monitor
from src.ops.application.jobs.paper_quant_plan import generate_nextday_plan

__all__ = [
    "execute_alert_scan",
    "execute_paper_eod",
    "execute_strategy_monitor",
    "generate_nextday_plan",
]


def execute_alert_scan(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    from src.ops.application.alert_rules import scan_alert_rules

    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    return scan_alert_rules(
        context.ops_store,
        dry_run=bool(config.get("dry_run")),
    )
