"""identity 上下文：注册 / 登录 / 会话 / 扫码 / 配额 / 多租户隔离。

全部用临时库，不碰真实 data（依赖 tests/conftest.py 的隔离夹具）。
"""
from __future__ import annotations

from pathlib import Path
import pytest

from src.identity.application import accounts, platform, social_login
from src.identity.domain import password as pw
from src.identity.domain.models import (
    AuthenticationError,
    RateLimitedError,
    ValidationError,
    can_unbind,
    check_password_strength,
    normalize_email,
    normalize_username,
)
from src.identity.infrastructure.store import IdentityStore
from src.shared.tenancy import PRIMARY_TENANT, tenant_paths, tenant_scope


@pytest.fixture()
def store(tmp_path: Path):
    with IdentityStore(tmp_path / "identity.db") as opened:
        yield opened


def test_password_roundtrip_and_dummy_is_constant_false() -> None:
    encoded = pw.hash_password("Asdf!234")
    assert pw.verify_password("Asdf!234", encoding := encoded)
    assert not pw.verify_password("wrong", encoding)
    # 账号不存在时也要跑一次同参数哈希，否则秒表能枚举出注册过的邮箱。
    assert pw.verify_dummy("anything") is False
    assert pw.algo_of(encoded) in ("argon2id", "scrypt")


def test_password_policy_rejects_short_and_trivial() -> None:
    with pytest.raises(ValidationError):
        check_password_strength("short")
    with pytest.raises(ValidationError):
        check_password_strength("aaaaaaaaaa")
    check_password_strength("loci-quant-2026")


def test_email_and_username_normalisation() -> None:
    assert normalize_email("  A@B.CN ") == "a@b.cn"
    with pytest.raises(ValidationError):
        normalize_email("not-an-email")
    assert normalize_username("lociAdmin") == "lociAdmin"
    with pytest.raises(ValidationError):
        normalize_username("1bad")


def test_seed_default_admin_is_idempotent_and_binds_primary_tenant(store) -> None:
    admin = platform.seed_default_admin(store)
    assert admin is not None
    assert admin.username == "lociAdmin"
    assert admin.role == "admin"
    # 主租户 = 老的 data/ 目录本身，存量单机用户零迁移。
    assert admin.tenant_id == PRIMARY_TENANT
    assert admin.must_change_password is True
    # 再跑一次不该产生第二个管理员。
    assert platform.seed_default_admin(store) is None
    assert store.count_users() == 1


def test_default_admin_can_login_with_documented_credentials(store) -> None:
    platform.seed_default_admin(store)
    user, token = accounts.login_with_password(
    store, handle="lociAdmin", password="Asdf!234", ip="1.1.1.1"
)
    assert user.is_admin
    context = accounts.resolve_session(store, token)
    assert context.authenticated
    assert context.tenant_id == PRIMARY_TENANT


def test_explicit_deployment_credentials_create_their_own_admin(store) -> None:
    """部署声明的管理员即便在默认管理员之后也要建出来，否则升级即失联。"""
    platform.seed_default_admin(store)
    declared = platform.seed_default_admin(store, username="opsadmin", password="deploy-secret-1")
    assert declared is not None
    assert declared.role == "admin"
    # 主租户只能有一个；第二个管理员拿自己的租户。
    assert declared.tenant_id != PRIMARY_TENANT
    accounts.login_with_password(store, handle="opsadmin", password="deploy-secret-1")


def test_seed_never_resets_an_existing_password(store) -> None:
    platform.seed_default_admin(store, username="opsadmin", password="deploy-secret-1")
    user = store.get_user_by_login("opsadmin")
    assert user is not None
    store.set_password(user.id, password_hash=pw.hash_password("user-changed-it"), algo="x")
    # 再次启动：环境变量还是旧口令，但不能把用户改过的密码冲掉。
    platform.seed_default_admin(store, username="opsadmin", password="deploy-secret-1")
    accounts.login_with_password(store, handle="opsadmin", password="user-changed-it")
    with pytest.raises(AuthenticationError):
        accounts.login_with_password(store, handle="opsadmin", password="deploy-secret-1")


def test_register_does_not_leak_existing_email(store) -> None:
    first = accounts.register_with_email(
    store, email="trader@example.com", password="loci-quant-2026"
)
    second = accounts.register_with_email(
    store, email="trader@example.com", password="another-password-1"
)
    # 两次响应必须一模一样，否则注册接口就是一个邮箱枚举器。
    assert first["message"] == second["message"]
    assert store.count_users() == 1


