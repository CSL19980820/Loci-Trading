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
from src.backtest.application.horizon import (
    DEFAULT_HORIZONS,
    HorizonEvent,
    HorizonResult,
    aggregate_horizon_events,
    aggregate_returns,
    attach_instrument_names,
    entry_day_offset,
    mark_day_offset,
    run_horizon_backtest,
)
from src.backtest.application.runner import (
    MAX_HORIZON_SPAN_DAYS,
    backtest_strategy,
    backtest_strategy_horizon,
)

__all__ = [
    "DEFAULT_HORIZONS",
    "EXIT_REASONS",
    "MAX_HORIZON_SPAN_DAYS",
    "BacktestConfig",
    "BacktestResult",
    "HorizonEvent",
    "HorizonResult",
    "Trade",
    "aggregate_horizon_events",
    "aggregate_returns",
    "attach_instrument_names",
    "backtest_strategy",
    "backtest_strategy_horizon",
    "compute_metrics",
    "describe_fast_backend",
    "entry_day_offset",
    "fast_backtest_enabled",
    "mark_day_offset",
    "run_backtest",
    "run_backtest_fast",
    "run_horizon_backtest",
]
