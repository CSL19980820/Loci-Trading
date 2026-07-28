"""回测限界上下文。"""
from src.backtest.application.engine import (
    EXIT_REASONS,
    BacktestConfig,
    BacktestResult,
    Trade,
    compute_metrics,
    run_backtest,
)
from src.backtest.application.fast_engine import (
    describe_fast_backend,
    fast_backtest_enabled,
    run_backtest_fast,
)
from src.backtest.application.runner import backtest_strategy

__all__ = [
    "EXIT_REASONS",
    "BacktestConfig",
    "BacktestResult",
    "Trade",
    "backtest_strategy",
    "compute_metrics",
    "describe_fast_backend",
    "fast_backtest_enabled",
    "run_backtest",
    "run_backtest_fast",
]
