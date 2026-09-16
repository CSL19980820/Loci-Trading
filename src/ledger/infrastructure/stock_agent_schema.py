"""智能体私有账本；与旧 guardian_* 表隔离，随租户 palace.db 备份。"""
SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_agent_profiles (
    id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    state_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    state_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    active_run TEXT,
    lease_until TEXT,
    total_runs INTEGER NOT NULL DEFAULT 0,
    total_actions INTEGER NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    cleaned_runs INTEGER NOT NULL DEFAULT 0,
    cleanup_at TEXT,
    latest_at TEXT,
    latest_phase TEXT,
    latest_status TEXT,
    latest_summary TEXT NOT NULL DEFAULT '',
    latest_actions_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS stock_agent_runs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES stock_agent_profiles(id),
    slot TEXT NOT NULL,
    phase TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    config_revision INTEGER NOT NULL,
    state_version INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    actions_json TEXT NOT NULL DEFAULT '[]',
    detail_json TEXT,
    UNIQUE(agent_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_stock_agent_runs_time
    ON stock_agent_runs(agent_id, started_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS stock_agent_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES stock_agent_profiles(id),
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    at TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    UNIQUE(agent_id, run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_stock_agent_trades_time ON stock_agent_trades(agent_id, at DESC, id DESC);
CREATE TABLE IF NOT EXISTS stock_agent_funding (
    agent_id TEXT NOT NULL REFERENCES stock_agent_profiles(id),
    request_id TEXT NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    PRIMARY KEY(agent_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_stock_agent_funding_time ON stock_agent_funding(agent_id, at DESC);
CREATE TABLE IF NOT EXISTS stock_agent_equity (
    agent_id TEXT NOT NULL REFERENCES stock_agent_profiles(id),
    day TEXT NOT NULL,
    at TEXT NOT NULL,
    equity_cents INTEGER NOT NULL,
    funded_cents INTEGER NOT NULL,
    pnl_cents INTEGER NOT NULL,
    realized_pnl_cents INTEGER NOT NULL,
    fees_cents INTEGER NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(agent_id, day)
);
"""
