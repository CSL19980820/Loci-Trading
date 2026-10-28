"""PostgreSQL schema for the online Loci data plane.

Quotes are stored as compact native types and indexed for the two real access
patterns: a date-ordered market scan and a code-ordered stock history.  Evidence
and task JSON remain JSONB so they can be queried without storing a second
SQLite-only representation.
"""
from __future__ import annotations

from typing import Any


SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS ledger;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS identity;

CREATE TABLE IF NOT EXISTS market.meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market.instruments (
    code text PRIMARY KEY,
    name text NOT NULL DEFAULT '',
    market text NOT NULL DEFAULT '',
    board text NOT NULL DEFAULT '',
    industry text NOT NULL DEFAULT '',
    instrument_type text NOT NULL DEFAULT 'STOCK'
        CHECK (instrument_type IN ('STOCK', 'INDEX')),
    list_date date,
    delist_date date,
    status text NOT NULL DEFAULT 'normal'
        CHECK (status IN ('normal', 'suspended', 'delisted')),
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market.quotes_daily (
    trade_date date NOT NULL,
    code text NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    amount double precision,
    outstanding_share double precision,
    turnover double precision,
    source text NOT NULL DEFAULT '',
    receipt_id text,
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, code)
);
CREATE INDEX IF NOT EXISTS quotes_code_date
    ON market.quotes_daily(code, trade_date DESC);
CREATE INDEX IF NOT EXISTS quotes_date_code
    ON market.quotes_daily(trade_date DESC, code);

