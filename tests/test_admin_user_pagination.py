"""Admin role pagination and bounded page enrichment, against an isolated identity DB."""
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.identity.api.admin_router import build_admin_router
from src.identity.application import platform
from src.identity.domain.models import AuthContext, iso, utc_now
from src.identity.infrastructure.store import IdentityStore
from src.identity.infrastructure.store_platform import DEFAULT_QUOTAS


@pytest.fixture
def store(tmp_path):
    with IdentityStore(tmp_path / "identity.db") as db:
        yield db


def create_user(store, index, *, role="visitor", status="active"):
    return store.create_user(
        username=f"account{index:03}", email="", display_name=f"Account {index}",
        role=role, status=status, password_hash=None, password_algo="",
    )


def test_role_filter_matches_total_across_three_pages_and_soft_deletes(store):
    operator = create_user(store, 999, role="admin")
    users = [create_user(store, index, role="admin" if index % 7 == 0 else "visitor")
             for index in range(85)]
    store.update_user(users[1].id, status="deleted")
    store.update_user(users[2].id, status="disabled")
    # A timestamp tie must have stable ordering across page boundaries.
    store.conn.execute("UPDATE users SET created_at = ?", (iso(utc_now() - timedelta(days=1)),))
    store.conn.commit()
    app = FastAPI()
    app.include_router(build_admin_router(
        auth_dependency=lambda: AuthContext(user=operator), identity_db=str(store.db_path),
    ))
    with TestClient(app) as client:
        pages = [client.get("/api/admin/users", params={
            "role": "visitor", "status": "active", "keyword": "account0",
            "limit": 30, "offset": offset,
        }) for offset in (0, 30, 60)]
        assert [response.status_code for response in pages] == [200, 200, 200]
        expected = sorted([u.id for u in users if u.role == "visitor" and u.id not in {users[1].id, users[2].id}], reverse=True)
        ids = [row["id"] for response in pages for row in response.json()["items"]]
        assert ids == expected
        assert len(ids) == len(set(ids))
        assert all(response.json()["total"] == len(expected) for response in pages)
        assert client.get("/api/admin/users", params={"role": "member"}).status_code == 422
        assert client.get("/api/admin/users").json()["total"] == 85


def test_batch_enrichment_preserves_values_and_constant_query_count(store):
    users = [create_user(store, index) for index in range(35)]
    month = utc_now().strftime("%Y-%m")
    store.set_quota(users[0].id, llm_monthly_tokens=1234)
    store.bump_usage(users[0].id, period=month, metric="llm_tokens", delta=12)
    store.bump_usage(users[0].id, period=month, metric="llm_calls", delta=2)
    store.bump_usage(users[0].id, period="1900-01", metric="llm_tokens", delta=900)
    statements = []
    store.conn.set_trace_callback(statements.append)
    for limit in (1, 35):
        statements.clear()
        rows = platform.list_users(store, limit=limit)
        assert len(rows) == limit
        assert len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]) == 3
    by_id = {row["id"]: row for row in rows}
    assert by_id[users[0].id]["quota"]["llm_monthly_tokens"] == 1234
    assert by_id[users[0].id]["usage"] == {"llm_tokens": 12, "llm_calls": 2}
    assert by_id[users[1].id]["quota"] == DEFAULT_QUOTAS
    assert by_id[users[1].id]["usage"] == {}
    statements.clear()
    assert platform.list_users(store, keyword="no-such-account") == []
    assert len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]) == 1
