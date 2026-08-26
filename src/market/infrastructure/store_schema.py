"""行情仓 schema DDL、字段常量与进程内建表缓存。"""
from __future__ import annotations

from src.shared.paths import market_db as _default_market_db

DEFAULT_DB = _default_market_db()

#: 7:补 idx_source_receipts_recent。加索引必须配套 bump——`init_schema()` 只在
#: `meta.schema_version` 与本常量不符时才跑 DDL,不 bump 的话新索引永远只出现在
#: 新建的库上,已有的生产库一辈子享受不到(实测就踩了这一脚)。
SCHEMA_VERSION = 7

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
    receipt_id          TEXT,
    fetched_at          TEXT NOT NULL,
    PRIMARY KEY (trade_date, code)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_quotes_code_date ON quotes_daily(code, trade_date);
-- idx_quotes_receipt 在 migrate 里建：旧库先补列再索引，避免 CREATE INDEX 踩无列。

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

-- 一次逐标的同步的来源、覆盖范围与尝试终态。行情缓存可重建，但研究 run card
-- 必须能追溯本次落盘实际用了什么来源，以及未解析/跳过的原因。
CREATE TABLE IF NOT EXISTS source_route_receipts (
    receipt_id              TEXT PRIMARY KEY,
    code                    TEXT NOT NULL,
    lane                    TEXT NOT NULL,
    requested_sources_json  TEXT NOT NULL DEFAULT '[]',
    selected_source         TEXT NOT NULL DEFAULT '',
    fallback_used           INTEGER NOT NULL DEFAULT 0,
    unresolved              INTEGER NOT NULL DEFAULT 0,
    state                   TEXT NOT NULL,
    coverage_json           TEXT NOT NULL DEFAULT '{}',
    source_url              TEXT NOT NULL DEFAULT '',
    published_at            TEXT NOT NULL DEFAULT '',
    publication_status      TEXT NOT NULL DEFAULT 'not_observed',
    fetched_at              TEXT NOT NULL DEFAULT '',
    as_of                   TEXT NOT NULL DEFAULT '',
    payload_sha256          TEXT NOT NULL DEFAULT '',
    parser_revision         TEXT NOT NULL DEFAULT '',
    available_at            TEXT NOT NULL DEFAULT '',
    availability_status     TEXT NOT NULL DEFAULT 'not_observed',
    coverage_start          TEXT NOT NULL DEFAULT '',
    coverage_end            TEXT NOT NULL DEFAULT '',
    request_start           TEXT NOT NULL DEFAULT '',
    request_end             TEXT NOT NULL DEFAULT '',
    error                   TEXT NOT NULL DEFAULT '',
    generated_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_receipts_code_lane
    ON source_route_receipts(code, lane, generated_at);
-- 未挂日 K 的失败/skip 回执范围查询（lane + 终态）。
CREATE INDEX IF NOT EXISTS idx_source_receipts_lane_state
    ON source_route_receipts(lane, state, unresolved);

-- 体检取「最近 N 条回执」的排序键。没有它,`check_ohlc_reject_rate` 与
-- `check_race_fallback_rate` 各要全表扫 106 万行 + 临时 B 树排序才拿到 200 行
-- (EQP 实测 `SCAN source_route_receipts` + `USE TEMP B-TREE FOR ORDER BY`,单条 945ms);
-- 两条合计占 /api/market/health 4 秒里的一半。
CREATE INDEX IF NOT EXISTS idx_source_receipts_recent
    ON source_route_receipts(generated_at DESC, receipt_id DESC);

CREATE TABLE IF NOT EXISTS source_route_attempts (
    receipt_id  TEXT NOT NULL,
    attempt_no  INTEGER NOT NULL,
    source_id   TEXT NOT NULL,
    state       TEXT NOT NULL,
    checked_at  TEXT NOT NULL DEFAULT '',
    rows        INTEGER,
    fields_json TEXT NOT NULL DEFAULT '[]',
    source_url TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    publication_status TEXT NOT NULL DEFAULT 'not_observed',
    fetched_at TEXT NOT NULL DEFAULT '',
    as_of TEXT NOT NULL DEFAULT '',
    payload_sha256 TEXT NOT NULL DEFAULT '',
    parser_revision TEXT NOT NULL DEFAULT '',
    available_at TEXT NOT NULL DEFAULT '',
    availability_status TEXT NOT NULL DEFAULT 'not_observed',
    error       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (receipt_id, attempt_no)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_source_attempts_source
    ON source_route_attempts(source_id, state);
"""

#: intel 域 MCP 快照缓存（可整表删除重建）；DDL 归属 market.db。
_INTEL_SNAPSHOTS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS intel_snapshots (
        trade_date      TEXT NOT NULL,
        tool            TEXT NOT NULL,
        args_hash       TEXT NOT NULL,
        server          TEXT NOT NULL DEFAULT '',
        payload_json    TEXT NOT NULL,
        fetched_at      TEXT NOT NULL,
        PRIMARY KEY (trade_date, tool, args_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_intel_snapshots_tool "
    "ON intel_snapshots(trade_date, tool, fetched_at DESC)",
)

#: 进程内已建过 schema 的库路径。仅用于省掉重复 DDL，不是正确性依赖：
#: 表全部是 CREATE ... IF NOT EXISTS，重复执行也只是浪费一次锁。
_SCHEMA_READY: set[str] = set()
