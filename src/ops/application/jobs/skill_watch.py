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

    # 扫描任务只有显式声明 paper_monitor_slug 才接管纸面舱；不再默认 dragon-return。
    slug = str(config.get("skill") or config.get("slug") or "").strip()
    if "paper_monitor_slug" in config:
        paper_slug = str(config.get("paper_monitor_slug") or "").strip()
    else:
        paper_slug = ""

    cabin = context.ops_store.get_paper_cabin(paper_slug) if paper_slug else None
    if paper_slug and isinstance(cabin, dict):
        from src.ops.application.jobs.paper_quant_support import _paper_quant_config

        paper_cfg = _paper_quant_config(cabin.get("config") or {})
        if paper_cfg.get("enabled", True):
            from src.ops.application.jobs.paper_quant_monitor import execute_strategy_monitor

            # 扫描摘要要推企微时，纸面动作并进那一条，避免同一轮发两遍；
            # 扫描摘要不推时，动作必须自己出声，否则成交回执就丢了。
            monitor = execute_strategy_monitor(
                {
                    "slug": paper_slug,
                    "trigger": "skill_watch",
                    "collect_follow": True,
                    "emit_follow": not bool(config.get("push_wecom")),
                    # 集成通知的持仓清单由执行后的统一池负责；这里仅返回本轮成交、
                    # 拒单、开盘纪律和异常，避免成本/层数在同一条消息里复读。
                    "include_position_lines": paper_slug == slug,
                },
                context,
            )
            result = {**result, "paper_monitor": monitor}
            action_body = str(monitor.get("follow_body") or "").strip()
            if result.get("skipped") and not monitor.get("skipped"):
                result["scan_skipped"] = True
                result["scan_reason"] = result.get("reason")
                result.pop("skipped", None)
                result.pop("reason", None)
        else:
            action_body = ""
    else:
        action_body = ""

    if action_body:
        summary = str(result.get("summary") or "").strip()
        result["summary"] = f"{summary}\n\n{action_body}".strip()
    return result
