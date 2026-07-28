"""行情数据仓。

与账本 (palace.db) 物理隔离：行情是可从外部源重建的缓存，不需要账本
那套不可变审计语义，也不该和交互式记账抢同一把 SQLite 写锁。

对外暴露：
- MarketStore  读写与面板加载
- QuoteSource  旧降级链（``sources=`` 注入时）
- adapters     数据线路 / 粘性竞速（日常 sync 默认）
- sync_quotes  同步编排（全量回填 / 每日增量）
"""
from src.market.infrastructure.adapters import (
    ALL_LANES,
    AdapterError,
    AdapterMeta,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    MarketAdapter,
    adapters_for_lane,
    all_adapters,
    clear_sticky,
    enabled_adapter_ids,
    fetch_daily_best,
    fetch_daily_routed,
    fetch_instruments_routed,
    fetch_live_quotes_routed,
    get_adapter,
    list_catalog,
    peek_sticky,
    probe_lane,
    speedtest_daily,
)
from src.market.infrastructure.sentinel import (
    DataQualityError,
    HealthReport,
    check_market_health,
    guard_market_health,
)
from src.market.infrastructure.sources import (
    EastmoneySource,
    QuoteSource,
    SinaSource,
    SourceError,
    default_sources,
)
from src.market.infrastructure.store import MarketStore, normalize_code, to_sina_symbol
from src.market.infrastructure.sync import SyncReport, apply_today_spot, sync_instruments, sync_quotes
from src.market.domain.universe import (
    UniverseError,
    UniverseSpec,
    classify_board,
    is_st_name,
    list_presets,
    resolve_universe,
    universe_stats,
)
from src.market.infrastructure import sina, tencent

__all__ = [
    "ALL_LANES",
    "AdapterError",
    "AdapterMeta",
    "DataQualityError",
    "EastmoneySource",
    "HealthReport",
    "LANE_HIST_DAILY",
    "LANE_INSTRUMENTS",
    "MarketAdapter",
    "MarketStore",
    "QuoteSource",
    "SinaSource",
    "SourceError",
    "SyncReport",
    "UniverseError",
    "UniverseSpec",
    "adapters_for_lane",
    "all_adapters",
    "apply_today_spot",
    "check_market_health",
    "classify_board",
    "clear_sticky",
    "default_sources",
    "enabled_adapter_ids",
    "fetch_daily_best",
    "fetch_daily_routed",
    "fetch_instruments_routed",
    "fetch_live_quotes_routed",
    "get_adapter",
    "guard_market_health",
    "is_st_name",
    "list_catalog",
    "list_presets",
    "normalize_code",
    "peek_sticky",
    "probe_lane",
    "resolve_universe",
    "speedtest_daily",
    "sync_instruments",
    "sync_quotes",
    "sina",
    "tencent",
    "to_sina_symbol",
    "universe_stats",
]
