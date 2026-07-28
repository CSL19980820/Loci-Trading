"""策略（战法）限界上下文。导入本包即注册内置策略。"""
from src.strategy.application.audit import (
    AuditReport,
    LookAheadError,
    audit_source,
    audit_strategy,
    guard_strategy,
)
from src.strategy.domain.base import (
    ENTRY_TIMINGS,
    SignalResult,
    StrategyEngine,
    StrategyError,
    all_strategies,
    describe_all,
    get,
    merge_params,
    register,
)
from src.strategy.application.screener import ScreenResult, screen

from src.strategy.application import lugaowen, qianlong  # noqa: F401

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
    "merge_params",
    "register",
    "screen",
]
