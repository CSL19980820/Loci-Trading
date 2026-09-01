"""写权限闸门：浏览器会话 / Agent Bearer / 两者取或。

这三个判定原先是 `create_app` 里的闭包。搬出组合根之后**仍然是闭包**，靠
`build_auth_guards` 工厂现造——不能改成模块级全局变量：它们捕获的是**每个
app 实例自己的**配置（`require_write_auth` 开关与 `write_token`）。改成全局
意味着同一进程里先后建的两个 app（`tests/app/**` 满地都是）会互相覆盖对方的
令牌与鉴权开关，后建的 app 能拿先建 app 的 Bearer 写库，而且只在多实例场景
下才复现。

`current_context` 反过来是无状态的（只读 `request.state` 里中间件放好的缓存），
所以它是模块级函数。
"""
from hmac import compare_digest
from typing import Callable, NamedTuple

from fastapi import HTTPException, Request

from src.identity import AuthContext


class AuthGuards(NamedTuple):
    """一个 app 实例的三个写权限判定；`require_write_access` 供路由注入。"""

    has_browser_session: Callable[[Request], bool]
    has_agent_token: Callable[[Request], bool]
    require_write_access: Callable[[Request], None]


def current_context(request: Request) -> AuthContext:
    """中间件已解析过身份，这里只取缓存，不再开库。"""
    cached = getattr(request.state, "loci_auth", None)
    return cached if isinstance(cached, AuthContext) else AuthContext()


def build_auth_guards(*, require_write_auth: bool, write_token: str) -> AuthGuards:
    """按本 app 实例的配置现造三个闸门。

    `require_write_auth=False`（本地桌面默认）时浏览器会话恒真，保持单机零登录；
    `write_token` 为空则 Agent Bearer 通道整条关闭，不会退化成「空令牌可写」。
    """

    def has_browser_session(request: Request) -> bool:
        """v2：认 identity 会话 Cookie。桌面模式下已由中间件自动登录。"""
        if not require_write_auth:
            return True
        return current_context(request).authenticated

    def has_agent_token(request: Request) -> bool:
        """Agent 无浏览器会话时可用的服务器端 Bearer 令牌。

        保留这条通道是为了不打断既有 CI / 脚本 / MCP 客户端。它代表「机器身份」，
        作用域恒为主租户，不属于任何用户，因此拿不到别人的私有库。
        """
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        return bool(
            write_token
            and scheme.lower() == "bearer"
            and token
            and compare_digest(token, write_token)
        )

    def require_write_access(request: Request) -> None:
        """浏览器会话或 Agent Bearer 令牌均可写入不可变账本。"""
        if has_browser_session(request) or has_agent_token(request):
            return
        raise HTTPException(status_code=401, detail="请先登录或提供有效的 Bearer 令牌")

    return AuthGuards(has_browser_session, has_agent_token, require_write_access)
