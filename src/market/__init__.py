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
    LANE_AUCTION_SNAPSHOT,
    LANE_BROKEN_LIMIT_UP,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_LIMIT_UP_POOL,
    LANE_MARKET_EMOTION,
    MarketAdapter,
    TAPE_LANES,
    LANE_THEME_BOARD,
    LANE_THEME_MEMBERS,
    adapters_for_lane,
    all_adapters,
    clear_sticky,
    enabled_adapter_ids,
    fetch_capital_flow_routed,
    fetch_daily_best,
    fetch_daily_routed,
    fetch_instruments_routed,
    fetch_live_quotes_routed,
    fetch_minute_routed,
    get_adapter,
    lane_provider_enabled,
    lane_route_policy,
    list_catalog,
    peek_sticky,
    probe_lane,
    provider_disabled_lanes,
    provider_master_enabled,
    speedtest_daily,
)
from src.market.infrastructure.akshare_catalog import (
    MAX_MCP_SAMPLE_ROWS,
    discover_stock_capabilities,
    probe_stock_capability,
)
from src.market.infrastructure.akshare_tools import (
    MAX_BATCH_PROBE,
    catalog_entries,
    check_akshare_version,
    clear_catalog_cache,
    installed_akshare_version,
    probe_stock_capabilities_batch,
)
from src.market.infrastructure.sentinel import (
    DataQualityError,
    HealthReport,
    check_market_health,
    guard_market_health,
)
from src.market.infrastructure.sources import (
    BaostockSource,
    EastmoneySource,
    QuoteSource,
    SinaSource,
    SourceError,
    default_sources,
)
from src.market.infrastructure.store_schema import DEFAULT_DB
from src.market.infrastructure.store import MarketStore, normalize_code, to_sina_symbol
from src.market.infrastructure.live_tape import format_tray_title
from src.market.infrastructure.store_hot import (
    HOT_WINDOW_TRADING_DAYS,
    hot_unusable_reason,
    hot_window_shallow,
    mirror_recent_to_hot,
    mirror_to_hot,
    open_market_hot,
    open_screen_store,
)
from src.market.application.screen_live import (
    ScreenLiveError,
    fetch_live_spot_bars,
    in_live_screen_clock,
    overlay_live_day,
    should_overlay_live,
)
from src.market.application.screen_spot import (
    ScreenSpotError,
    ensure_today_quotes_for_screen,
    measure_day_coverage,
)
from src.market.infrastructure.write_lock import MarketWriteBusy, market_write_lock
from src.market.infrastructure.sync import (
    SyncReport,
    apply_today_spot,
    refresh_adjust_factors,
    sync_instruments,
    sync_quotes,
)
from src.market.infrastructure.turnover_repair import (
    backfill_missing_turnover,
    load_shares_asof,
    repair_inflated_turnover,
    rescale_star_daily_volumes,
)
from src.market.domain.universe import (
    ResolvedUniverse,
    UniverseError,
    UniverseSpec,
    classify_board,
    enrich_picks,
    is_st_name,
    list_presets,
    resolve_universe,
    universe_stats,
)
from src.market.domain.provenance import SourceAttemptRecord, SourceRouteReceipt
from src.market.domain.tape import (
    AuctionSnapshot,
    BrokenLimitUp,
    LimitUpLadder,
    MarketEmotion,
    TapeAttempt,
    TapeProvenance,
    TapeRequest,
    TapeResult,
    ThemeBoard,
    ThemeMembers,
    ThemeRank,
)
from src.market.infrastructure.tape.base import TapeProvider, TapeProviderError
from src.market.infrastructure.tape.cache_provider import CachedTapeProvider
from src.market.infrastructure.tape.legacy_bridge import (
    LEGACY_TOOL_TO_LANE,
    legacy_call_tool,
    make_legacy_tape_call,
)
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.registry import (
    all_providers,
    register_provider,
    reset_registry,
)
from src.market.infrastructure.tape.router import (
    clear_provider_cooldown,
    fetch_tape,
    reset_provider_circuit,
    route_tape,
    tape_readiness,
)
from src.market.infrastructure import sina, tencent

from src.market.application.intraday import (
    CaptureReport,
    CaptureSpec,
    capture_snapshots,
  default_specs,
    intraday_status,
)
from src.market.infrastructure.intraday_archive import (
    IntradayArchiveError,
    describe as describe_intraday,
    list_days as list_intraday_days,
    read_manifest as read_intraday_manifest,
    read_snapshot as read_intraday_snapshot,
    write_snapshot as write_intraday_snapshot,
)
from src.market.infrastructure.intraday_prune import (
    DEFAULT_RETENTION_DAYS,
    IntradayPruneError,
    prune_intraday,
)
from src.market.application.reclaim import (
    RECLAIMABLE_INDEXES,
    ReclaimReport,
    reclaim_market_db,
)
from src.market.application.data_quality import (
    QualityThresholds,
    inspect_market_data,
)

