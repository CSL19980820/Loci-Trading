"""``/api/auth/*``：注册、登录、扫码、会话、个人资料、API Key、通知。

本文件只做三件事：解析入参 → 调 application → 映射错误为 HTTP。
任何业务判断（限流、合并账号、口令强度）都在 application/domain，别往这搬。

关于「公开」与「需登录」：``/api/auth/**`` 里除了 ``/session`` ``/me`` ``/logout``
之外全部是公开端点——它们本来就是给未登录的人用的。组合根的鉴权中间件
必须把整个前缀放行，否则注册页会自己把自己挡在门外。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from src.identity.api.schemas import (
    BINDING_COOKIE,
    ChangePasswordRequest,
    EmailOnlyRequest,
    LoginRequest,
    MockConfirmRequest,
    ProfileRequest,
    QrStartRequest,
    RegisterRequest,
    ResetConfirmRequest,
    SESSION_COOKIE,
    VerifyRequest,
    clear_session_cookie,
    client_ip,
    set_session_cookie,
    to_http,
)
from src.identity.application import accounts, social_login
from src.identity.domain.models import AuthContext, IdentityError
from src.identity.infrastructure.registry import login_options, signup_enabled
from src.identity.infrastructure.store import IdentityStore


def build_auth_router(
    *,
    auth_dependency: Any,
    identity_db: str | None = None,
    cookie_secure: bool = True,
    limiter: Any = None,
) -> APIRouter:
    """``cookie_secure`` 由组合根按环境决定：本地 http 调试必须传 False。

    ``limiter`` 是每个 app 实例一份的登录限流器。用进程级单例会让连续跑的
    测试互相污染失败计数，也会让多 app 共存时彼此锁死。
    """
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    Auth = Depends(auth_dependency)
    login_limiter = limiter if limiter is not None else accounts.LoginThrottle()

    def _store() -> IdentityStore:
        return IdentityStore(identity_db)

    @router.get("/options")
    def options() -> dict[str, Any]:
        """登录页要画哪些按钮。未配置的 provider 不会出现。"""
        return login_options()

    @router.post("/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        try:
            with _store() as store:
                user, token = accounts.login_with_password(
                    store,
                    handle=payload.username,
                    password=payload.password,
                    ip=client_ip(request),
                    user_agent=request.headers.get("User-Agent", ""),
                    limiter=login_limiter,
                )
                profile = user.self_dict()
        except IdentityError as exc:
            raise to_http(exc) from exc
        set_session_cookie(response, token, secure=cookie_secure)
        return {"authenticated": True, "user": profile}

    @router.post("/register")
    def register(payload: RegisterRequest, request: Request) -> dict[str, Any]:
        """邮箱自助注册。**默认关闭**（``LOCI_ALLOW_SIGNUP``）。"""
        if not signup_enabled():
            # 本系统不走注册制：账号由管理员在后台新增。这里在**任何副作用之前**
            # 拦掉——既不落审计也不发信，否则关掉的注册端点还是个邮箱探测器 +
            # 免费发信器（照样能给任意地址投「有人尝试注册」提醒）。
            raise HTTPException(
                status_code=403, detail="本站不开放自助注册，请联系管理员开通账号"
            )
        try:
            with _store() as store:
                return accounts.register_with_email(
                    store,
                    email=payload.email,
                    password=payload.password,
                    username=payload.username,
                    display_name=payload.display_name,
                    ip=client_ip(request),
                )
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.post("/verify-email")
    def verify_email(payload: VerifyRequest, response: Response) -> dict[str, Any]:
        try:
            with _store() as store:
                user = accounts.verify_email(
                    store, token=payload.token, code=payload.code, email=payload.email
                )
                token = store.create_session(user_id=user.id)
                profile = user.self_dict()
        except IdentityError as exc:
            raise to_http(exc) from exc
        set_session_cookie(response, token, secure=cookie_secure)
        return {"authenticated": True, "user": profile}

    @router.post("/resend-code")
    def resend_code(payload: EmailOnlyRequest, request: Request) -> dict[str, Any]:
        try:
            with _store() as store:
                return accounts.resend_verification(
                    store, email=payload.email, ip=client_ip(request)
                )
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.post("/forgot-password")
    def forgot_password(payload: EmailOnlyRequest, request: Request) -> dict[str, Any]:
        try:
            with _store() as store:
                return accounts.request_password_reset(
                    store, email=payload.email, ip=client_ip(request)
                )
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.post("/reset-password")
    def reset_password(payload: ResetConfirmRequest) -> dict[str, bool]:
        try:
            with _store() as store:
                accounts.confirm_password_reset(
                    store,
                    token=payload.token,
                    code=payload.code,
                    email=payload.email,
                    new_password=payload.new_password,
                )
        except IdentityError as exc:
            raise to_http(exc) from exc
        # 刻意不自动登录：OWASP 建议重置后要求用户主动用新口令登录一次。
        return {"ok": True}

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            with _store() as store:
                accounts.logout(store, token)
        clear_session_cookie(response)
        return {"authenticated": False}

    @router.get("/session")
    def session(context: AuthContext = Auth) -> dict[str, Any]:
        """前端路由守卫每次导航都会打这个。保持轻量。"""
        if not context.authenticated:
            return {"authenticated": False, "username": "", "user": None}
        user = context.require_user()
        return {
            "authenticated": True,
            # 兼容旧前端：它读的是顶层 username。
            "username": user.username,
            "user": user.self_dict(),
        }

    @router.get("/me")
    def me(context: AuthContext = Auth) -> dict[str, Any]:
        user = context.require_user()
        with _store() as store:
            return {
                "user": user.self_dict(),
                "identities": [item.public_dict() for item in store.list_identities(user.id)],
                "quota": store.get_quota(user.id),
                "sessions": store.list_sessions(user.id),
                "unread": store.unread_count(user.id),
            }

    @router.patch("/me")
    def update_me(payload: ProfileRequest, context: AuthContext = Auth) -> dict[str, Any]:
        user = context.require_user()
        fields = {key: value for key, value in payload.model_dump().items() if value is not None}
        try:
            with _store() as store:
                return accounts.update_profile(store, user=user, **fields).self_dict()
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.post("/me/password")
    def change_password(
        payload: ChangePasswordRequest, request: Request, context: AuthContext = Auth
    ) -> dict[str, bool]:
        user = context.require_user()
        try:
            with _store() as store:
                accounts.change_password(
                    store,
                    user=user,
                    old_password=payload.old_password,
                    new_password=payload.new_password,
                    keep_token=request.cookies.get(SESSION_COOKIE, ""),
                )
        except IdentityError as exc:
            raise to_http(exc) from exc
        return {"ok": True}

    @router.delete("/me/sessions")
    def revoke_other_sessions(request: Request, context: AuthContext = Auth) -> dict[str, int]:
        user = context.require_user()
        with _store() as store:
            keep = store.get_session(request.cookies.get(SESSION_COOKIE, ""))
            revoked = store.revoke_user_sessions(user.id, keep_session_id=keep.id if keep else "")
        return {"revoked": revoked}

    @router.delete("/me/identities/{identity_id}")
    def unbind(identity_id: str, context: AuthContext = Auth) -> dict[str, bool]:
        from src.identity.domain.models import can_unbind

        user = context.require_user()
        with _store() as store:
            identities = store.list_identities(user.id)
            if not can_unbind(identities, identity_id, has_password=bool(user.password_algo)):
                raise HTTPException(status_code=409, detail="解绑后将无法登录，请先设置密码或绑定其他方式")
            return {"ok": store.delete_identity(identity_id, user.id)}

    # ---- 第三方 / 扫码 ---------------------------------------------------

    @router.post("/qr/start")
    def qr_start(payload: QrStartRequest, response: Response) -> dict[str, Any]:
        try:
            with _store() as store:
                result = social_login.start_login(
                    store, provider_name=payload.provider, redirect_to=payload.redirect_to
                )
        except IdentityError as exc:
            raise to_http(exc) from exc
        binding = str(result.pop("binding", ""))
        if binding:
            response.set_cookie(
                BINDING_COOKIE,
                binding,
                max_age=300,
                httponly=True,
                secure=cookie_secure,
                samesite="lax",
                path="/",
            )
        return result

    @router.get("/qr/{state}")
    def qr_poll(state: str) -> dict[str, Any]:
        """短轮询。二维码只活 5 分钟、状态只变 1-2 次，不值得为它开一条 SSE。"""
        with _store() as store:
            return social_login.poll_state(store, state)

    @router.post("/qr/{state}/scanned")
    def qr_scanned(state: str) -> dict[str, bool]:
        with _store() as store:
            return {"ok": social_login.mark_scanned(store, state)}

    @router.post("/qr/{state}/claim")
    def qr_claim(state: str, request: Request, response: Response) -> dict[str, Any]:
        try:
            with _store() as store:
                claimed = social_login.claim_session(
                    store, state=state, binding=request.cookies.get(BINDING_COOKIE, "")
                )
                if claimed is None:
                    raise HTTPException(status_code=409, detail="登录请求尚未确认或已被兑换")
                user, token = claimed
                profile = user.self_dict()
        except IdentityError as exc:
            raise to_http(exc) from exc
        set_session_cookie(response, token, secure=cookie_secure)
        response.delete_cookie(BINDING_COOKIE, path="/")
        return {"authenticated": True, "user": profile}

    @router.post("/mock/confirm")
    def mock_confirm(payload: MockConfirmRequest, request: Request) -> dict[str, Any]:
        """演示 provider 的「手机上点确认」。生产环境 provider 不可用，这里自然 400。"""
        try:
            with _store() as store:
                social_login.complete_callback(
                    store,
                    provider_name="mock",
                    code=payload.handle,
                    state=payload.state,
                    ip=client_ip(request),
                    user_agent=request.headers.get("User-Agent", ""),
                )
        except IdentityError as exc:
            raise to_http(exc) from exc
        return {"ok": True}

    @router.get("/callback/{provider_name}")
    def oauth_callback(
        provider_name: str,
        request: Request,
        code: str = Query(default=""),
        state: str = Query(default=""),
    ) -> RedirectResponse:
        """厂商 302 回来的落点。成功就带 state 跳回登录页，由前端兑换会话。"""
        if not code or not state:
            return RedirectResponse(url="/login?auth_error=missing_code", status_code=302)
        try:
            with _store() as store:
                social_login.complete_callback(
                    store,
                    provider_name=provider_name,
                    code=code,
                    state=state,
                    ip=client_ip(request),
                    user_agent=request.headers.get("User-Agent", ""),
                )
        except IdentityError as exc:
            return RedirectResponse(
                url=f"/login?auth_error={exc.code}", status_code=302
            )
        return RedirectResponse(url=f"/login?claim_state={state}", status_code=302)

    # ---- 本人通知 --------------------------------------------------

    @router.get("/notifications")
    def notifications(
        unread_only: bool = Query(default=False), context: AuthContext = Auth
    ) -> dict[str, Any]:
        user = context.require_user()
        with _store() as store:
            return {
                "items": store.list_notifications(user.id, unread_only=unread_only),
                "unread": store.unread_count(user.id),
            }

    @router.post("/notifications/read")
    def mark_read(context: AuthContext = Auth) -> dict[str, int]:
        user = context.require_user()
        with _store() as store:
            return {"marked": store.mark_notifications_read(user.id)}

    return router
