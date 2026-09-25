"""数据线路适配器包。

把「可接入 API」做成代码注册表；字段转换走共享管线
（``domain/source_contract`` + ``infrastructure/pipeline``）。
日常同步默认走 ``fetch_daily_routed``（粘性竞速）。
"""
from __future__ import annotations

from src.market.infrastructure.adapters.base import (
    AdapterError,
    MarketAdapter,
    window_start_date,
)
from src.market.infrastructure.adapters.baostock_adapter import BaostockAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.exchange_list_adapter import ExchangeListAdapter
from src.market.infrastructure.adapters.hithink_adapter import HithinkAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    all_adapters,
    enabled_adapter_ids,
    get_adapter,
    lane_provider_enabled,
    lane_route_policy,
    list_catalog,
    provider_disabled_lanes,
    provider_master_enabled,
    reset_registry,
)
from src.market.infrastructure.adapters.router import (
    STICKY_TTL_SEC,
    clear_sticky,
    fetch_adjust_factors_routed,
    fetch_capital_flow_routed,
    fetch_daily_best,
    fetch_daily_routed,
    fetch_instruments_routed,
    fetch_live_quotes_routed,
    fetch_minute_routed,
    fetch_spot_routed,
    peek_sticky,
    pin_sticky,
    probe_lane,
    speedtest_daily,
)
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tdx_adapter import TdxAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import (
    ALL_LANES,
    AdapterMeta,
    LANE_ADJUST_FACTOR,
    LANE_AUCTION_SNAPSHOT,
    LANE_BROKEN_LIMIT_UP,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_INTEL_MCP,
    LANE_LIMIT_UP_POOL,
    LANE_MARKET_EMOTION,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    LANE_THEME_BOARD,
    LANE_THEME_MEMBERS,
    ProbeResult,
    SpeedTestResult,
    TAPE_LANES,
)

__all__ = [
    "ALL_LANES",
    "AdapterError",
    "AdapterMeta",
    "BaostockAdapter",
    "LANE_AUCTION_SNAPSHOT",
    "LANE_BROKEN_LIMIT_UP",
    "EastmoneyAdapter",
    "ExchangeListAdapter",
    "HithinkAdapter",
    "LANE_ADJUST_FACTOR",
    "LANE_CAPITAL_FLOW",
    "LANE_HIST_DAILY",
    "LANE_INSTRUMENTS",
    "LANE_INTEL_MCP",
    "LANE_LIMIT_UP_POOL",
    "LANE_MARKET_EMOTION",
    "LANE_MINUTE",
    "LANE_SPOT_BATCH",
    "LANE_THEME_BOARD",
    "LANE_THEME_MEMBERS",
    "MarketAdapter",
    "ProbeResult",
    "STICKY_TTL_SEC",
    "SinaAdapter",
    "SpeedTestResult",
    "TAPE_LANES",
    "TdxAdapter",
    "TencentAdapter",
    "adapters_for_lane",
    "all_adapters",
    "clear_sticky",
    "enabled_adapter_ids",
    "fetch_adjust_factors_routed",
    "fetch_capital_flow_routed",
    "fetch_daily_best",
    "fetch_daily_routed",
    "fetch_instruments_routed",
    "fetch_live_quotes_routed",
    "fetch_minute_routed",
    "fetch_spot_routed",
    "get_adapter",
    "lane_provider_enabled",
    "lane_route_policy",
    "list_catalog",
    "peek_sticky",
    "pin_sticky",
    "probe_lane",
    "provider_disabled_lanes",
    "provider_master_enabled",
    "reset_registry",
    "speedtest_daily",
    "window_start_date",
]

# 行情域名遇系统代理 ProxyError 时自动直连重试（akshare 东财等）
from src.market.infrastructure.http_client import install_market_proxy_fallback

install_market_proxy_fallback()
