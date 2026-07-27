"""策略（战法）集合。

导入本包即完成所有内置策略的注册；新增战法只需在这里 import 一行。
"""
from src.strategies.audit import (
    AuditReport,
    LookAheadError,
    audit_source,
    audit_strategy,
    guard_strategy,
)
from src.strategies.base import (
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
from src.strategies.screener import ScreenResult, screen

# 导入即注册。顺序无关，slug 重复会在 register 里直接报错。
from src.strategies import lugaowen, qianlong  # noqa: F401  (side-effect import)

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
