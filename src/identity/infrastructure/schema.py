"""identity.db 的 DDL 与迁移。

归属：**全局唯一**，绝不按租户分库——身份本身就是跨租户的东西。

可重建性：**不可重建**。这里丢一行 = 一个用户永久失联。备份优先级与
``palace.db`` 同级。

迁移风格与 ops.db 对齐：``_SCHEMA`` 建初始表，``_MIGRATIONS`` 平铺追加，
每次连接无条件重跑（全部语句自身幂等）。加表只准往 ``_MIGRATIONS`` 尾部追加。
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
 value   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 账号。tenant_id 决定私有库落在 data/tenants/<tenant_id>/；
-- 主管理员是 '__primary__'，直接复用存量 data/ 目录（升级零迁移）。
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    tenant_id            TEXT NOT NULL UNIQUE,
    username    TEXT NOT NULL,
    email                TEXT NOT NULL DEFAULT '',
    email_verified_at    TEXT,
    password_hash        TEXT,
    password_algo        TEXT NOT NULL DEFAULT '',
    password_updated_at  TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    display_name       TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    bio        TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'visitor',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at         TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    last_login_at        TEXT,
    CHECK (role IN ('admin', 'visitor')),
CHECK (status IN ('active', 'pending', 'disabled', 'deleted'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username ON users(lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(lower(email)) WHERE email <> '';

-- 一个账号可以挂多种登录方式。合并只认 (provider, subject) 与 (family, union_key)，
-- 永远不拿昵称做合并（昵称可改、可重名）。
CREATE TABLE IF NOT EXISTS identities (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    provider      TEXT NOT NULL,
    family        TEXT NOT NULL,
    subject       TEXT NOT NULL,
    union_key     TEXT,
    display_name  TEXT NOT NULL DEFAULT '',
  avatar_url    TEXT NOT NULL DEFAULT '',
    raw_profile   TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    last_login_at TEXT,
  CHECK (family IN ('local', 'wechat', 'qq', 'mock'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_identities_subject ON identities(provider, subject);
CREATE UNIQUE INDEX IF NOT EXISTS ux_identities_union
    ON identities(family, union_key) WHERE union_key IS NOT NULL AND union_key <> '';
CREATE UNIQUE INDEX IF NOT EXISTS ux_identities_user_provider ON identities(user_id, provider);

-- 会话。id 就是 sha256(明文 token)；明文只活在 Cookie 里。
-- 滑动过期 + 绝对上限双闸门：长期不登录会掉线，长期在线也会强制重登。
CREATE TABLE IF NOT EXISTS sessions (
    id        TEXT PRIMARY KEY,
user_id             TEXT NOT NULL,
    identity_id         TEXT,
    created_at   TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    expires_at          TEXT NOT NULL,
    absolute_expires_at TEXT NOT NULL,
    revoked_at TEXT,
    ip         TEXT NOT NULL DEFAULT '',
    user_agent          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id, revoked_at);
CREATE INDEX IF NOT EXISTS ix_sessions_expiry ON sessions(expires_at);

-- 邮箱验证 / 密码重置。只存 token 的 sha256；单次使用。
CREATE TABLE IF NOT EXISTS email_verifications (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    purpose    TEXT NOT NULL,
email      TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    code       TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    request_ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK (purpose IN ('verify', 'reset'))
);
CREATE INDEX IF NOT EXISTS ix_ev_live ON email_verifications(user_id, purpose, used_at);

-- 扫码 / 跳转登录的一次性票据。confirmed -> consumed 只允许发生一次。
CREATE TABLE IF NOT EXISTS oauth_states (
    state           TEXT PRIMARY KEY,
 provider    TEXT NOT NULL,
    status             TEXT NOT NULL,
    binding_hash       TEXT NOT NULL DEFAULT '',
    qr_content    TEXT NOT NULL DEFAULT '',
    user_id      TEXT,
    session_token_hash TEXT,
  redirect_to        TEXT NOT NULL DEFAULT '/',
 error        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    expires_at         TEXT NOT NULL,
    CHECK (status IN ('pending','scanned','confirmed','consumed','expired','failed'))
);
CREATE INDEX IF NOT EXISTS ix_oauth_states_expiry ON oauth_states(expires_at);

-- 每用户配额。缺行 = 用系统默认值，不代表无限制。
CREATE TABLE IF NOT EXISTS user_quotas (
    user_id        TEXT PRIMARY KEY,
    llm_monthly_tokens  INTEGER NOT NULL DEFAULT 0,
    llm_daily_calls     INTEGER NOT NULL DEFAULT 0,
    strategy_slots      INTEGER NOT NULL DEFAULT 0,
    publish_slots       INTEGER NOT NULL DEFAULT 0,
    job_slots      INTEGER NOT NULL DEFAULT 0,
    storage_mb          INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL
);

-- 用量计数。period 形如 '2026-08'（月）或 '2026-08-27'（日）。
-- 可整表清空重建（只影响配额判定的当期计数，不是账本）。
CREATE TABLE IF NOT EXISTS usage_counters (
 user_id    TEXT NOT NULL,
    period     TEXT NOT NULL,
    metric     TEXT NOT NULL,
    value      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, period, metric)
);

-- 审计。谁在什么时候对谁做了什么。只追加，不修改。
CREATE TABLE IF NOT EXISTS audit_log (
    id  TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_id  TEXT NOT NULL DEFAULT '',
    actor_name  TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    outcome     TEXT NOT NULL DEFAULT 'ok',
    detail_json TEXT NOT NULL DEFAULT '{}',
    ip       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_log(actor_id, occurred_at DESC);

-- 站内通知。read_at 为空即未读。
CREATE TABLE IF NOT EXISTS notifications (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'system',
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    link       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications(user_id, created_at DESC);

"""

#: 后续演进只准往这个列表尾部追加，且每条必须可重复执行。
#:
#: 存量库靠这里补列与补索引：CREATE TABLE IF NOT EXISTS 对已存在的表什么都不做。
_MIGRATIONS: list[str] = [
    "ALTER TABLE user_quotas ADD COLUMN job_slots INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE user_quotas ADD COLUMN storage_mb INTEGER NOT NULL DEFAULT 0",
    # 保留期清理按这些列截断。缺索引时 15 天截断就是全表扫，而清理跑在
    # 02:30 且持写锁，慢下来等于把凌晨的库锁住。
    "CREATE INDEX IF NOT EXISTS ix_sessions_absolute ON sessions(absolute_expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_ev_expiry ON email_verifications(expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_notifications_created ON notifications(created_at)",
    "CREATE INDEX IF NOT EXISTS ix_usage_period ON usage_counters(period)",
]


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            # 幂等迁移在已应用时会报 duplicate column 之类；这是预期路径。
            continue
    conn.commit()
    from src.identity.infrastructure.access_migration import migrate_access_model

    migrate_access_model(conn)
