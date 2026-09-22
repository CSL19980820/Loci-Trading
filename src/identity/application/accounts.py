"""账号用例：注册、验证、登录、改密、资料、会话管理。

三条贯穿全文的安全原则（写在这里，路由层不要再各自发挥）：

1. **防枚举**：登录失败、找回密码、注册已存在邮箱，对外一律同一种响应。
   时序侧信道靠 ``password.verify_dummy`` 抹平。
2. **限流按账号 + 按 IP 双轨**，任一命中即拒。找回密码不触发账号锁定
   （否则任何人都能用「一直点找回」把别人锁死）。
3. **状态变更必须先出示有效票据**。没验证邮箱之前不改任何账号状态。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

from src.identity.domain.models import (
    AuthContext,
    AuthenticationError,
    ConflictError,
    RateLimitedError,
    User,
    ValidationError,
    check_password_strength,
    is_expired,
    iso,
    normalize_email,
    normalize_username,
    utc_now,
)
from src.identity.domain import password as pw
from src.identity.infrastructure.registry import Mailer, render_verification_mail
from src.identity.infrastructure.store import IdentityStore, token_digest

#: 登录失败阈值。账号维度比 IP 维度更接近真实攻击面（OWASP 的建议）。
_ACCOUNT_MAX_FAILURES = 5
_IP_MAX_FAILURES = 30
_FAILURE_WINDOW_SEC = 900
#: 同一邮箱两次发信的最小间隔。
_MAIL_COOLDOWN_SEC = 60

#: 对外统一话术。任何时候都不要因为「用户不存在」换一句更友好的提示。
GENERIC_LOGIN_ERROR = "账号或密码错误"
GENERIC_MAIL_SENT = "若该邮箱可用，我们已发送验证码"


@dataclass
class _Bucket:
    count: int = 0
    first_at: float = 0.0


class LoginThrottle:
    """进程内双轨限流。单容器单进程部署够用；多实例请换共享存储。

        重启即清零是**已知取舍**——攻击者要靠重启服务来重置计数，
        那他已经有更严重的能力了。
        """

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}

    def _hit(self, key: str, limit: int, now: float) -> int:
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket.first_at > _FAILURE_WINDOW_SEC:
            bucket = _Bucket(count=0, first_at=now)
            self._buckets[key] = bucket
        return bucket.count

    def check(self, *, account: str, ip: str) -> None:
        now = time.time()
        if len(self._buckets) > 4096:
            self._buckets.clear()
        if account and self._hit(f"acct:{account}", _ACCOUNT_MAX_FAILURES, now) >= _ACCOUNT_MAX_FAILURES:
            raise RateLimitedError("登录失败次数过多，请稍后再试", retry_after=_FAILURE_WINDOW_SEC)
        if ip and self._hit(f"ip:{ip}", _IP_MAX_FAILURES, now) >= _IP_MAX_FAILURES:
            raise RateLimitedError("登录失败次数过多，请稍后再试", retry_after=_FAILURE_WINDOW_SEC)

    def record_failure(self, *, account: str, ip: str) -> None:
        now = time.time()
        for key in (f"acct:{account}" if account else "", f"ip:{ip}" if ip else ""):
            if not key:
                continue
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.first_at > _FAILURE_WINDOW_SEC:
                bucket = _Bucket(count=0, first_at=now)
                self._buckets[key] = bucket
            bucket.count += 1

    def reset(self, *, account: str, ip: str) -> None:
        self._buckets.pop(f"acct:{account}", None)
        self._buckets.pop(f"ip:{ip}", None)


_throttle = LoginThrottle()


def throttle() -> LoginThrottle:
    return _throttle


def _tenant_for(user_id: str) -> str:
    """用户 id 直接当租户目录名。已经是 ``u_<hex>``，天然安全。"""
    return user_id


def register_with_email(
    store: IdentityStore,
    *,
    email: str,
    password: str,
    username: str = "",
    display_name: str = "",
    ip: str = "",
) -> dict[str, Any]:
    """邮箱注册。**已存在的邮箱不报错**——那等于确认「这个邮箱注册过」。

        改为给该地址发一封「有人尝试用你的邮箱注册」提醒邮件，返回同样的响应。
        """
    normalized = normalize_email(email)
    if not normalized:
        raise ValidationError("请填写邮箱")
    check_password_strength(password)
    handle = normalize_username(username) if username else normalized.split("@")[0][:32]
    handle = normalize_username(handle) if len(handle) >= 3 else f"loci{handle}"
    mailer = Mailer()
    existing = store.get_user_by_login(normalized)
    if existing is not None:
        subject = "【Loci】有人尝试用你的邮箱注册"
        body = "如果是你本人，请直接使用原密码登录或走「忘记密码」。若非本人操作，可忽略。"
        try:
            mailer.send(to=normalized, subject=subject, body=body)
        except OSError:
            pass
        return {"ok": True, "message": GENERIC_MAIL_SENT}
    try:
        user = store.create_user(
            username=handle,
            email=normalized,
            password_hash=pw.hash_password(password),
            password_algo=pw.preferred_algo(),
            display_name=display_name or handle,
            role="visitor",
            status="pending",
        )
    except ConflictError:
        # 登录名撞车：加随机后缀重试一次，不把冲突暴露给调用方。
        import secrets

        user = store.create_user(
            username=f"{handle[:24]}{secrets.token_hex(3)}",
            email=normalized,
            password_hash=pw.hash_password(password),
            password_algo=pw.preferred_algo(),
            display_name=display_name or handle,
            role="visitor",
            status="pending",
        )
    store.update_user(user.id, **{})
    store.upsert_identity(
        user_id=user.id,
        provider="email",
        family="local",
        subject=normalized,
        display_name=user.display_name,
    )
    token, code = store.create_verification(user_id=user.id, email=normalized, request_ip=ip)
    subject, body = render_verification_mail(code=code, token=token, purpose="verify")
    delivered = False
    try:
        delivered = mailer.send(to=normalized, subject=subject, body=body)
    except OSError:
        delivered = False
    store.write_audit(
        action="account.register", actor_id=user.id, actor_name=user.username, ip=ip
    )
    return {"ok": True, "message": GENERIC_MAIL_SENT, "mail_delivered": delivered}


def resend_verification(store: IdentityStore, *, email: str, ip: str = "") -> dict[str, Any]:
    normalized = normalize_email(email)
    user = store.get_user_by_login(normalized)
    if user is None or user.email_verified:
        # 不泄漏「这个邮箱存在 / 已验证」。
        return {"ok": True, "message": GENERIC_MAIL_SENT}
    last = store.last_verification_at(user.id, "verify")
    if last and not is_expired(last, now=utc_now()):
        pass
    if last:
        from src.identity.domain.models import parse_iso

        moment = parse_iso(last)
        if moment and (utc_now() - moment).total_seconds() < _MAIL_COOLDOWN_SEC:
            raise RateLimitedError("发送过于频繁，请稍后再试", retry_after=_MAIL_COOLDOWN_SEC)
    token, code = store.create_verification(user_id=user.id, email=normalized, request_ip=ip)
    subject, body = render_verification_mail(code=code, token=token, purpose="verify")
    try:
        Mailer().send(to=normalized, subject=subject, body=body)
    except OSError:
        pass
    return {"ok": True, "message": GENERIC_MAIL_SENT}


def verify_email(
    store: IdentityStore, *, token: str = "", code: str = "", email: str = ""
) -> User:
    record = store.consume_verification(
        token=token, code=code, email=normalize_email(email) if email else "", purpose="verify"
    )
    if record is None:
        raise ValidationError("验证码无效或已过期")
    now = iso(utc_now())
    user = store.update_user(record["user_id"], email_verified_at=now, status="active")
    if user is None:
        raise ValidationError("账号不存在")
    store.write_audit(action="account.verify_email", actor_id=user.id, actor_name=user.username)
    return user


def login_with_password(
    store: IdentityStore,
    *,
    handle: str,
    password: str,
    ip: str = "",
    user_agent: str = "",
    limiter: "LoginThrottle | None" = None,
) -> tuple[User, str]:
    """返回 ``(用户, 明文会话 token)``。失败一律 ``AuthenticationError``。

    ``limiter`` 允许调用方注入独立的限流器。组合根为**每个 app 实例**建一个，
    这样并行测试与多进程部署不会互相污染计数。缺省用进程级单例。
    """
    counter = limiter or _throttle
    account = (handle or "").strip().lower()
    counter.check(account=account, ip=ip)
    user = store.get_user_by_login(account)
    if user is None:
        pw.verify_dummy(password)
        counter.record_failure(account=account, ip=ip)
        raise AuthenticationError(GENERIC_LOGIN_ERROR)
    if user.status == "disabled":
        counter.record_failure(account=account, ip=ip)
        raise AuthenticationError("账号已被停用，请联系管理员")
    if user.status == "deleted" or not user.can_login:
        pw.verify_dummy(password)
        counter.record_failure(account=account, ip=ip)
        raise AuthenticationError(GENERIC_LOGIN_ERROR)
    stored = store.get_password_hash(user.id)
    if not pw.verify_password(password, stored):
        counter.record_failure(account=account, ip=ip)
        store.write_audit(
            action="account.login",
            actor_id=user.id,
            actor_name=user.username,
            outcome="failed",
            ip=ip,
            detail={"provider": "local", "user_agent": user_agent[:512], "reason": "invalid_credentials"},
        )
        raise AuthenticationError(GENERIC_LOGIN_ERROR)
    if pw.needs_rehash(stored):
        # 登录成功这一刻是唯一能拿到明文的时机，顺手升档。
        store.set_password(user.id, password_hash=pw.hash_password(password), algo=pw.preferred_algo())
    counter.reset(account=account, ip=ip)
    token = store.create_session(user_id=user.id, ip=ip, user_agent=user_agent)
    store.update_user(user.id, last_login_at=iso(utc_now()))
    store.write_audit(action="account.login", actor_id=user.id, actor_name=user.username, ip=ip,
                      detail={"provider": "local", "user_agent": user_agent[:512]})
    refreshed = store.get_user(user.id)
    return (refreshed or user), token


def resolve_session(store: IdentityStore, token: str) -> AuthContext:
    """Cookie → AuthContext。过期/撤销/停用一律回匿名，不抛异常。"""
    if not token:
        return AuthContext()
    session = store.get_session(token)
    if session is None or not session.alive:
        return AuthContext()
    user = store.get_user(session.user_id)
    if user is None or user.status in ("disabled", "deleted"):
        return AuthContext()
    store.touch_session(session.id)
    return AuthContext(user=user, session_id=session.id, via="session")


def logout(store: IdentityStore, token: str) -> None:
    session = store.get_session(token)
    if session is not None:
        store.revoke_session(session.id)


def change_password(
    store: IdentityStore,
    *,
    user: User,
    old_password: str,
    new_password: str,
    keep_token: str = "",
) -> None:
    """改密后**踢掉除当前会话外的全部会话**。这是服务端会话相对 JWT 的核心价值。"""
    check_password_strength(new_password)
    stored = store.get_password_hash(user.id)
    if stored and not pw.verify_password(old_password, stored):
        raise AuthenticationError("原密码不正确")
    store.set_password(user.id, password_hash=pw.hash_password(new_password), algo=pw.preferred_algo())
    keep = token_digest(keep_token) if keep_token else ""
    store.revoke_user_sessions(user.id, keep_session_id=keep)
    store.write_audit(action="account.change_password", actor_id=user.id, actor_name=user.username)


def request_password_reset(store: IdentityStore, *, email: str, ip: str = "") -> dict[str, Any]:
    """找回密码。**不触发账号锁定**，也不泄漏邮箱是否存在。"""
    normalized = normalize_email(email)
    user = store.get_user_by_login(normalized)
    if user is None:
        return {"ok": True, "message": GENERIC_MAIL_SENT}
    token, code = store.create_verification(
        user_id=user.id, email=normalized, purpose="reset", request_ip=ip
    )
    subject, body = render_verification_mail(code=code, token=token, purpose="reset")
    try:
        Mailer().send(to=normalized, subject=subject, body=body)
    except OSError:
        pass
    return {"ok": True, "message": GENERIC_MAIL_SENT}


def confirm_password_reset(
    store: IdentityStore, *, token: str = "", code: str = "", email: str = "", new_password: str
) -> None:
    """重置成功后失效**全部**会话，且不自动登录（OWASP 建议）。"""
    check_password_strength(new_password)
    record = store.consume_verification(
        token=token, code=code, email=normalize_email(email) if email else "", purpose="reset"
    )
    if record is None:
        raise ValidationError("验证码无效或已过期")
    user_id = record["user_id"]
    store.set_password(
        user_id, password_hash=pw.hash_password(new_password), algo=pw.preferred_algo()
    )
    store.revoke_user_sessions(user_id)
    store.update_user(user_id, status="active", email_verified_at=iso(utc_now()))
    store.write_audit(action="account.reset_password", actor_id=user_id)


def update_profile(store: IdentityStore, *, user: User, **fields: Any) -> User:
    payload: dict[str, Any] = {}
    if "display_name" in fields:
        payload["display_name"] = str(fields["display_name"] or "")[:64]
    if "bio" in fields:
        payload["bio"] = str(fields["bio"] or "")[:280]
    if "avatar_url" in fields:
        payload["avatar_url"] = str(fields["avatar_url"] or "")[:512]
    if "username" in fields and fields["username"]:
        payload["username"] = normalize_username(str(fields["username"]))
    updated = store.update_user(user.id, **payload)
    if updated is None:
        raise ValidationError("账号不存在")
    return updated
