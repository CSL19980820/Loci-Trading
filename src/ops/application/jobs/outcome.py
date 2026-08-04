"""outcome 任务：盘后跟踪候选 T+1/T+3/T+5 并汇总战法胜率。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import (
    DEFAULT_PALACE_DB,
    JobContext,
)


def execute_outcome(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """重算近期精选候选的短线窗口，写入执行记录供目录消费。

    数字仍由行情即时推导，不落第二套权威表；本任务负责：
    1) 定时触发（默认工作日 15:45）
    2) 留下可追溯快照（job_runs.result）
    """
    from src.ledger import PalaceStore
    from src.review import track_candidate_outcomes

    limit = int(config.get("limit") or 2000)
    max_age = int(config.get("max_age_trading_days") or 5)
    benchmark = config.get("benchmark")
    if benchmark is not None:
        benchmark = str(benchmark).strip() or None
    else:
        benchmark = "000300"

    palace_path = context.palace_db or DEFAULT_PALACE_DB
    with PalaceStore(palace_path) as palace, context.market() as market:
        payload = track_candidate_outcomes(
            palace,
            market,
            limit=limit,
            benchmark=benchmark,
            max_age_trading_days=max_age,
        )
    payload["config"] = {
        "limit": limit,
        "max_age_trading_days": max_age,
        "benchmark": benchmark or "",
    }
    return payload
