"""identity 的 HTTP 入站适配器：请求模型 + 依赖。

``build_auth_dependency`` 是组合根与业务路由之间唯一的握手点：
组合根调用它拿到一个 FastAPI 依赖，再把这个依赖注给各上下文的 router 工厂。
这样业务上下文既拿得到「当前用户」，又不用 import ``src.app``（会违反
``contexts-must-not-import-composition-root`` 契约）。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.identity.domain.models import AuthContext, IdentityError
from src.identity.infrastructure.store import IdentityStore

#: 会话 Cookie 名。与旧的 ``palace_session``（starlette SessionMiddleware）
#: 刻意不同名：两套机制并存期间互不干扰，回滚也不会串味。
SESSION_COOKIE = "loci_session"
#: 扫码绑定 Cookie，5 分钟即焚。
BINDING_COOKIE = "loci_qr_bind"


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(AuthModel):
    #: 登录名或邮箱都收。历史上 /api/auth/login 用的是 username，保持兼容。
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(AuthModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    username: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=64)


class VerifyRequest(AuthModel):
    token: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=8)
    email: str = Field(default="", max_length=254)


class EmailOnlyRequest(AuthModel):
    email: str = Field(min_length=3, max_length=254)


class ResetConfirmRequest(AuthModel):
    token: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=8)
    email: str = Field(default="", max_length=254)
    new_password: str = Field(min_length=8, max_length=256)


class ChangePasswordRequest(AuthModel):
    old_password: str = Field(default="", max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ProfileRequest(AuthModel):
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=280)
    avatar_url: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=32)


class QrStartRequest(AuthModel):
    provider: str = Field(min_length=1, max_length=32)
    redirect_to: str = Field(default="/", max_length=256)


class MockConfirmRequest(AuthModel):
    state: str = Field(min_length=8, max_length=128)
    handle: str = Field(default="demo", max_length=32)


class RoleRequest(AuthModel):
    role: str = Field(pattern="^(admin|visitor)$")


class StatusRequest(AuthModel):
    status: str = Field(pattern="^(active|pending|disabled)$")


class QuotaRequest(AuthModel):
    llm_monthly_tokens: int | None = None
    llm_daily_calls: int | None = None
    strategy_slots: int | None = None
    publish_slots: int | None = None
    job_slots: int | None = None
    storage_mb: int | None = None


class AdminPasswordRequest(AuthModel):
    new_password: str = Field(min_length=8, max_length=256)


class AdminCreateUserRequest(AuthModel):
    """管理员开号的入参。自助注册默认关闭，这是账号的正常来源。"""

    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=254)
    role: str = Field(default="visitor", pattern="^(admin|visitor)$")
    status: str = Field(default="active", pattern="^(active|disabled)$")


def client_ip(request: Request) -> str:
    """uvicorn 以 ``--proxy-headers`` 启动，经 Nginx 后这里已是真实来源。"""
    return request.client.host if request.client else ""


def to_http(exc: IdentityError) -> HTTPException:
    headers: dict[str, str] = {}
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return HTTPException(status_code=exc.http_status, detail=str(exc), headers=headers or None)


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
    key=SESSION_COOKIE,
    value=token,
    max_age=30 * 24 * 3600,
    httponly=True,
    secure=secure,
    samesite="lax",
    path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def build_auth_dependency(
    identity_db: str | None = None,
    *,
    auto_login_primary: bool = False,
):
    """返回 FastAPI 依赖：``Request -> AuthContext``。

    识别顺序：会话 Cookie → 无凭证的桌面自动登录。个人开放 API Key 已停用。都没命中就是匿名——
    **这里不抛异常**，鉴权由各路由自己按需 require。

    ``auto_login_primary`` 是桌面单机形态的兼容闸门：本地跑 ``loci.py`` 的人
    从来不需要登录，升级到 v2 之后也不该突然被拦在登录页外。它只在
    **非 production** 下被组合根打开；生产恒为 False。
    """
    from src.identity.application import accounts

    def current_auth(request: Request) -> AuthContext:
        cached = getattr(request.state, "loci_auth", None)
        if isinstance(cached, AuthContext):
            return cached
        context = AuthContext()
        token = request.cookies.get(SESSION_COOKIE, "")
        with IdentityStore(identity_db) as store:
            if token:
                context = accounts.resolve_session(store, token)
            if not context.authenticated and auto_login_primary and not token and not request.headers.get("Authorization"):
                context = _primary_admin_context(store)
        request.state.loci_auth = context
        return context

    return current_auth


def _primary_admin_context(store: IdentityStore) -> AuthContext:
    """桌面模式：直接以主租户管理员身份视之，不签发会话。"""
    from src.shared.tenancy import PRIMARY_TENANT

    row = store.conn.execute(
        "SELECT id FROM users WHERE tenant_id = ? AND status = 'active' AND role = 'admin' LIMIT 1",
        (PRIMARY_TENANT,),
    ).fetchone()
    if row is None:
        return AuthContext()
    user = store.get_user(row["id"])
    return AuthContext(user=user, via="desktop") if user else AuthContext()


def require_admin_context(context: AuthContext) -> Any:
    try:
        return context.require_admin()
    except IdentityError as exc:
        raise to_http(exc) from exc
