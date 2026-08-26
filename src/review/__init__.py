"""复盘限界上下文。

口径（2026-08 实盘项下线后）：复盘只基于**候选池 + 行情**算纸上收益。
依赖真实成交 / 持仓的能力（资金曲线、持仓回放、往返归因、持仓盯市、
回测-实盘偏离）已整体删除，不再从这里导出。
"""
from src.review.application.outcomes import (
    HORIZONS,
    PRIMARY_HORIZONS,
    CandidateOutcome,
    evaluate_candidates,
    filter_recent_outcomes,
    summarize_by_strategy,
    summarize_candidates,
    track_candidate_outcomes,
)
from src.review.application.outcomes_plans import evaluate_plans
from src.review.application.winrates import strategy_winrate_summary

__all__ = [
    "HORIZONS",
    "PRIMARY_HORIZONS",
    "CandidateOutcome",
    "evaluate_candidates",
    "evaluate_plans",
    "filter_recent_outcomes",
    "strategy_winrate_summary",
    "summarize_by_strategy",
    "summarize_candidates",
    "track_candidate_outcomes",
]
