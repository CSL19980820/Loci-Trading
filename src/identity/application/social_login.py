"""第三方登录用例：发起 → 回调/确认 → 兑换会话。

两种形态共用一台状态机（``oauth_states`` 表）：

- ``redirect``（微信 qrconnect / QQ authorize）：厂商 302 回我们的 callback，
  callback 里完成 exchange 并把 state 推到 ``confirmed``；前端整页跳走再跳回，
  理论上不需要轮询，但我们仍然让它走同一个 ``claim`` 出口，避免两套兑换逻辑。
- ``qrcode``（mock / 将来的公众号带参二维码）：前端拿到二维码后轮询
  ``poll_state``，用户在手机上确认后状态推进。

**防重放的全部机制是一条 CAS**：``confirmed → consumed`` 只能成功一次
（见 ``store.advance_oauth_state``）。同一个 state 兑不出第二个会话。

账号合并顺序（绝不用昵称）：

1. ``(provider, subject)`` 命中 → 就是他；
2. 否则 ``(family, union_key)`` 命中 → 同一个微信/QQ 用户从另一个入口进来；
3. 否则若当前已登录 → 绑到当前账号；
4. 否则新建账号。
"""
from __future__ import annotations

from typing import Any
import hashlib
import secrets

from src.identity.domain.models import (
    AuthContext,
    IdentityError,
    ValidationError,
    User,
    iso,
    utc_now,
)
from src.identity.domain.providers import ExternalIdentity, ProviderError
from src.identity.infrastructure.registry import get_provider, public_base_url
from src.identity.infrastructure.store import IdentityStore, token_digest


def _binding_secret() -> tuple[str, str]:
    """返回 ``(明文绑定串, sha256)``。明文进 HttpOnly Cookie，摘要进库。

        作用：挡住「A 发起扫码、B 拿到 state 去兑换」。没有这一层，
        state 泄漏就等于账号泄漏。
    """
    raw = secrets.token_urlsafe(24)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def callback_url(provider_name: str) -> str:
    base = public_base_url()
    return f"{base}/api/auth/callback/{provider_name}" if base else ""


def start_login(
    store: IdentityStore, *, provider_name: str, redirect_to: str = "/"
) -> dict[str, Any]:
    provider = get_provider(provider_name)
    if provider is None:
        raise ValidationError(f"登录方式不可用：{provider_name}")
    raw_binding, binding_hash = _binding_secret()
    state = store.create_oauth_state(
        provider=provider_name,
        binding_hash=binding_hash,
        redirect_to=redirect_to or "/",
    )
    challenge = provider.start(state=state, redirect_uri=callback_url(provider_name))
    if challenge.qr_content:
        store.conn.execute(
            "UPDATE oauth_states SET qr_content = ? WHERE state = ?",
            (challenge.qr_content, state),
        )
        store.conn.commit()
    payload = challenge.to_dict()
    payload["binding"] = raw_binding
    return payload


def poll_state(store: IdentityStore, state: str) -> dict[str, Any]:
    """前端轮询。只回状态，不回任何身份信息。"""
    record = store.get_oauth_state(state)
    if record is None:
        return {"status": "expired"}
    from src.identity.domain.models import is_expired

    if is_expired(record["expires_at"]) and record["status"] in ("pending", "scanned"):
        return {"status": "expired"}
    return {
        "status": record["status"],
        "redirect_to": record["redirect_to"],
        "error": record["error"] or "",
}


def mark_scanned(store: IdentityStore, state: str) -> bool:
    """扫码形态：用户扫开了但还没点确认。纯 UI 反馈，不产生任何权限。"""
    return store.advance_oauth_state(state, to="scanned", expect=("pending",))


def _merge_identity(
    store: IdentityStore,
    external: ExternalIdentity,
    *,
    current: AuthContext | None = None,
) -> User:
    existing = store.find_identity(external.provider, external.subject)
    if existing is not None:
        user = store.get_user(existing.user_id)
        if user is None:
            raise IdentityError("绑定的账号已不存在")
        return user
    if external.union_key:
        sibling = store.find_identity_by_union(external.family, external.union_key)
        if sibling is not None:
            user = store.get_user(sibling.user_id)
            if user is not None:
                store.upsert_identity(
                    user_id=user.id,
                    provider=external.provider,
                    family=external.family,
                    subject=external.subject,
                    union_key=external.union_key,
                    display_name=external.display_name,
                    avatar_url=external.avatar_url,
                    raw_profile=dict(external.raw),
                )
                return user
    if current is not None and current.user is not None:
        store.upsert_identity(
            user_id=current.user.id,
            provider=external.provider,
            family=external.family,
            subject=external.subject,
            union_key=external.union_key,
            display_name=external.display_name,
            avatar_url=external.avatar_url,
            raw_profile=dict(external.raw),
        )
        return current.user
    return _create_from_external(store, external)


