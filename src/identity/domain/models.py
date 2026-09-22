"""身份域模型：用户、外部身份、会话、角色。

这一层不认识 SQLite、不认识 FastAPI、不认识 httpx——只有值对象与规则。

两条容易被忽略的规则写在这里而不是 store 里：

1. **一个账号至少保留一种可登录方式**。解绑最后一个身份、或清掉唯一的口令，
   都会把用户永久锁在门外。``can_unbind`` 负责挡住。
2. **昵称永远不能用来合并账号**。微信/QQ 昵称可以随便改、可以重名，
拿它当身份等于把账号送人。合并只认 ``(provider, subject)`` 与 unionid。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
import re

#: 角色。刻意只有两级：可操作的管理员与只读访客。
#: 「专业版/付费档」是配额问题，不是角色问题，走 user_quotas。
Role = Literal["admin", "visitor"]
ROLES: tuple[Role, ...] = ("admin", "visitor")

#: 账号状态。pending = 邮箱未验证（可登录，但拿不到敏感能力）。
UserStatus = Literal["active", "pending", "disabled", "deleted"]
USER_STATUSES: tuple[UserStatus, ...] = ("active", "pending", "disabled", "deleted")

#: 身份提供方族。合并 unionid 时以「族」为作用域，而不是单个 provider——
#: 同一个微信用户从网站应用和公众号进来，openid 不同但 unionid 相同。
ProviderFamily = Literal["local", "wechat", "qq", "mock"]

#: 扫码登录状态机。confirmed → consumed 只允许发生一次（CAS 防重放）。
QrStatus = Literal["pending", "scanned", "confirmed", "consumed", "expired", "failed"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
#: 登录名：字母开头，字母数字下划线中划线点，3-32 位。管理员 lociAdmin 合规。
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,31}$")


class IdentityError(ValueError):
    """身份域的业务错误；api 层统一映射成 4xx。"""

    code = "identity_error"
    http_status = 400


class ValidationError(IdentityError):
    code = "validation_error"
    http_status = 422


class AuthenticationError(IdentityError):
    """口令错、账号不存在、会话失效——对外一律同一句话，防账号枚举。"""

    code = "authentication_failed"
    http_status = 401


class AuthorizationError(IdentityError):
    code = "forbidden"
    http_status = 403


class ConflictError(IdentityError):
    code = "conflict"
    http_status = 409


class RateLimitedError(IdentityError):
    code = "rate_limited"
    http_status = 429

    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """统一时间字面量：UTC + 秒精度 + 'Z'。库里排序与比较都靠字典序。"""
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_expired(raw: str | None, *, now: datetime | None = None) -> bool:
    moment = parse_iso(raw)
    if moment is None:
        return True
    return moment <= (now or utc_now())


def in_seconds(seconds: int, *, now: datetime | None = None) -> str:
    return iso((now or utc_now()) + timedelta(seconds=seconds))


def normalize_email(raw: str | None) -> str:
    """邮箱统一小写去空白。唯一索引建在 lower(email) 上，这里必须一致。"""
    value = (raw or "").strip().lower()
    if not value:
        return ""
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValidationError("邮箱格式不正确")
    return value


def normalize_username(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if not _USERNAME_RE.match(value):
        raise ValidationError("登录名需 3-32 位，字母开头，仅含字母数字与 . _ -")
    return value


def check_password_strength(password: str) -> None:
    """口令强度：只卡长度与「不是纯重复字符」，不搞组成规则。

        NIST SP800-63B 与 OWASP 都反对强制大小写/符号组合——它逼出的是
        ``Passw0rd!`` 这种可预测口令。长度才是真门槛。
        """
    if len(password) < 8:
        raise ValidationError("密码至少 8 位")
    if len(password) > 256:
        raise ValidationError("密码最长 256 位")
    if len(set(password)) < 3:
        raise ValidationError("密码过于简单")


@dataclass(frozen=True, slots=True)
class User:
    """账号事实。``tenant_id`` 决定这个人的私有库落在哪个目录。"""

    id: str
    tenant_id: str
    username: str
    email: str
    display_name: str
    role: Role = "visitor"
    status: UserStatus = "active"
    avatar_url: str = ""
    bio: str = ""
    email_verified_at: str | None = None
    password_algo: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_login_at: str | None = None
    must_change_password: bool = False
    view_tenant_id: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def email_verified(self) -> bool:
        return bool(self.email_verified_at)

    @property
    def can_login(self) -> bool:
        return self.status in ("active", "pending")

    def public_dict(self) -> dict[str, Any]:
        """给别人看的资料：不含邮箱、不含状态、不含任何可用于攻击的字段。"""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "avatar_url": self.avatar_url,
            "bio": self.bio,
            "role": self.role,
            "created_at": self.created_at,
        }

    def self_dict(self) -> dict[str, Any]:
        """给本人看的资料。"""
        data = self.public_dict()
        data.update(
            {
                "email": self.email,
                "email_verified": self.email_verified,
                "status": self.status,
                "tenant_id": self.tenant_id,
                "view_tenant_id": self.view_tenant_id if not self.is_admin else "",
                "read_only": not self.is_admin,
                "last_login_at": self.last_login_at,
                "must_change_password": self.must_change_password,
                "has_password": bool(self.password_algo),
            }
        )
        return data


@dataclass(frozen=True, slots=True)
class Identity:
    """一条外部（或本地）登录方式。``subject`` 是该 provider 下的稳定标识。"""

    id: str
    user_id: str
    provider: str
    family: ProviderFamily
    subject: str
    union_key: str | None = None
    display_name: str = ""
    avatar_url: str = ""
    created_at: str = ""
    last_login_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "family": self.family,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """一次登录会话。库里存的是 token 的 sha256，明文只在 Cookie 里活一次。"""

    id: str
    user_id: str
    identity_id: str | None
    created_at: str
    last_seen_at: str
    expires_at: str
    absolute_expires_at: str
    revoked_at: str | None = None
    ip: str = ""
    user_agent: str = ""

    @property
    def alive(self) -> bool:
        if self.revoked_at:
            return False
        return not is_expired(self.expires_at) and not is_expired(self.absolute_expires_at)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """一次请求的身份结论。未登录时 ``user`` 为 None。"""

    user: User | None = None
    session_id: str | None = None
    via: str = "anonymous"
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def authenticated(self) -> bool:
        return self.user is not None

    @property
    def tenant_id(self) -> str | None:
        if not self.user:
            return None
        if not self.user.is_admin:
            return self.user.view_tenant_id or self.user.tenant_id
        return self.user.tenant_id

    def require_user(self) -> User:
        if self.user is None:
            raise AuthenticationError("请先登录")
        return self.user

    def require_admin(self) -> User:
        user = self.require_user()
        if not user.is_admin:
            raise AuthorizationError("需要管理员权限")
        return user


def can_unbind(identities: list[Identity], target_id: str, *, has_password: bool) -> bool:
    """解绑后是否还剩至少一种登录方式。"""
    remaining = [item for item in identities if item.id != target_id]
    return bool(remaining) or has_password
