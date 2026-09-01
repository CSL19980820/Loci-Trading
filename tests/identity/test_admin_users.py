"""管理员开号（无注册制）+ 后台过滤计数与登录记录查询。

为什么单独一个文件：``test_identity.py`` 已经 300+ 行且讲的是「自助注册那条
路」；本系统的正常账号来源是管理员开号，两套语义放一起读不清。
夹具风格沿用 ``test_identity.py``（tmp_path 临时库 + tests/conftest.py 的环境隔离）。
"""
from __future__ import annotations

from pathlib import Path
import pytest

from src.identity.application import accounts, platform
from src.identity.domain.models import ConflictError, ValidationError
from src.identity.infrastructure.registry import signup_enabled
from src.identity.infrastructure.store import IdentityStore
from src.shared.tenancy import PRIMARY_TENANT


@pytest.fixture()
def store(tmp_path: Path):
    with IdentityStore(tmp_path / "identity.db") as opened:
        yield opened


@pytest.fixture()
def admin(store):
    seeded = platform.seed_default_admin(store)
    assert seeded is not None
    return seeded


def test_admin_created_user_can_login_and_must_change_password(store, admin) -> None:
    created = platform.create_user(
        store,
        operator=admin,
        username="trader01",
        password="loci-quant-2026",
        display_name="研究员甲",
        email="trader01@example.com",
    )
    assert created.status == "active"
    assert created.role == "member"
    # 管理员知道这个明文，所以它只是「一次性入场券」。
    assert created.must_change_password is True
    # 管理员录入的邮箱视为已验证，不该再把人卡在收信验证上。
    assert created.email_verified
    user, token = accounts.login_with_password(
        store, handle="trader01", password="loci-quant-2026"
    )
    assert user.id == created.id
    assert accounts.resolve_session(store, token).authenticated
    # 邮箱也能登（upsert_identity 建了 email/local 身份，登录名/邮箱双索引）。
    accounts.login_with_password(store, handle="trader01@example.com", password="loci-quant-2026")


def test_admin_created_user_gets_its_own_tenant(store, admin) -> None:
    created = platform.create_user(
        store, operator=admin, username="trader02", password="loci-quant-2026"
    )
    # 租户隔离是整个多租户改造要守住的不变式：绝不能复用主租户，那是
    # 首启管理员的存量 data/ 目录。
    assert created.tenant_id != admin.tenant_id
    assert created.tenant_id != PRIMARY_TENANT
    assert created.tenant_id == created.id


def test_duplicate_login_name_conflicts(store, admin) -> None:
    platform.create_user(store, operator=admin, username="trader03", password="loci-quant-2026")
    with pytest.raises(ConflictError) as raised:
        platform.create_user(
            store, operator=admin, username="trader03", password="another-secret-1"
        )
    assert raised.value.http_status == 409
    # 邮箱撞车同样是 409，而不是把已有账号的邮箱悄悄改掉。
    platform.create_user(
        store,
        operator=admin,
        username="trader04",
        password="loci-quant-2026",
        email="dup@example.com",
    )
    with pytest.raises(ConflictError):
        platform.create_user(
            store,
            operator=admin,
            username="trader05",
            password="loci-quant-2026",
            email="DUP@example.com",
        )


def test_weak_password_and_bad_role_are_rejected(store, admin) -> None:
    with pytest.raises(ValidationError):
        platform.create_user(store, operator=admin, username="trader06", password="short")
    with pytest.raises(ValidationError):
        platform.create_user(store, operator=admin, username="trader06", password="aaaaaaaaaa")
    with pytest.raises(ValidationError):
        platform.create_user(
            store, operator=admin, username="trader06", password="loci-quant-2026", role="root"
        )
    with pytest.raises(ValidationError):
        platform.create_user(
            store, operator=admin, username="trader06", password="loci-quant-2026", status="deleted"
        )
    # 一次都没建出来：校验失败必须发生在写库之前。
    assert store.get_user_by_login("trader06") is None


def test_admin_role_gets_unlimited_quota(store, admin) -> None:
    created = platform.create_user(
        store, operator=admin, username="opsmate", password="loci-quant-2026", role="admin"
    )
    assert store.get_quota(created.id)["llm_monthly_tokens"] == -1
    member = platform.create_user(
        store, operator=admin, username="member01", password="loci-quant-2026"
    )
    assert store.get_quota(member.id)["llm_monthly_tokens"] > 0


