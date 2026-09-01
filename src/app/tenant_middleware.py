"""租户解析中间件：把「当前请求属于哪个用户」变成进程内的 ContextVar。

**为什么是纯 ASGI 中间件而不是 ``@app.middleware("http")``**：
``BaseHTTPMiddleware`` 会把下游应用放进另一个 anyio 任务里跑。
ContextVar 只在任务**创建那一刻**做快照拷贝，语义微妙且随 Starlette 版本变过。
纯 ASGI 中间件在同一个任务里 ``await`` 下游，绑定关系确定无疑；
同步路由走 ``run_in_threadpool``，anyio 会把当前 context 复制进线程，同样读得到。

这一层还顺手把 ``AuthContext`` 缓存进 ``scope[\"state\"]``，
让后面的依赖不用再开一次 identity.db。
"""
from __future__ import annotations

from typing import Any
import logging

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from src.identity import AuthContext
from src.shared.tenancy import reset_current_tenant, set_current_tenant

logger = logging.getLogger(__name__)


class TenantResolverMiddleware:
    """解析凭证 → 绑定租户 → 放行。凭证无效一律按匿名处理，不在这里拒绝。

        拒绝是路由与鉴权中间件的职责；这一层只负责「知道你是谁」。
        把两件事混在一起会让「公开端点」变得难以表达。
    """

    def __init__(self, app: Any, *, resolver: Any) -> None:
        self.app = app
        self._resolver = resolver

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        try:
            context = await run_in_threadpool(self._resolver, request)
        except Exception:
            # 身份库暂时不可用不能让整站 500：退化成匿名，鉴权层会给 401。
            logger.exception("解析当前用户失败（按匿名处理）")
            context = AuthContext()
        scope.setdefault("state", {})["loci_auth"] = context
        token = set_current_tenant(context.tenant_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_tenant(token)