def _create_from_external(store: IdentityStore, external: ExternalIdentity) -> User:
    """社交注册：没有邮箱也能建号，但登录名必须唯一。"""
    base = "".join(
        ch for ch in (external.display_name or external.family) if ch.isalnum()
    )[:16]
    if len(base) < 3 or not base[:1].isalpha():
        base = f"{external.family}user"
    for _ in range(6):
        candidate = f"{base}{secrets.token_hex(3)}"
        try:
            user = store.create_user(
                username=candidate,
                email="",
                password_hash=None,
                password_algo="",
                display_name=external.display_name or candidate,
                role="member",
                # 社交登录没有邮箱可验，直接 active；敏感能力另有 email 门槛。
                status="active",
            )
        except Exception:
            continue
        if external.avatar_url:
            store.update_user(user.id, avatar_url=external.avatar_url)
        store.upsert_identity(
            user_id=user.id,
            provider=external.provider,
            family=external.family,
            subject=external.subject,
            union_key=external.union_key,
            display_name=external.display_name,
            avatar_url=external.avatar_url,
            raw_profile=dict(external.raw),
        )
        store.write_audit(
            action="account.social_register",
            actor_id=user.id,
            actor_name=user.username,
            detail={"provider": external.provider},
        )
        return user
    raise IdentityError("生成登录名失败，请重试")


def complete_callback(
    store: IdentityStore,
    *,
    provider_name: str,
    code: str,
    state: str,
    current: AuthContext | None = None,
    ip: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    """厂商回调 / mock 确认。成功后把 state 推到 ``confirmed`` 并预置会话。"""
    record = store.get_oauth_state(state)
    if record is None:
        raise ValidationError("登录会话已过期，请重新扫码")
    if record["provider"] != provider_name:
        raise ValidationError("登录会话与提供方不匹配")
    if record["status"] in ("consumed", "failed"):
        raise ValidationError("该登录请求已完成或已失效")
    provider = get_provider(provider_name)
    if provider is None:
        raise ValidationError(f"登录方式不可用：{provider_name}")
    try:
        external = provider.exchange(
            code=code, state=state, redirect_uri=callback_url(provider_name)
        )
    except ProviderError as exc:
        store.fail_oauth_state(state, exc.provider_message or str(exc))
        raise
    user = _merge_identity(store, external, current=current)
    if user.status == "disabled":
        store.fail_oauth_state(state, "账号已被停用")
        raise IdentityError("账号已被停用，请联系管理员")
    token = store.create_session(user_id=user.id, ip=ip, user_agent=user_agent)
    store.advance_oauth_state(
        state,
        to="confirmed",
        expect=("pending", "scanned"),
        user_id=user.id,
        session_token_hash=token_digest(token),
    )
    store.update_user(user.id, last_login_at=iso(utc_now()))
    store.write_audit(
        action="account.social_login",
        actor_id=user.id,
        actor_name=user.username,
        detail={"provider": provider_name},
        ip=ip,
    )
    return {"user": user, "session_token": token, "redirect_to": record["redirect_to"]}


def claim_session(
    store: IdentityStore, *, state: str, binding: str = ""
) -> tuple[User, str] | None:
    """前端轮到 ``confirmed`` 后来兑换会话。**这一步只能成功一次**。

        注意：我们不能从库里取回明文 token（只存了摘要），所以兑换时
     重新签发一个会话，并把原来那个预置会话作废。这样即便 confirmed
      阶段的响应在网络上被看到，也换不出可用凭证。
        """
    record = store.get_oauth_state(state)
    if record is None or record["status"] != "confirmed":
        return None
    if record["binding_hash"]:
        provided = hashlib.sha256((binding or "").encode("utf-8")).hexdigest()
        if provided != record["binding_hash"]:
            raise ValidationError("登录会话校验失败，请重新扫码")
    if not store.advance_oauth_state(state, to="consumed", expect=("confirmed",)):
        return None
    user = store.get_user(str(record["user_id"] or ""))
    if user is None:
        return None
    preset = str(record["session_token_hash"] or "")
    if preset:
        store.revoke_session(preset)
    token = store.create_session(user_id=user.id)
    return user, token