def test_count_users_matches_list_users_under_the_same_filter(store, admin) -> None:
    for name in ("alpha01", "alpha02", "beta01"):
        platform.create_user(store, operator=admin, username=name, password="loci-quant-2026")
    for keyword in ("", "alpha", "beta", "lociAdmin", "nope"):
        listed = store.list_users(keyword=keyword, limit=500)
        assert len(listed) == store.count_users(keyword=keyword), keyword
    assert store.count_users(keyword="alpha") == 2
    assert store.count_users() == 4
    # 无参调用的老语义不能变：首启种子与 overview 都靠它。
    assert store.count_users() == len(store.list_users(limit=500))
    platform.set_status(store, operator=admin, user_id=store.list_users()[0].id, status="disabled")
    assert store.count_users(status="disabled") == len(store.list_users(status="disabled")) == 1


def test_user_keyword_wildcards_are_escaped(store, admin) -> None:
    platform.create_user(store, operator=admin, username="gamma01", password="loci-quant-2026")
    # 管理员在搜索框敲一个 % 不该等于「把全表捞出来」。
    assert store.count_users(keyword="%") == 0
    assert store.list_users(keyword="%") == []
    assert store.count_users(keyword="_amma01") == 0


def test_login_actions_whitelist_isolates_login_events(store, admin) -> None:
    platform.create_user(store, operator=admin, username="trader07", password="loci-quant-2026")
    accounts.login_with_password(store, handle="trader07", password="loci-quant-2026", ip="7.7.7.7")
    accounts.login_with_password(store, handle="lociAdmin", password="Asdf!234", ip="8.8.8.8")
    rows = store.list_audit(actions=platform.LOGIN_ACTIONS, limit=500)
    assert rows, "登录事件一条都没落，审计链路断了"
    assert {row["action"] for row in rows} <= set(platform.LOGIN_ACTIONS)
    assert store.count_audit(actions=platform.LOGIN_ACTIONS) == len(rows)
    # 白名单之外的事件（开号、种子）确实存在，只是不该出现在登录记录里。
    everything = store.list_audit(limit=500)
    assert len(everything) > len(rows)
    assert "admin.create_user" in {row["action"] for row in everything}
    # 倒序：occurred_at 单调不增（同一秒内的先后由 rowid 决定，不做假设）。
    stamps = [row["occurred_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True)
    assert {row["actor_name"] for row in rows} == {"lociAdmin", "trader07"}


def test_audit_filters_by_prefix_keyword_and_outcome(store, admin) -> None:
    platform.create_user(store, operator=admin, username="trader08", password="loci-quant-2026")
    with pytest.raises(Exception):
        accounts.login_with_password(store, handle="trader08", password="wrong-password")
    prefixed = store.list_audit(action="admin.")
    assert prefixed and all(row["action"].startswith("admin.") for row in prefixed)
    assert store.count_audit(action="admin.") == len(prefixed)
    failed = store.list_audit(outcome="failed")
    assert failed and all(row["outcome"] == "failed" for row in failed)
    assert store.count_audit(outcome="failed") == len(failed)
    by_actor = store.list_audit(keyword="trader08")
    assert by_actor and store.count_audit(keyword="trader08") == len(by_actor)
    # 通配符要被转义，否则一个 % 就把整本审计端出去。
    assert store.count_audit(keyword="%") == 0
    assert store.count_audit(action="%") == 0
    # 空白名单是「明确一条都不要」，不是「不过滤」。
    assert store.list_audit(actions=[]) == []
    assert store.count_audit(actions=[]) == 0


def test_signup_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_ALLOW_SIGNUP", raising=False)
    # 本系统不支持注册制：缺省必须是关。
    assert signup_enabled() is False
    for raw in ("0", "", "off", "no", "false", "maybe"):
        monkeypatch.setenv("LOCI_ALLOW_SIGNUP", raw)
        assert signup_enabled() is False, raw
    for raw in ("1", "true", "TRUE", "Yes", " on "):
        monkeypatch.setenv("LOCI_ALLOW_SIGNUP", raw)
        assert signup_enabled() is True, raw


def test_login_options_reports_signup_switch(monkeypatch) -> None:
    from src.identity.infrastructure.registry import login_options

    monkeypatch.delenv("LOCI_ALLOW_SIGNUP", raising=False)
    monkeypatch.setenv("LOCI_AUTH_PROVIDERS", "email,mock")
    # email 在 provider 名单里也不代表能自助注册——登录与注册是两件事。
    assert login_options()["email_signup"] is False
    monkeypatch.setenv("LOCI_ALLOW_SIGNUP", "1")
    assert login_options()["email_signup"] is True
