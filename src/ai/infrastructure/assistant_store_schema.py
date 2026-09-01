"""AssistantStore 的建表 DDL（会话 / 消息 / run / 事件 / 用量 / 授权六张表）。

与 `src/ops/infrastructure/store_schema.py` 同一范式：DDL 与读写分开放，门面只
负责 `executescript`。画像与记忆两张表**不在这里**——它们由
`assistant_store_profile._ensure_profile_schema` 按需补建（旧库升级路径）。

新增 `ai_` 开头的表，记得同时登记进
`src/ops/application/share_pack_sanitize.PERSONAL_TABLES`，否则分享包会外发。
"""
from __future__ import annotations

ASSISTANT_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS ai_sessions (
    id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idle', provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_sessions_updated ON ai_sessions(updated_at DESC);
CREATE TABLE IF NOT EXISTS ai_messages (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_session ON ai_messages(session_id, seq);
CREATE TABLE IF NOT EXISTS ai_agent_runs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL, provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0, error_text TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}', user_message_hash TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_session ON ai_agent_runs(session_id, started_at DESC);
CREATE TABLE IF NOT EXISTS ai_agent_events (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES ai_agent_runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL, UNIQUE(run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_ai_agent_events_run ON ai_agent_events(run_id, seq);
-- 15 天保留期截断按 created_at 走（本表 1-20 MB/日，全仓涨得最快）；(run_id, seq) 以 run_id 打头用不上。见 src/ops/README.md「保留期与垃圾回收」。
CREATE INDEX IF NOT EXISTS idx_ai_agent_events_created ON ai_agent_events(created_at);
CREATE TABLE IF NOT EXISTS ai_usage_daily (
    day TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, provider, model)
);
CREATE TABLE IF NOT EXISTS ai_execution_grants (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
    message_hash TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
    params_hash TEXT NOT NULL, params_redacted_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
    expires_at TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL, consumed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ai_grants_run ON ai_execution_grants(run_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_grants_identity
    ON ai_execution_grants(run_id, action, target, params_hash);
CREATE INDEX IF NOT EXISTS idx_ai_grants_created ON ai_execution_grants(created_at);
"""
