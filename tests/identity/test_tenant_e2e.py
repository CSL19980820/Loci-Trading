"""端到端：两个用户在同一台服务上互不串味。

这是整个 v2 多租户改造**唯一真正要守住的不变式**——其余都是它的推论。
用真实 ASGI 应用跑，不 mock 任何一层：走 HTTP → 中间件解析身份 → ContextVar
绑租户 → `paths.palace_db()` 解析 → `PalaceStore` 落到不同文件。
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from src.app.main import create_app
from src.identity.infrastructure.store import IdentityStore


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """生产形态：强制登录、无桌面自动登录。静态目录故意不存在。

    自助注册默认关闭（本系统不走注册制），但这一组用例要测的是「两个用户各
    自的账本互不串味」，最省事的造号通道就是注册。显式打开开关，把「注册开着
    的形态」写进夹具而不是靠默认值——默认值改了这里也不会静默换语义。
    """
    monkeypatch.setenv("LOCI_ALLOW_SIGNUP", "1")
    return create_app(
        static_dir=tmp_path / "no-static",
        environment="production",
        allowed_hosts=["testserver"],
        write_token="tenant-isolation-agent-token-0123456789ab",
        auth_username="rootadmin",
        auth_password="root-password-1",
        session_secret="tenant-isolation-secret",
        insecure_http=True,
    )


def _register_and_login(client: TestClient, email: str, password: str) -> None:
    """注册 → 直接消费验证票据 → 登录。绕过邮件通道，只测隔离。"""
    assert client.post(
        "/api/auth/register", json={"email": email, "password": password}
    ).status_code == 200
    with IdentityStore() as store:
        user = store.get_user_by_login(email)
        assert user is not None
        token, _code = store.create_verification(user_id=user.id, email=email)
    verified = client.post("/api/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text


def _candidate(code: str, name: str) -> dict[str, object]:
    return {
        "code": code,
        "name": name,
        "decision": "观察",
        "reason": "多租户隔离验证",
        "occurred_on": "2026-08-27",
    }


def test_two_users_do_not_see_each_others_ledger(app) -> None:
    with TestClient(app) as alice:
        _register_and_login(alice, "alice@example.com", "alice-secret-2026")
        me = alice.get("/api/auth/me").json()
        alice_tenant = me["user"]["tenant_id"]
        assert alice.post("/api/candidates", json=_candidate("300358", "楚天科技")).status_code == 201
        mine = alice.get("/api/candidates").json()
    with TestClient(app) as bob:
        _register_and_login(bob, "bob@example.com", "bob-secret-2026")
        bob_tenant = bob.get("/api/auth/me").json()["user"]["tenant_id"]
        # Bob 的账本必须是空的：Alice 刚写进去的那条不属于他。
        assert bob.get("/api/candidates").json() == []
        assert bob.post("/api/candidates", json=_candidate("601138", "工业富联")).status_code == 201
        bob_list = bob.get("/api/candidates").json()
    # 租户 id 必须不同，且都不是主租户（主租户归首启管理员）。
    assert alice_tenant != bob_tenant
    assert alice_tenant != "__primary__" and bob_tenant != "__primary__"
    assert [row["code"] for row in mine] == ["300358"]
    assert [row["code"] for row in bob_list] == ["601138"]


def test_tenant_databases_are_separate_files_on_disk(app, tmp_path: Path) -> None:
    from src.shared.paths import data_dir

    with TestClient(app) as alice:
        _register_and_login(alice, "alice@example.com", "alice-secret-2026")
        tenant = alice.get("/api/auth/me").json()["user"]["tenant_id"]
        alice.post("/api/candidates", json=_candidate("300358", "楚天科技"))
    private = data_dir() / "tenants" / tenant / "palace.db"
    assert private.is_file(), f"租户私有账本没落盘：{private}"
    # 行情库不分租户——按人复制一份 GB 级行情既费磁盘又会让同步任务互相撞锁。
    assert not (data_dir() / "tenants" / tenant / "market.db").exists()


def test_anonymous_is_rejected_and_admin_area_needs_admin(app) -> None:
    with TestClient(app) as client:
        assert client.get("/api/candidates").status_code == 401
        assert client.get("/api/admin/users").status_code == 401
        _register_and_login(client, "member@example.com", "member-secret-2026")
        # 普通成员登录后能用工作台，但进不了管理后台。
        assert client.get("/api/candidates").status_code == 200
        assert client.get("/api/admin/users").status_code == 403


def test_seeded_admin_owns_the_primary_tenant(app) -> None:
    """存量单机用户升级后看到的还是老的 data/ 目录，这条守住「零迁移」。"""
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/login", json={"username": "rootadmin", "password": "root-password-1"}
        ).status_code == 200
        profile = client.get("/api/auth/me").json()["user"]
        assert profile["role"] == "admin"
        assert profile["tenant_id"] == "__primary__"
        assert client.get("/api/admin/users").status_code == 200


def test_agent_bearer_token_still_works_and_maps_to_primary(app) -> None:
    """老的 CI / 脚本 / MCP 客户端不能因为上了用户体系就集体失联。"""
    headers = {"Authorization": "Bearer tenant-isolation-agent-token-0123456789ab"}
    with TestClient(app) as client:
        assert client.get("/api/candidates", headers=headers).status_code == 200
        wrote = client.post(
            "/api/candidates", json=_candidate("000001", "平安银行"), headers=headers
        )
        assert wrote.status_code == 201


def test_logout_and_disabled_account_lose_access_immediately(app) -> None:
    with TestClient(app) as client:
        _register_and_login(client, "victim@example.com", "victim-secret-2026")
        user_id = client.get("/api/auth/me").json()["user"]["id"]
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/candidates").status_code == 401
        # 重新登录后被管理员封号，在线会话必须立刻断，而不是等自然过期。
        assert client.post(
            "/api/auth/login",
            json={"username": "victim@example.com", "password": "victim-secret-2026"},
        ).status_code == 200
        assert client.get("/api/candidates").status_code == 200
        with IdentityStore() as store:
            store.update_user(user_id, status="disabled")
            store.revoke_user_sessions(user_id)
        assert client.get("/api/candidates").status_code == 401


def test_login_page_is_reachable_without_a_session(app) -> None:
    """注册页不能把自己挡在门外：/api/auth/** 整个前缀必须公开。"""
    with TestClient(app) as client:
        assert client.get("/api/auth/options").status_code == 200
        assert client.get("/api/auth/session").json()["authenticated"] is False
        assert client.post("/api/auth/forgot-password", json={"email": "x@y.cn"}).status_code == 200
        # 但 /api/auth/me 是私有的，不能被那条前缀顺手放行。
        assert client.get("/api/auth/me").status_code == 401


def test_self_service_signup_is_closed_by_default(app, monkeypatch) -> None:
    """本系统不支持注册制：关掉开关后注册端点必须 403，且不留任何痕迹。"""
    monkeypatch.delenv("LOCI_ALLOW_SIGNUP", raising=False)
    with TestClient(app) as client:
        refused = client.post(
            "/api/auth/register",
            json={"email": "walkin@example.com", "password": "walk-in-secret-2026"},
        )
        assert refused.status_code == 403
        # 登录页也要照实说：别画一个点了就 403 的注册按钮。
        assert client.get("/api/auth/options").json()["email_signup"] is False
    with IdentityStore() as store:
        # 不落账号、不落审计——否则「关掉的注册」还是个邮箱探测器。
        assert store.get_user_by_login("walkin@example.com") is None
        assert store.count_audit(keyword="walkin@example.com") == 0


def test_admin_creates_an_account_that_can_log_in(app) -> None:
    """管理员开号 → 新人用初始口令登录 → 被要求改密。"""
    with TestClient(app) as admin:
        assert admin.post(
            "/api/auth/login", json={"username": "rootadmin", "password": "root-password-1"}
        ).status_code == 200
        created = admin.post(
            "/api/admin/users",
            json={
                "username": "analyst01",
                "password": "analyst-secret-2026",
                "display_name": "分析师甲",
                "email": "analyst01@example.com",
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()
        # 与 GET /admin/users 的单项同形：前端能直接把它塞进列表。
        listed = admin.get("/api/admin/users", params={"keyword": "analyst01"}).json()
        assert listed["total"] == 1
        assert set(row) == set(listed["items"][0])
        assert row["must_change_password"] is True
        assert row["tenant_id"] not in ("", "__primary__")
        # 重名再来一次 → 409，不是 500 也不是静默改号。
        assert admin.post(
            "/api/admin/users",
            json={"username": "analyst01", "password": "another-secret-2026"},
        ).status_code == 409
        # 弱口令 → 422（domain 的强度校验，不是 pydantic 的长度）。
        assert admin.post(
            "/api/admin/users",
            json={"username": "analyst02", "password": "aaaaaaaaaa"},
        ).status_code == 422
    with TestClient(app) as member:
        logged = member.post(
            "/api/auth/login",
            json={"username": "analyst01", "password": "analyst-secret-2026"},
        )
        assert logged.status_code == 200, logged.text
        profile = logged.json()["user"]
        assert profile["must_change_password"] is True
        assert profile["email_verified"] is True
        # 开出来的是普通成员：能用工作台，进不了后台。
        assert member.get("/api/candidates").status_code == 200
        assert member.get("/api/admin/users").status_code == 403


def test_admin_login_records_only_show_logins(app) -> None:
    with TestClient(app) as admin:
        admin.post("/api/auth/login", json={"username": "rootadmin", "password": "root-password-1"})
        admin.post(
            "/api/admin/users",
            json={"username": "analyst03", "password": "analyst-secret-2026"},
        )
        logins = admin.get("/api/admin/logins", params={"limit": 100}).json()
        assert logins["total"] == len(logins["items"])
        assert {row["action"] for row in logins["items"]} == {"account.login"}
        # 审计全量里有开号事件，登录记录里没有。
        audit = admin.get("/api/admin/audit", params={"action": "admin.", "limit": 100}).json()
        assert audit["total"] >= 1
        assert all(row["action"].startswith("admin.") for row in audit["items"])
