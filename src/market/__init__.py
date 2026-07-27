"""行情数据仓。

与账本 (qianlong.db) 物理隔离：行情是可从外部源重建的缓存，不需要账本
那套不可变审计语义，也不该和交互式记账抢同一把 SQLite 写锁。

对外只暴露三样东西：
- MarketStore  读写与面板加载
- 数据源适配器  SinaSource / EastmoneySource
- sync_quotes  同步编排（全量回填 / 每日增量）
"""
from src.market.sentinel import (
    DataQualityError,
    HealthReport,
    check_market_health,
    guard_market_health,
)
from src.market.sources import (
    EastmoneySource,
    QuoteSource,
    SinaSource,
    SourceError,
    default_sources,
)
from src.market.store import MarketStore, normalize_code, to_sina_symbol
from src.market.sync import SyncReport, sync_instruments, sync_quotes

__all__ = [
    "DataQualityError",
    "EastmoneySource",
    "HealthReport",
    "MarketStore",
    "QuoteSource",
    "SinaSource",
    "SourceError",
    "SyncReport",
    "check_market_health",
    "default_sources",
    "guard_market_health",
    "normalize_code",
    "sync_instruments",
    "sync_quotes",
    "to_sina_symbol",
]
