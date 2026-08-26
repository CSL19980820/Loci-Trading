"""次日情景预案：按开盘情景动态调仓 / 择位 + 竞价窗纠偏。

预案不是「选股池直接开仓」，也不是对错判决；而是每只票的动态应对：
- 相对昨收划分高/低/平开
- 各情景：是否接（buy）、仓位层数（layers）、可接/理想价位带（entry_pct）
- 过高可减层、等回踩价位或本情景暂缓；不是「高开=错误」
- 09:15–09:30（含 09:25 撮合后至连续竞价前）对照实时竞价持续判断 follow / revise / abandon / wait；默认不落开仓

实现拆分到同目录子模块；本包 re-export 保持 ``from src.ops.application.nextday_plan import ...`` 兼容。
"""
from __future__ import annotations

from src.ops.application.plan_build import (
    build_plan_item,
    default_scenarios,
    enrich_plan_items,
    format_plan_body,
    resolve_entry_mode,
)
from src.ops.application.scenario_gates import (
    AuctionStance,
    ScenarioKey,
    classify_open_scenario,
    evaluate_auction_stance,
    merge_ai_orders_with_gates,
    price_in_entry_band,
    scenario_gated_open_orders,
)
from src.ops.application.session_clock import SessionClock, SessionPhase, session_clock

__all__ = [
    "AuctionStance",
    "ScenarioKey",
    "SessionClock",
    "SessionPhase",
    "build_plan_item",
    "classify_open_scenario",
    "default_scenarios",
    "enrich_plan_items",
    "evaluate_auction_stance",
    "format_plan_body",
    "merge_ai_orders_with_gates",
    "price_in_entry_band",
    "resolve_entry_mode",
    "scenario_gated_open_orders",
    "session_clock",
]
