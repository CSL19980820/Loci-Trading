"""身份会话连接池：空闲复用、事务回滚及失效连接恢复。"""

from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import PoolTimeout
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.app.tenant_middleware import TenantResolverMiddleware
from src.identity.api.schemas import SESSION_COOKIE, build_auth_dependency
from src.identity.infrastructure.store import IdentityStore
from src.shared.postgres import create_identity_auth_pool


@pytest.fixture(scope="module")
def synthetic_postgres():
    dsn = os.environ.get("LOCI_TEST_AUTH_POOL_DSN", "")
    if not dsn:
        pytest.skip("未配置隔离的 PostgreSQL 身份测试数据库")
    params = conninfo_to_dict(dsn)
    loopback = {"127.0.0.1", "localhost", "::1"}
    if (params.get("dbname") != "loci_auth_pool_test" or params.get("host") not in loopback
            or params.get("hostaddr", "127.0.0.1") not in loopback):
        raise ValueError("身份连接池测试只允许使用本机隔离的 loci_auth_pool_test 数据库")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA identity")
        try:
            conn.execute("""
                CREATE TABLE identity.users (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL UNIQUE, username TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '', email_verified_at TIMESTAMPTZ, password_hash TEXT,
                    password_algo TEXT NOT NULL DEFAULT '', password_updated_at TIMESTAMPTZ,
                    must_change_password BOOLEAN NOT NULL DEFAULT FALSE, display_name TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'visitor', status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, last_login_at TIMESTAMPTZ,
                    view_tenant_id TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE identity.sessions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, identity_id TEXT, created_at TIMESTAMPTZ NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
                    absolute_expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
                    ip TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT ''
                )
            """)
            yield dsn
        finally:
            conn.execute("DROP SCHEMA identity CASCADE")


@pytest.fixture
def identity_pool(synthetic_postgres, monkeypatch):
    monkeypatch.setenv("LOCI_DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("PALACE_POSTGRES_URL", raising=False)
    monkeypatch.setenv("LOCI_POSTGRES_URL", synthetic_postgres)
    pool = create_identity_auth_pool()
    pool.wait()
    try:
        yield pool
    finally:
        pool.close()


def _request(token=""):
    headers = [(b"cookie", f"{SESSION_COOKIE}={token}".encode())] if token else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _user_and_session():
    with IdentityStore() as store:
        user = store.create_user(
            username=f"pool-{uuid4().hex}", email="", password_hash=None,
            password_algo="", role="admin", status="active",
        )
        token = store.create_session(user_id=user.id)
    return user, token


def test_authenticated_session_refreshes_and_revocation_is_observed(identity_pool):
    user, token = _user_and_session()
    with IdentityStore() as store:
        session = store.get_session(token)
        store.conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE id = ?", ("2000-01-01T00:00:00Z", session.id),
        )
        store.conn.commit()
    authenticate = build_auth_dependency(connection_pool=lambda: identity_pool)
    context = authenticate(_request(token))
    assert context.authenticated and context.user.id == user.id

    with IdentityStore() as store:
        session = store.get_session(token)
        assert session is not None and session.id == context.session_id
        assert session.last_seen_at.year > 2000
        store.revoke_session(session.id)
    assert not authenticate(_request(token)).authenticated


def test_pool_rolls_back_uncommitted_changes_and_clears_session_state(identity_pool):
    user, _ = _user_and_session()
    with IdentityStore(pool=identity_pool) as store:
        store.conn.raw.execute("SET application_name TO 'loci-pool-test'")
        store.conn.raw.commit()
        store.conn.execute("UPDATE users SET display_name = ? WHERE id = ?", ("uncommitted", user.id))

    with IdentityStore() as store:
        assert store.get_user(user.id).display_name != "uncommitted"
    conn = identity_pool.getconn()
    try:
        assert conn.execute("SHOW application_name").fetchone()["application_name"] == ""
        assert "identity" not in conn.execute("SHOW search_path").fetchone()["search_path"]
    finally:
        conn.rollback()
        identity_pool.putconn(conn)


def test_transaction_context_commits_without_returning_connection(identity_pool):
    user, _ = _user_and_session()
    with IdentityStore(pool=identity_pool) as store:
        with store.conn:
            store.conn.execute("UPDATE users SET display_name = ? WHERE id = ?", ("saved", user.id))
        assert store.get_user(user.id).display_name == "saved"
    with IdentityStore() as store:
        assert store.get_user(user.id).display_name == "saved"


def test_pool_recovers_after_query_error(identity_pool):
    with pytest.raises(psycopg.Error):
        with IdentityStore(pool=identity_pool) as store:
            store.conn.execute("SELECT missing_column FROM users")
    with IdentityStore(pool=identity_pool) as store:
        assert store.conn.execute("SELECT 1 AS value").fetchone()["value"] == 1


def test_closed_pooled_wrapper_cannot_operate_on_a_reused_connection(identity_pool):
    first = IdentityStore(pool=identity_pool)
    closed = first.conn
    first.close()
    with IdentityStore(pool=identity_pool) as second:
        with pytest.raises(psycopg.OperationalError, match="closed"):
            closed.execute("SELECT 1")
        with pytest.raises(psycopg.OperationalError, match="closed"):
            _ = closed.raw
        assert second.conn.execute("SELECT 1 AS value").fetchone()["value"] == 1


def test_pool_discards_a_connection_lost_while_idle(identity_pool, synthetic_postgres):
    conn = identity_pool.getconn()
    pid = conn.info.backend_pid
    identity_pool.putconn(conn)
    with psycopg.connect(synthetic_postgres, autocommit=True) as control:
        assert control.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()[0]
    with IdentityStore(pool=identity_pool) as store:
        assert store.conn.execute("SELECT 1 AS value").fetchone()["value"] == 1


def test_concurrent_requests_do_not_leak_or_exhaust_identity_connections(identity_pool):
    user, token = _user_and_session()
    authenticate = build_auth_dependency(connection_pool=lambda: identity_pool)
    with ThreadPoolExecutor(max_workers=8) as workers:
        contexts = list(workers.map(lambda _: authenticate(_request(token)), range(24)))
    assert all(context.authenticated and context.user.id == user.id for context in contexts)
    assert identity_pool.get_stats().get("requests_errors", 0) == 0


def test_anonymous_requests_do_not_open_identity_store(monkeypatch):
    from src.identity.api import schemas

    def unexpected(*_args, **_kwargs):
        raise AssertionError("匿名请求不应连接身份库")

    monkeypatch.setattr(schemas, "IdentityStore", unexpected)
    authenticate = build_auth_dependency()
    assert not authenticate(_request()).authenticated


@pytest.mark.parametrize(
    ("path", "with_cookie"),
    [
        ("/api/example", True),
        ("/api/auth/session", True),
        ("/api/auth/me", True),
        ("/api/example", False),
    ],
)
def test_pool_timeout_does_not_misreport_session_as_expired(path, with_cookie):
    app = FastAPI()

    def busy(_request):
        raise PoolTimeout("fixture pool busy")

    app.add_middleware(TenantResolverMiddleware, resolver=busy)

    @app.get("/{path:path}")
    def example():
        return {"ok": True}

    with TestClient(app) as client:
        if with_cookie:
            client.cookies.set(SESSION_COOKIE, "synthetic-token")
        response = client.get(path)
    assert response.status_code == 503
    assert response.json()["code"] == "auth_unavailable"
    assert response.headers["Retry-After"] == "1"