# 实时推流与实时信号（大屏纯读路径）。
from src.market.application.live_bars import LiveBarBook, get_live_bars
from src.market.application.live_hub import (
    LiveHub,
    Snapshot as LiveSnapshot,
    Subscription as LiveSubscription,
    get_live_hub,
)
from src.market.application.realtime_signals import (
    RULES as REALTIME_RULES,
    RealtimeSignalEngine,
    get_signal_engine,
)
from src.market.application.watchlist import (
    ALL_PRESETS,
    MAX_PRESET_CODES,
    WatchlistError,
    list_watchlist_presets,
    resolve_preset,
)

__all__ = [
    "QualityThresholds",
    "inspect_market_data",
    "ALL_PRESETS",
    "LiveBarBook",
    "LiveHub",
    "LiveSnapshot",
    "LiveSubscription",
    "MAX_PRESET_CODES",
    "REALTIME_RULES",
    "RealtimeSignalEngine",
    "WatchlistError",
    "get_live_bars",
    "get_live_hub",
    "get_signal_engine",
    "list_watchlist_presets",
    "resolve_preset",
    "ALL_LANES",
    "AdapterError",
    "AdapterMeta",
    "AuctionSnapshot",
    "BaostockSource",
    "BrokenLimitUp",
    "DataQualityError",
    "DEFAULT_DB",
    "EastmoneySource",
    "HealthReport",
    "HOT_WINDOW_TRADING_DAYS",
    "hot_unusable_reason",
    "hot_window_shallow",
    "LANE_AUCTION_SNAPSHOT",
    "LANE_BROKEN_LIMIT_UP",
    "LANE_HIST_DAILY",
    "LANE_INSTRUMENTS",
    "LANE_LIMIT_UP_POOL",
    "LANE_MARKET_EMOTION",
    "LANE_THEME_BOARD",
    "LANE_THEME_MEMBERS",
    "LimitUpLadder",
    "MAX_BATCH_PROBE",
    "MAX_MCP_SAMPLE_ROWS",
    "MarketAdapter",
    "MarketEmotion",
    "MarketStore",
    "QuoteSource",
    "SinaSource",
    "SourceError",
    "SourceAttemptRecord",
    "SourceRouteReceipt",
    "SyncReport",
    "TAPE_LANES",
    "TapeAttempt",
    "CachedTapeProvider",
    "LEGACY_TOOL_TO_LANE",
    "LocalTapeProvider",
    "TapeProvider",
    "TapeProviderError",
    "TapeProvenance",
    "TapeRequest",
    "TapeResult",
    "ThemeBoard",
    "ThemeMembers",
    "ThemeRank",
    "all_providers",
    "ResolvedUniverse",
    "UniverseError",
    "enrich_picks",
    "UniverseSpec",
    "adapters_for_lane",
    "all_adapters",
    "MarketWriteBusy",
    "ScreenLiveError",
    "ScreenSpotError",
    "apply_today_spot",
    "ensure_today_quotes_for_screen",
    "fetch_live_spot_bars",
    "in_live_screen_clock",
    "overlay_live_day",
    "should_overlay_live",
    "market_write_lock",
    "measure_day_coverage",
    "refresh_adjust_factors",
    "backfill_missing_turnover",
    "CaptureReport",
    "CaptureSpec",
    "DEFAULT_RETENTION_DAYS",
    "IntradayArchiveError",
    "IntradayPruneError",
    "capture_snapshots",
    "default_specs",
    "describe_intraday",
    "intraday_status",
    "list_intraday_days",
    "prune_intraday",
    "read_intraday_manifest",
    "read_intraday_snapshot",
    "write_intraday_snapshot",
    "RECLAIMABLE_INDEXES",
    "ReclaimReport",
    "reclaim_market_db",
    "catalog_entries",
    "check_akshare_version",
    "check_market_health",
    "classify_board",
    "clear_catalog_cache",
    "clear_provider_cooldown",
    "clear_sticky",
    "default_sources",
    "discover_stock_capabilities",
    "enabled_adapter_ids",
    "fetch_capital_flow_routed",
    "fetch_daily_best",
    "fetch_daily_routed",
    "fetch_instruments_routed",
    "fetch_live_quotes_routed",
    "fetch_minute_routed",
    "fetch_tape",
    "legacy_call_tool",
    "make_legacy_tape_call",
    "format_tray_title",
    "get_adapter",
    "guard_market_health",
    "installed_akshare_version",
    "is_st_name",
    "list_catalog",
    "lane_provider_enabled",
    "lane_route_policy",
    "list_presets",
    "load_shares_asof",
    "mirror_recent_to_hot",
    "mirror_to_hot",
    "normalize_code",
    "open_market_hot",
    "open_screen_store",
    "peek_sticky",
    "probe_lane",
    "probe_stock_capabilities_batch",
    "probe_stock_capability",
    "provider_disabled_lanes",
    "provider_master_enabled",
    "resolve_universe",
    "repair_inflated_turnover",
    "rescale_star_daily_volumes",
    "register_provider",
    "reset_registry",
    "reset_provider_circuit",
    "route_tape",
    "tape_readiness",
    "speedtest_daily",
    "sync_instruments",
    "sync_quotes",
    "sina",
    "tencent",
    "to_sina_symbol",
    "universe_stats",
]
