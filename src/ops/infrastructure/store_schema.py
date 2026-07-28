"""运维库 schema DDL 与进程内建表缓存。"""
from __future__ import annotations

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- LLM 供应商：名称 + Base URL + 协议 + 密文 Key。
-- 不硬编码厂商枚举，新增一家 = 加一行配置，不改代码。
CREATE TABLE IF NOT EXISTS llm_providers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    protocol        TEXT NOT NULL CHECK (protocol IN ('openai_compatible', 'anthropic')),
    base_url        TEXT NOT NULL,
    encrypted_key   BLOB,
    key_last4       TEXT NOT NULL DEFAULT '',
    default_model   TEXT NOT NULL DEFAULT '',
    models_json     TEXT NOT NULL DEFAULT '[]',
    models_synced_at TEXT NOT NULL DEFAULT '',
    proxy_url       TEXT NOT NULL DEFAULT '',
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_default      INTEGER NOT NULL DEFAULT 0,
    validated_at    TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 定时任务。cron 表达式 + 类型 + 该类型自己的配置。
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    cron         TEXT NOT NULL DEFAULT '',
    config_json  TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_run_at  TEXT NOT NULL DEFAULT '',
    last_status  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled, kind);


-- 每次执行的痕迹。定时任务最怕的是"静默地一直失败"，
-- 所以每次都记，且失败要留完整错误文本而不只是一个状态码。
CREATE TABLE IF NOT EXISTS job_runs (
    id           TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL,
    job_name     TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT '',
    trigger      TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL DEFAULT '',
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    result_json  TEXT NOT NULL DEFAULT '{}',
    error_text   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_job ON job_runs(job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status, started_at DESC);

-- 量化战法档案：结构化记录战法形成背景、核心假设、适用市况和已知失效场景。
-- 有了这些，AI 做可行性分析和复盘优化时才有具体的可质疑点，
-- 而不是对着一行 description 瞎猜。
CREATE TABLE IF NOT EXISTS strategy_docs (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    source_text     TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT '',
    assumptions     TEXT NOT NULL DEFAULT '',
    market_cond     TEXT NOT NULL DEFAULT '',
    failure_modes   TEXT NOT NULL DEFAULT '',
    entry_timing    TEXT NOT NULL DEFAULT '',
    exit_rules      TEXT NOT NULL DEFAULT '',
    version         TEXT NOT NULL DEFAULT '1',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 自定义策略版本历史。最多保留10个版本，超出时删最旧的「未被任务引用」版本。
-- 被任务引用的版本不删：如果任务正在用某版本，删掉会让任务崩溃。
CREATE TABLE IF NOT EXISTS strategy_versions (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    code        TEXT NOT NULL,
    file_path   TEXT NOT NULL DEFAULT '',
    issues      TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sv_slug ON strategy_versions(slug, version DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sv_slug_active ON strategy_versions(slug) WHERE is_active=1;
"""

_SCHEMA_READY: set[str] = set()

#: 增量迁移语句（幂等）。旧 skills / mcp_servers 先迁出再 DROP。
_MIGRATIONS: list[str] = [
    """CREATE TABLE IF NOT EXISTS strategy_docs (
        slug            TEXT PRIMARY KEY,
        name            TEXT NOT NULL DEFAULT '',
        source_text     TEXT NOT NULL DEFAULT '',
        source_type     TEXT NOT NULL DEFAULT '',
        assumptions     TEXT NOT NULL DEFAULT '',
        market_cond     TEXT NOT NULL DEFAULT '',
        failure_modes   TEXT NOT NULL DEFAULT '',
        entry_timing    TEXT NOT NULL DEFAULT '',
        exit_rules      TEXT NOT NULL DEFAULT '',
        version         TEXT NOT NULL DEFAULT '1',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS strategy_versions (
        id          TEXT PRIMARY KEY,
        slug        TEXT NOT NULL,
        version     INTEGER NOT NULL,
        code        TEXT NOT NULL,
        file_path   TEXT NOT NULL DEFAULT '',
        issues      TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        is_active   INTEGER NOT NULL DEFAULT 1
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sv_slug ON strategy_versions(slug, version DESC)",
    "ALTER TABLE llm_providers ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0",
    "DROP TABLE IF EXISTS skills",
    "DROP TABLE IF EXISTS mcp_servers",
]