def test_email_verification_is_single_use(store) -> None:
    accounts.register_with_email(store, email="trader@example.com", password="loci-quant-2026")
    user = store.get_user_by_login("trader@example.com")
    assert user is not None and user.status == "pending"
    token, code = store.create_verification(user_id=user.id, email="trader@example.com")
    verified = accounts.verify_email(store, token=token)
    assert verified.status == "active"
    assert verified.email_verified
    with pytest.raises(ValidationError):
        accounts.verify_email(store, token=token)
    # 验证码通道同样可用（走另一条分支）。
    _, code2 = store.create_verification(user_id=user.id, email="trader@example.com")
    assert accounts.verify_email(store, code=code2, email="trader@example.com")


def test_login_throttle_locks_the_account_then_rejects_right_password(store) -> None:
    platform.seed_default_admin(store)
    limiter = accounts.LoginThrottle()
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            accounts.login_with_password(
                store, handle="lociAdmin", password="wrong", ip="9.9.9.9", limiter=limiter
            )
    # 锁定期内即便口令正确也要拒绝，否则限流形同虚设。
    with pytest.raises(RateLimitedError):
        accounts.login_with_password(
            store, handle="lociAdmin", password="Asdf!234", ip="9.9.9.9", limiter=limiter
        )


def test_change_password_revokes_other_sessions(store) -> None:
    admin = platform.seed_default_admin(store)
    assert admin is not None
    _, keep = accounts.login_with_password(store, handle="lociAdmin", password="Asdf!234")
    _, other = accounts.login_with_password(store, handle="lociAdmin", password="Asdf!234")
    accounts.change_password(
    store,
    user=admin,
    old_password="Asdf!234",
    new_password="brand-new-secret-1",
    keep_token=keep,
)
    assert accounts.resolve_session(store, keep).authenticated
    # 改密的全部价值就在这一行：别处登录的会话立刻失效。
    assert not accounts.resolve_session(store, other).authenticated


def test_password_reset_kills_every_session_and_does_not_auto_login(store) -> None:
    accounts.register_with_email(store, email="trader@example.com", password="loci-quant-2026")
    user = store.get_user_by_login("trader@example.com")
    assert user is not None
    token, _ = store.create_verification(user_id=user.id, email="trader@example.com")
    accounts.verify_email(store, token=token)
    _, live = accounts.login_with_password(
    store, handle="trader@example.com", password="loci-quant-2026"
)
    reset_token, _ = store.create_verification(
    user_id=user.id, email="trader@example.com", purpose="reset"
)
    accounts.confirm_password_reset(store, token=reset_token, new_password="fresh-secret-2026")
    assert not accounts.resolve_session(store, live).authenticated
    accounts.login_with_password(store, handle="trader@example.com", password="fresh-secret-2026")


def test_disabled_account_cannot_login_or_keep_a_session(store) -> None:
    admin = platform.seed_default_admin(store)
    assert admin is not None
    accounts.register_with_email(store, email="trader@example.com", password="loci-quant-2026")
    user = store.get_user_by_login("trader@example.com")
    assert user is not None
    store.update_user(user.id, status="active")
    _, token = accounts.login_with_password(
    store, handle="trader@example.com", password="loci-quant-2026"
)
    platform.set_status(store, operator=admin, user_id=user.id, status="disabled")
    # 封号必须立刻断开在线会话，而不是等它自然过期。
    assert not accounts.resolve_session(store, token).authenticated
    with pytest.raises(AuthenticationError):
        accounts.login_with_password(
            store, handle="trader@example.com", password="loci-quant-2026"
        )


def test_admin_cannot_demote_or_disable_self(store) -> None:
    from src.identity.domain.models import AuthorizationError

    admin = platform.seed_default_admin(store)
    assert admin is not None
    with pytest.raises(AuthorizationError):
        platform.set_role(store, operator=admin, user_id=admin.id, role="member")
    with pytest.raises(AuthorizationError):
        platform.set_status(store, operator=admin, user_id=admin.id, status="disabled")


