"""回测：把信号变成可比较的绩效。

信号级回测（单笔独立评估）先回答"这个战法本身有没有 alpha"；
组合级资金曲线是另一回事，由复盘模块基于真实账本另做。
"""
from src.backtest.engine import (
    EXIT_REASONS,
    BacktestConfig,
    BacktestResult,
    Trade,
    compute_metrics,
    run_backtest,
)
from src.backtest.runner import backtest_strategy

__all__ = [
    "EXIT_REASONS",
    "BacktestConfig",
    "BacktestResult",
    "Trade",
    "backtest_strategy",
    "compute_metrics",
    "run_backtest",
]
