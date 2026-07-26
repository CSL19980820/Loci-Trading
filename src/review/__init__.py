"""复盘：基于真实账本 + 真实行情，不依赖任何 LLM。

三块内容对应三个不同的问题：

- ``equity``   我的钱是怎么变化的（真实净值曲线、回撤、基准对比）
- ``replay``   我持有过什么（持仓回放、持仓周期归因）
- ``outcomes`` 我的判断对不对（候选池 T+N 验证、预案兑现率）

其中候选池验证是最有价值的一块：交易复盘只统计买过的票，那是幸存者
偏差的样本；而"当初否决的票后来涨了多少"才真正能改进选股规则。
"""
from src.review.attribution import attribute_round_trips, summarize_round_trips
from src.review.equity import EquityCurve, EquityPoint, build_equity_curve, compute_curve_metrics
from src.review.outcomes import (
    HORIZONS,
    CandidateOutcome,
    evaluate_candidates,
    evaluate_plans,
    summarize_candidates,
)
from src.review.replay import HeldPosition, RoundTrip, holdings_timeline, positions_as_of, round_trips

__all__ = [
    "HORIZONS",
    "CandidateOutcome",
    "EquityCurve",
    "EquityPoint",
    "HeldPosition",
    "RoundTrip",
    "attribute_round_trips",
    "build_equity_curve",
    "compute_curve_metrics",
    "evaluate_candidates",
    "evaluate_plans",
    "holdings_timeline",
    "positions_as_of",
    "round_trips",
    "summarize_candidates",
    "summarize_round_trips",
]
