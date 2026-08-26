"""策略（战法）限界上下文。导入本包即注册内置策略。"""
from src.strategy.application.audit import (
    AuditReport,
    LookAheadError,
    audit_source,
    audit_strategy,
    guard_strategy,
)
from src.strategy.application.catalog import all_strategies, describe_all, get
from src.strategy.domain.base import (
    ENTRY_TIMINGS,
    SignalResult,
    StrategyEngine,
    StrategyError,
    is_builtin_registered,
    merge_params,
    register,
)
from src.strategy.application.screener import ScreenResult, screen

from src.strategy.application import (  # noqa: F401
    qianlong,
    tail_resonance,
    yangshi_tail,
)

__all__ = [
    "ENTRY_TIMINGS",
    "AuditReport",
    "LookAheadError",
    "ScreenResult",
    "SignalResult",
    "StrategyEngine",
    "StrategyError",
    "all_strategies",
    "audit_source",
    "audit_strategy",
    "describe_all",
    "get",
    "guard_strategy",
    "is_builtin_registered",
    "merge_params",
    "register",
    "screen",
]