def test_qr_login_state_machine_and_replay_protection(store, monkeypatch) -> None:
    monkeypatch.setenv("LOCI_PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    started = social_login.start_login(store, provider_name="mock", redirect_to="/live")
    assert started["mode"] == "qrcode"
    assert started["qr_content"]
    state = started["state"]
    assert social_login.poll_state(store, state)["status"] == "pending"
    assert social_login.mark_scanned(store, state)
    assert social_login.poll_state(store, state)["status"] == "scanned"
    social_login.complete_callback(store, provider_name="mock", code="alice", state=state)
    assert social_login.poll_state(store, state)["status"] == "confirmed"
    claimed = social_login.claim_session(store, state=state, binding=started["binding"])
    assert claimed is not None
    user, token = claimed
    assert accounts.resolve_session(store, token).authenticated
    # confirmed -> consumed 的 CAS 只能成功一次，重放拿不到第二个会话。
    assert social_login.claim_session(store, state=state, binding=started["binding"]) is None


def test_qr_claim_requires_the_binding_cookie(store, monkeypatch) -> None:
    monkeypatch.setenv("LOCI_PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    started = social_login.start_login(store, provider_name="mock")
    social_login.complete_callback(
    store, provider_name="mock", code="bob", state=started["state"]
)
    # 别人捡到 state 也兑不出会话。
    with pytest.raises(ValidationError):
        social_login.claim_session(store, state=started["state"], binding="stolen")


def test_social_login_merges_by_subject_not_nickname(store, monkeypatch) -> None:
    monkeypatch.setenv("LOCI_PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    first = social_login.start_login(store, provider_name="mock")
    social_login.complete_callback(store, provider_name="mock", code="alice", state=first["state"])
    second = social_login.start_login(store, provider_name="mock")
    social_login.complete_callback(store, provider_name="mock", code="alice", state=second["state"])
    # 同一个 subject 两次登录只能是同一个账号。
    assert store.count_users() == 1
    third = social_login.start_login(store, provider_name="mock")
    social_login.complete_callback(store, provider_name="mock", code="carol", state=third["state"])
    assert store.count_users() == 2


def test_mock_provider_is_unavailable_in_production(store, monkeypatch) -> None:
    monkeypatch.setenv("PALACE_ENV", "production")
    monkeypatch.setenv("LOCI_AUTH_PROVIDERS", "email,mock")
    from src.identity.infrastructure.registry import enabled_providers, get_provider

    # 一个能凭空造账号的 provider 在生产必须彻底消失，且没有 override。
    assert get_provider("mock") is None
    assert all(item.name != "mock" for item in enabled_providers())


def test_unbind_last_login_method_is_blocked() -> None:
    from src.identity.domain.models import Identity

    only = Identity(id="idt_1", user_id="u_1", provider="mock", family="mock", subject="s")
    assert not can_unbind([only], "idt_1", has_password=False)
    assert can_unbind([only], "idt_1", has_password=True)


def test_api_key_lifecycle(store) -> None:
    admin = platform.seed_default_admin(store)
    assert admin is not None
    key_id, plaintext = store.create_api_key(user_id=admin.id, name="ci")
    assert plaintext.startswith("loci_")
    context = accounts.resolve_api_key(store, plaintext)
    assert context.authenticated and context.via == "api_key"
    assert store.revoke_api_key(key_id, admin.id)
    assert not accounts.resolve_api_key(store, plaintext).authenticated


def test_quota_defaults_and_admin_override(store) -> None:
    admin = platform.seed_default_admin(store)
    assert admin is not None
    # 管理员不限额。
    assert store.get_quota(admin.id)["llm_monthly_tokens"] == -1
    accounts.register_with_email(store, email="trader@example.com", password="loci-quant-2026")
    user = store.get_user_by_login("trader@example.com")
    assert user is not None
    assert store.get_quota(user.id)["llm_monthly_tokens"] > 0
    platform.set_quota(store, operator=admin, user_id=user.id, limits={"llm_daily_calls": 5})
    assert store.get_quota(user.id)["llm_daily_calls"] == 5
    assert store.bump_usage(user.id, period="2026-08", metric="llm_tokens", delta=10) == 10
    assert store.bump_usage(user.id, period="2026-08", metric="llm_tokens", delta=5) == 15


def test_tenant_scope_switches_private_databases(tmp_path: Path) -> None:
    root = tmp_path / "data"
    # 主租户 = data/ 本身；其他人落在 data/tenants/<uid>/。
    assert tenant_paths(root).palace_db == root / "palace.db"
    with tenant_scope("u_alice"):
        mine = tenant_paths(root)
        assert mine.palace_db == root / "tenants" / "u_alice" / "palace.db"
        assert mine.ops_db == root / "tenants" / "u_alice" / "ops.db"
    with tenant_scope("u_bob"):
        assert tenant_paths(root).palace_db == root / "tenants" / "u_bob" / "palace.db"
    # 出了作用域必须还原，否则后台任务会写到上一个用户的库里。
    assert tenant_paths(root).palace_db == root / "palace.db"


def test_market_database_stays_global_across_tenants(monkeypatch, tmp_path: Path) -> None:
    from src.shared import paths

    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    global_market = paths.market_db()
    with tenant_scope("u_alice"):
        # 行情是公共事实：按人复制既费磁盘又费带宽，也会让同步任务打架。
        assert paths.market_db() == global_market
        assert paths.identity_db() == paths.data_dir() / "identity.db"
        assert paths.palace_db() != paths.data_dir() / "palace.db"


def test_audit_log_records_login(store) -> None:
    platform.seed_default_admin(store)
    accounts.login_with_password(store, handle="lociAdmin", password="Asdf!234", ip="2.2.2.2")
    actions = [row["action"] for row in store.list_audit()]
    assert "account.login" in actions
    assert "platform.seed_admin" in actions