CREATE TABLE IF NOT EXISTS market.adjust_factors (
    code text NOT NULL,
    trade_date date NOT NULL,
    hfq_factor double precision NOT NULL,
    source text NOT NULL DEFAULT '',
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS market.trading_calendar (
    trade_date date PRIMARY KEY,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market.ingest_watermark (
    code text PRIMARY KEY,
    last_trade_date date,
    last_synced_at timestamptz,
    status text NOT NULL DEFAULT 'ok',
    message text NOT NULL DEFAULT '',
    source text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS watermark_status ON market.ingest_watermark(status);

CREATE TABLE IF NOT EXISTS market.source_route_receipts (
    receipt_id text PRIMARY KEY,
    code text NOT NULL,
    lane text NOT NULL,
    requested_sources_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_source text NOT NULL DEFAULT '',
    fallback_used boolean NOT NULL DEFAULT false,
    unresolved boolean NOT NULL DEFAULT false,
    state text NOT NULL,
    coverage_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_url text NOT NULL DEFAULT '',
    published_at timestamptz,
    publication_status text NOT NULL DEFAULT 'not_observed',
    fetched_at timestamptz,
    as_of timestamptz,
    payload_sha256 text NOT NULL DEFAULT '',
    parser_revision text NOT NULL DEFAULT '',
    available_at timestamptz,
    availability_status text NOT NULL DEFAULT 'not_observed',
    coverage_start date,
    coverage_end date,
    request_start date,
    request_end date,
    error text NOT NULL DEFAULT '',
    generated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS source_receipts_code_lane
    ON market.source_route_receipts(code, lane, generated_at DESC);
CREATE INDEX IF NOT EXISTS source_receipts_lane_state
    ON market.source_route_receipts(lane, state, unresolved);
CREATE INDEX IF NOT EXISTS source_receipts_recent
    ON market.source_route_receipts(generated_at DESC, receipt_id DESC);

CREATE TABLE IF NOT EXISTS market.source_route_attempts (
    receipt_id text NOT NULL REFERENCES market.source_route_receipts(receipt_id) ON DELETE CASCADE,
    attempt_no integer NOT NULL,
    source_id text NOT NULL,
    state text NOT NULL,
    checked_at timestamptz,
    rows integer,
    fields_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_url text NOT NULL DEFAULT '',
    published_at timestamptz,
    publication_status text NOT NULL DEFAULT 'not_observed',
    fetched_at timestamptz,
    as_of timestamptz,
    payload_sha256 text NOT NULL DEFAULT '',
    parser_revision text NOT NULL DEFAULT '',
    available_at timestamptz,
    availability_status text NOT NULL DEFAULT 'not_observed',
    error text NOT NULL DEFAULT '',
    PRIMARY KEY (receipt_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS market.intel_snapshots (
    trade_date date NOT NULL,
    tool text NOT NULL,
    args_hash text NOT NULL,
    server text NOT NULL DEFAULT '',
    payload_json jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, tool, args_hash)
);

CREATE TABLE IF NOT EXISTS ledger.meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ledger.stocks (
    code text PRIMARY KEY,
    name text NOT NULL,
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger.candidate_reviews (
    id text PRIMARY KEY,
    occurred_on date NOT NULL,
    pool_id text NOT NULL,
    code text NOT NULL REFERENCES ledger.stocks(code),
    name text NOT NULL,
    score double precision,
    decision text NOT NULL,
    timing text NOT NULL DEFAULT '',
    reason text NOT NULL,
    rule_version text NOT NULL DEFAULT '潜龙',
    strategy_slug text NOT NULL DEFAULT '',
    strategy_revision text NOT NULL DEFAULT '',
    effective_params jsonb NOT NULL DEFAULT '{}'::jsonb,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    tier text NOT NULL DEFAULT 'core',
    source text NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL,
    UNIQUE (occurred_on, pool_id, code)
);
CREATE INDEX IF NOT EXISTS candidates_code_date
    ON ledger.candidate_reviews(code, occurred_on DESC, created_at DESC);
CREATE TABLE IF NOT EXISTS ledger.plans (
    id text PRIMARY KEY,
    occurred_on date NOT NULL,
    code text NOT NULL REFERENCES ledger.stocks(code),
    title text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    scenario text NOT NULL,
    entry_zone text NOT NULL DEFAULT '',
    stop_price double precision,
    target_price double precision,
    layers double precision,
    invalidation text NOT NULL DEFAULT '',
    rule_version text NOT NULL DEFAULT '潜龙',
    source text NOT NULL DEFAULT 'manual',
    supersedes_id text,
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS plans_code_date
    ON ledger.plans(code, occurred_on DESC, created_at DESC);
CREATE TABLE IF NOT EXISTS ledger.reviews (
    id text PRIMARY KEY,
    reviewed_on date NOT NULL,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    strategy_tag text NOT NULL DEFAULT '潜龙',
    outcome text NOT NULL,
    return_pct double precision,
    max_favorable_pct double precision,
    max_adverse_pct double precision,
    lesson text NOT NULL DEFAULT '',
    next_rule text NOT NULL DEFAULT '',
    source text NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_entity_id ON ledger.reviews(entity_id);
CREATE INDEX IF NOT EXISTS reviews_tag
    ON ledger.reviews(strategy_tag, reviewed_on DESC);
CREATE TABLE IF NOT EXISTS ledger.ai_judgments (
    id text PRIMARY KEY,
    occurred_on date NOT NULL,
    strategy_tag text NOT NULL,
    decision text NOT NULL,
    top_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    reason text NOT NULL DEFAULT '',
    provider text NOT NULL DEFAULT '',
    model text NOT NULL DEFAULT '',
    token_used bigint NOT NULL DEFAULT 0,
    source text NOT NULL DEFAULT 'ai',
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_judgments_strategy
    ON ledger.ai_judgments(strategy_tag, occurred_on DESC);

CREATE TABLE IF NOT EXISTS ledger.guardian_portfolio (
    id integer PRIMARY KEY CHECK (id=1),
    state jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger.guardian_cycles (
    slot text PRIMARY KEY,
    started double precision NOT NULL,
    status text NOT NULL,
    result jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS guardian_cycles_started
    ON ledger.guardian_cycles(started DESC);
CREATE TABLE IF NOT EXISTS ledger.guardian_trades (
    id text PRIMARY KEY,
    slot text NOT NULL,
    code text NOT NULL,
    occurred_at timestamptz NOT NULL,
    detail jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger.guardian_reports (
    report_key text PRIMARY KEY,
    trade_date date NOT NULL,
    period text NOT NULL,
    body text NOT NULL,
    facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS guardian_reports_date
    ON ledger.guardian_reports(trade_date DESC, period);
CREATE TABLE IF NOT EXISTS ledger.guardian_report_revisions (
    report_key text NOT NULL,
    revision integer NOT NULL,
    body text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (report_key, revision)
);
CREATE TABLE IF NOT EXISTS ledger.guardian_consultations (
    id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS ledger.guardian_consult_turns (
    id text PRIMARY KEY,
    conversation_id text NOT NULL,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS ledger.guardian_notices (
    slot text PRIMARY KEY,
    title text NOT NULL,
    body text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ledger.guardian_experience_versions (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    version integer NOT NULL,
    content text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger.guardian_diary_preferences (
    id integer PRIMARY KEY CHECK (id=1),
    prefs jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS ledger.guardian_diary_compactions (
    slot text PRIMARY KEY,
    at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger.stock_agent_profiles (
    id text PRIMARY KEY,
    config jsonb NOT NULL,
    state jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1,
    state_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    archived boolean NOT NULL DEFAULT false,
    active_run text,
    lease_until timestamptz,
    total_runs integer NOT NULL DEFAULT 0,
    total_actions integer NOT NULL DEFAULT 0,
    total_trades integer NOT NULL DEFAULT 0,
    cleaned_runs integer NOT NULL DEFAULT 0,
    cleanup_at timestamptz,
    latest_at timestamptz,
    latest_phase text,
    latest_status text,
    latest_summary text NOT NULL DEFAULT '',
    latest_actions jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE TABLE IF NOT EXISTS ledger.stock_agent_runs (
    id text PRIMARY KEY,
    agent_id text NOT NULL REFERENCES ledger.stock_agent_profiles(id),
    slot text NOT NULL,
    phase text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL,
    config_revision integer NOT NULL,
    state_version integer NOT NULL,
    summary text NOT NULL DEFAULT '',
    actions jsonb NOT NULL DEFAULT '[]'::jsonb,
    detail jsonb,
    UNIQUE (agent_id, slot)
);
CREATE INDEX IF NOT EXISTS stock_agent_runs_time
    ON ledger.stock_agent_runs(agent_id, started_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS ledger.stock_agent_trades (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    agent_id text NOT NULL REFERENCES ledger.stock_agent_profiles(id),
    run_id text NOT NULL,
    seq integer NOT NULL,
    at timestamptz NOT NULL,
    detail jsonb NOT NULL,
    UNIQUE (agent_id, run_id, seq)
);
CREATE INDEX IF NOT EXISTS stock_agent_trades_time
    ON ledger.stock_agent_trades(agent_id, at DESC, id DESC);
CREATE TABLE IF NOT EXISTS ledger.stock_agent_funding (
    agent_id text NOT NULL REFERENCES ledger.stock_agent_profiles(id),
    request_id text NOT NULL,
    at timestamptz NOT NULL,
    kind text NOT NULL,
    amount_cents bigint NOT NULL CHECK (amount_cents > 0),
    PRIMARY KEY (agent_id, request_id)
);
CREATE TABLE IF NOT EXISTS ledger.stock_agent_equity (
    agent_id text NOT NULL REFERENCES ledger.stock_agent_profiles(id),
    day date NOT NULL,
    at timestamptz NOT NULL,
    equity_cents bigint NOT NULL,
    funded_cents bigint NOT NULL,
    pnl_cents bigint NOT NULL,
    realized_pnl_cents bigint NOT NULL,
    fees_cents bigint NOT NULL,
    stale boolean NOT NULL DEFAULT false,
    PRIMARY KEY (agent_id, day)
);

CREATE TABLE IF NOT EXISTS ops.meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ops.jobs (
    id text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    kind text NOT NULL,
    cron text NOT NULL DEFAULT '',
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    last_run_at timestamptz,
    last_status text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_enabled ON ops.jobs(enabled, kind);
CREATE TABLE IF NOT EXISTS ops.job_runs (
    id text PRIMARY KEY,
    job_id text NOT NULL,
    job_name text NOT NULL DEFAULT '',
    kind text NOT NULL DEFAULT '',
    trigger text NOT NULL DEFAULT 'manual',
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    duration_ms bigint NOT NULL DEFAULT 0,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_text text NOT NULL DEFAULT '',
    owner_pid integer NOT NULL DEFAULT 0,
    idempotency_key text NOT NULL DEFAULT '',
    cancel_requested boolean NOT NULL DEFAULT false,
    heartbeat_at timestamptz
);
CREATE INDEX IF NOT EXISTS runs_job ON ops.job_runs(job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS runs_status ON ops.job_runs(status, started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS runs_idempotency
    ON ops.job_runs(idempotency_key) WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS runs_heartbeat ON ops.job_runs(status, heartbeat_at);
CREATE TABLE IF NOT EXISTS ops.llm_providers (
    id text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    protocol text NOT NULL,
    base_url text NOT NULL,
    encrypted_key bytea,
    key_last4 text NOT NULL DEFAULT '',
    default_model text NOT NULL DEFAULT '',
    models jsonb NOT NULL DEFAULT '[]'::jsonb,
    models_synced_at timestamptz,
    proxy_url text NOT NULL DEFAULT '',
    is_active boolean NOT NULL DEFAULT true,
    is_default boolean NOT NULL DEFAULT false,
    validated_at timestamptz,
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS ops.alert_rules (
    id text PRIMARY KEY,
    code text NOT NULL,
    name text NOT NULL DEFAULT '',
    enabled boolean NOT NULL DEFAULT true,
    condition_group jsonb NOT NULL DEFAULT '{}'::jsonb,
    market_hours_mode text NOT NULL DEFAULT 'session',
    cooldown_minutes integer NOT NULL DEFAULT 5,
    max_triggers_per_day integer NOT NULL DEFAULT 10,
    repeat_mode text NOT NULL DEFAULT 'repeat',
    expire_at timestamptz,
    plan_id_optional text NOT NULL DEFAULT '',
    channel_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    last_trigger_at timestamptz,
    trigger_count_today integer NOT NULL DEFAULT 0,
    trigger_date date,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS ops.alert_hits (
    id text PRIMARY KEY,
    rule_id text NOT NULL REFERENCES ops.alert_rules(id) ON DELETE CASCADE,
    trigger_bucket text NOT NULL,
    trigger_time timestamptz NOT NULL,
    snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    notify_ok boolean NOT NULL DEFAULT false,
    notify_error text NOT NULL DEFAULT '',
    UNIQUE (rule_id, trigger_bucket)
);
CREATE INDEX IF NOT EXISTS alert_hits_time ON ops.alert_hits(trigger_time DESC);
CREATE TABLE IF NOT EXISTS ops.signal_journal (
    id text PRIMARY KEY,
    tenant text NOT NULL,
    triggered_at timestamptz NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS signal_journal_tenant_time
    ON ops.signal_journal(tenant, triggered_at DESC);

CREATE TABLE IF NOT EXISTS identity.meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS identity.users (
    id text PRIMARY KEY,
    tenant_id text NOT NULL UNIQUE,
    username text NOT NULL,
    email text NOT NULL DEFAULT '',
    email_verified_at timestamptz,
    password_hash text,
    password_algo text NOT NULL DEFAULT '',
    password_updated_at timestamptz,
    must_change_password boolean NOT NULL DEFAULT false,
    display_name text NOT NULL DEFAULT '',
    avatar_url text NOT NULL DEFAULT '',
    bio text NOT NULL DEFAULT '',
    role text NOT NULL DEFAULT 'visitor' CHECK (role IN ('admin','visitor')),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','pending','disabled','deleted')),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    last_login_at timestamptz,
    view_tenant_id text NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower ON identity.users(lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower
    ON identity.users(lower(email)) WHERE email <> '';
CREATE TABLE IF NOT EXISTS identity.identities (
    id text PRIMARY KEY,
    user_id text NOT NULL,
    provider text NOT NULL,
    family text NOT NULL,
    subject text NOT NULL,
    union_key text,
    display_name text NOT NULL DEFAULT '',
    avatar_url text NOT NULL DEFAULT '',
    raw_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    last_login_at timestamptz,
    UNIQUE(provider, subject),
    UNIQUE(user_id, provider)
);
CREATE UNIQUE INDEX IF NOT EXISTS identities_union
    ON identity.identities(family, union_key)
    WHERE union_key IS NOT NULL AND union_key <> '';
CREATE TABLE IF NOT EXISTS identity.sessions (
    id text PRIMARY KEY,
    user_id text NOT NULL,
    identity_id text,
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    ip text NOT NULL DEFAULT '',
    user_agent text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sessions_user ON identity.sessions(user_id, revoked_at);
CREATE INDEX IF NOT EXISTS sessions_expiry ON identity.sessions(expires_at);
CREATE TABLE IF NOT EXISTS identity.email_verifications (
    id text PRIMARY KEY,
    user_id text NOT NULL,
    purpose text NOT NULL,
    email text NOT NULL,
    token_hash text NOT NULL UNIQUE,
    code text NOT NULL DEFAULT '',
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    request_ip text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS identity.oauth_states (
    state text PRIMARY KEY,
    provider text NOT NULL,
    status text NOT NULL,
    binding_hash text NOT NULL DEFAULT '',
    qr_content text NOT NULL DEFAULT '',
    user_id text,
    session_token_hash text,
    redirect_to text NOT NULL DEFAULT '/',
    error text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS identity.user_quotas (
    user_id text PRIMARY KEY,
    llm_monthly_tokens bigint NOT NULL DEFAULT 0,
    llm_daily_calls bigint NOT NULL DEFAULT 0,
    strategy_slots integer NOT NULL DEFAULT 0,
    publish_slots integer NOT NULL DEFAULT 0,
    job_slots integer NOT NULL DEFAULT 0,
    storage_mb bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS identity.usage_counters (
    user_id text NOT NULL,
    period text NOT NULL,
    metric text NOT NULL,
    value bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY(user_id, period, metric)
);
CREATE TABLE IF NOT EXISTS identity.audit_log (
    id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    actor_id text NOT NULL DEFAULT '',
    actor_name text NOT NULL DEFAULT '',
    action text NOT NULL,
    target text NOT NULL DEFAULT '',
    outcome text NOT NULL DEFAULT 'ok',
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_time ON identity.audit_log(occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_actor ON identity.audit_log(actor_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS identity.notifications (
    id text PRIMARY KEY,
    user_id text NOT NULL,
    kind text NOT NULL DEFAULT 'system',
    title text NOT NULL,
    body text NOT NULL DEFAULT '',
    link text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    read_at timestamptz
);
CREATE INDEX IF NOT EXISTS notifications_user
    ON identity.notifications(user_id, created_at DESC);
"""


def apply_schema(conn: Any) -> None:
    conn.raw.execute(SCHEMA_SQL)
    conn.commit()


__all__ = ["SCHEMA_SQL", "apply_schema"]
