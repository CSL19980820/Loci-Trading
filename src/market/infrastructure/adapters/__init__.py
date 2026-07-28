"""数据线路适配器包。

把「可接入 API」做成代码注册表；字段转换只写在各 Adapter 内。
日常同步默认走 ``fetch_daily_routed``（粘性竞速）。
"""
from __future__ import annotations

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.exchange_list_adapter import ExchangeListAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    all_adapters,
    enabled_adapter_ids,
    get_adapter,
    list_catalog,
    reset_registry,
)
from src.market.infrastructure.adapters.router import (
    STICKY_TTL_SEC,
    clear_sticky,
    fetch_adjust_factors_routed,
    fetch_daily_best,
    fetch_daily_routed,
    fetch_instruments_routed,
    fetch_live_quotes_routed,
    fetch_spot_routed,
    peek_sticky,
    pin_sticky,
    probe_lane,
    speedtest_daily,
)
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import (
    ALL_LANES,
    AdapterMeta,
    LANE_ADJUST_FACTOR,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_INTEL_MCP,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    ProbeResult,
    SpeedTestResult,
)

__all__ = [
    "ALL_LANES",
    "AdapterError",
    "AdapterMeta",
    "EastmoneyAdapter",
    "ExchangeListAdapter",
    "LANE_ADJUST_FACTOR",
    "LANE_CAPITAL_FLOW",
    "LANE_HIST_DAILY",
    "LANE_INSTRUMENTS",
    "LANE_INTEL_MCP",
    "LANE_MINUTE",
    "LANE_SPOT_BATCH",
    "MarketAdapter",
    "ProbeResult",
    "STICKY_TTL_SEC",
    "SinaAdapter",
    "SpeedTestResult",
    "TencentAdapter",
    "adapters_for_lane",
    "all_adapters",
    "clear_sticky",
    "enabled_adapter_ids",
    "fetch_adjust_factors_routed",
    "fetch_daily_best",
    "fetch_daily_routed",
    "fetch_instruments_routed",
    "fetch_live_quotes_routed",
    "fetch_spot_routed",
    "get_adapter",
    "list_catalog",
    "peek_sticky",
    "pin_sticky",
    "probe_lane",
    "reset_registry",
    "speedtest_daily",
]
