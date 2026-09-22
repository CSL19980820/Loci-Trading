"""Read-only visitor policy, applied independently of deployment/auth mode.

HTTP verbs are denied by default; hiding a button is never an authorization gate.
Visitors use the explicit workspace grant carried by AuthContext, not a client-
supplied tenant id. Settings are private even when their endpoint uses GET.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from src.identity import AuthContext

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SESSION_ACTIONS = frozenset({"/api/auth/login", "/api/auth/logout"})
_PRIVATE_ROOTS = (
    "/api/admin", "/api/providers", "/api/mcp", "/api/auth/me",
    "/api/auth/api-keys", "/api/ai/profile", "/api/ai/tools",
    "/api/settings", "/api/system", "/api/jobs/quota",
)
_OPS_READ_ROOTS = (
    "/api/ops/guardian", "/api/ops/stock-agents", "/api/ops/paper-cabins",
    "/api/ops/alert-rules", "/api/ops/alert-hits",
)


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def visitor_allowed(method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    if method.upper() == "POST" and path in _SESSION_ACTIONS:
        return True
    if method.upper() not in _SAFE_METHODS:
        return False
    if any(under(path, root) for root in _PRIVATE_ROOTS):
        return False
    if under(path, "/api/ops"):
        return path == "/api/ops/version" or any(under(path, root) for root in _OPS_READ_ROOTS)
    return True


class VisitorAccessMiddleware:
    """Must run after TenantResolverMiddleware and before every business router."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        context = scope.get("state", {}).get("loci_auth")
        context = context if isinstance(context, AuthContext) else AuthContext()
        path = scope.get("path", "").rstrip("/") or "/"
        # No WebSocket mutation channel may bypass the HTTP policy. This app's
        # live read feeds use SSE; visitors need no bidirectional socket.
        if scope["type"] == "websocket":
            if not context.user or not context.user.is_admin:
                await send({"type": "websocket.close", "code": 4403})
                return
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if not context.authenticated and request.cookies.get("loci_session"):
            # An invalid/kicked session must not fall back to permissive desktop
            # access; auth endpoints still allow logging in again and logging out.
            if path.startswith("/api/") and not under(path, "/api/auth") and path != "/api/health":
                await JSONResponse({"detail": "登录已失效，请重新登录", "code": "session_expired"}, status_code=401)(scope, receive, send)
                return
        if context.user and not context.user.is_admin:
            if any(under(path, root) for root in ("/ops", "/admin", "/account")):
                await RedirectResponse("/", status_code=303)(scope, receive, send)
                return
            if path.startswith("/api/") and not visitor_allowed(request.method, path):
                await JSONResponse({"detail": "访客仅可浏览，无权执行此操作或访问设置", "code": "visitor_read_only"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
