"""skill_watch 任务：战法实时监测（MCP + 量化 + AI 摘要）。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs.context import JobContext, JobError
from src.ops.application.skill_watch.runner import run_skill_watch


def execute_skill_watch(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    # 确定性监测可只跑 MCP/量化；仅开启 AI 摘要时才强制供应商
    if bool(config.get("watch_use_ai", False)) and not str(config.get("provider") or "").strip():
        raise JobError("开启 AI 摘要时必须配置 LLM 供应商")
    market_store = None
    if context.market_db is not None or context.market_hot_db is not None:
        market_store = context.market() if context.market_db is not None else context.market_hot()
    if market_store is None:
        result = run_skill_watch(config, store=context.ops_store)
    else:
        try:
            result = run_skill_watch(
                config,
                store=context.ops_store,
                market_store=market_store,
            )
        finally:
            market_store.close()

    return result
