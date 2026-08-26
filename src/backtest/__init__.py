"""回测限界上下文。"""
from src.backtest.application.engine import (
    EXIT_REASONS,
    BacktestConfig,
    BacktestResult,
    Trade,
    compute_metrics,
    run_backtest,
)
from src.backtest.application.performance import compute_trade_performance
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
    attach_instrument_names,
    entry_day_offset,
    mark_day_offset,
    run_horizon_backtest,
)
from src.backtest.application.runner import (
    MAX_HORIZON_SPAN_DAYS,
    backtest_strategy,
    backtest_strategy_horizon,
    build_universe_control,
    execute_backtest_context,
    prepare_backtest_context,
)
from src.backtest.application.research_analysis import (
    BacktestResearchAnalysis,
    analyze_backtest_research,
)
from src.backtest.application.research_portfolio import (
    PortfolioResearchConfig,
    PortfolioResearchResult,
    analyze_portfolio,
)
from src.backtest.application.research_validation import TrainOOSSplit

__all__ = [
    "DEFAULT_HORIZONS",
    "EXIT_REASONS",
    "MAX_HORIZON_SPAN_DAYS",
    "BacktestConfig",
    "BacktestResearchAnalysis",
    "BacktestResult",
    "HorizonEvent",
    "HorizonResult",
    "PortfolioResearchConfig",
    "PortfolioResearchResult",
    "Trade",
    "TrainOOSSplit",
    "aggregate_horizon_events",
    "analyze_backtest_research",
    "analyze_portfolio",
    "attach_instrument_names",
    "backtest_strategy",
    "backtest_strategy_horizon",
    "build_universe_control",
    "compute_metrics",
    "compute_trade_performance",
    "describe_fast_backend",
    "entry_day_offset",
    "fast_backtest_enabled",
    "mark_day_offset",
    "execute_backtest_context",
    "prepare_backtest_context",
    "run_backtest",
    "run_backtest_fast",
    "run_horizon_backtest",
]
