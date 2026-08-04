"""行情仓 schema DDL、字段常量与进程内建表缓存。"""
from __future__ import annotations

from src.shared.paths import market_db as _default_market_db

DEFAULT_DB = _default_market_db()

SCHEMA_VERSION = 2

#: 面板字段 -> quotes_daily 列名。价格类字段会按复权方式换算，量额类不换算。
PRICE_FIELDS = ("open", "high", "low", "close")
RAW_FIELDS = ("volume", "amount", "turnover", "outstanding_share")
PANEL_FIELDS = PRICE_FIELDS + RAW_FIELDS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    market          TEXT NOT NULL DEFAULT '',
    board           TEXT NOT NULL DEFAULT '',
    industry        TEXT NOT NULL DEFAULT '',
    instrument_type TEXT NOT NULL DEFAULT 'STOCK'
                    CHECK (instrument_type IN ('STOCK', 'INDEX')),
    list_date       TEXT NOT NULL DEFAULT '',
    delist_date     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'normal'
                    CHECK (status IN ('normal', 'suspended', 'delisted')),
    updated_at      TEXT NOT NULL
);

-- 不复权原始价。按 (trade_date, code) 聚簇，让全市场日期区间扫描变顺序读。
CREATE TABLE IF NOT EXISTS quotes_daily (
    trade_date          TEXT NOT NULL,
    code                TEXT NOT NULL,
    open                REAL,
    high                REAL,
    low                 REAL,
    close               REAL,
    volume              REAL,
    amount              REAL,
    outstanding_share   REAL,
    turnover            REAL,
    source              TEXT NOT NULL DEFAULT '',
    fetched_at          TEXT NOT NULL,
    PRIMARY KEY (trade_date, code)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_quotes_code_date ON quotes_daily(code, trade_date);

-- 稀疏表：只有除权除息日才有行。读时前向填充。
CREATE TABLE IF NOT EXISTS adjust_factors (
    code        TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    hfq_factor  REAL NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (code, trade_date)
) WITHOUT ROWID;

-- 交易日历。看似冗余（日期都在 quotes_daily 里），但 SELECT DISTINCT
-- trade_date 是全表扫描：400 只票时 0.6s，全市场会涨到近 10s，而选股、
-- T+N 复盘、回测每次都要问"有哪些交易日"。单独一张几千行的小表，
-- 把这个高频问题从 O(行数) 降到 O(交易日数)。
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date  TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL
) WITHOUT ROWID;

-- 增量同步的断点：全量回填中断后可从这里续跑。
CREATE TABLE IF NOT EXISTS ingest_watermark (
    code            TEXT PRIMARY KEY,
    last_trade_date TEXT NOT NULL DEFAULT '',
    last_synced_at  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'ok',
    message         TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_watermark_status ON ingest_watermark(status);
"""

#: 进程内已建过 schema 的库路径。仅用于省掉重复 DDL，不是正确性依赖：
#: 表全部是 CREATE ... IF NOT EXISTS，重复执行也只是浪费一次锁。
_SCHEMA_READY: set[str] = set()
