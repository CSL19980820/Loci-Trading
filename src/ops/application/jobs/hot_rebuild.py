"""hot_rebuild 任务：全量重建滚动热读库。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext


def execute_hot_rebuild(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """把全量库近 N 交易日窗口全量重灌进热库。

    热库是「可重建派生缓存」：启动、损坏或手动触发时用本任务清空重灌，
    幂等可随时重跑。数字仍来自全量库镜像，不产生第二套真相。
    """
    return {
        "status": "skipped",
        "reason": "PostgreSQL is the authoritative online store; market_hot.db retirement is complete",
    }
