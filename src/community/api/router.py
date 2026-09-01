"""社区 HTTP 入口。

一个工厂 ``build_community_router`` 对外，内部拆两张 router（广场 / 社交），
避免单文件继续膨胀过 600 行。
"""

from typing import Any, Callable

from fastapi import APIRouter

from src.community.api.social_router import build_community_social_router
from src.community.api.strategies_router import build_community_strategies_router


def build_community_router(
    *,
    write_dependency: Callable[..., Any],
    auth_dependency: Callable[..., Any],
    community_db: str | None = None,
) -> APIRouter:
    """装配社区上下文的全部路由（前缀 ``/api/community``）。

    参数：

    - ``write_dependency`` — 组合根的写权限依赖（会话 / Bearer），所有写接口都挂它。
    - ``auth_dependency`` — 返回「当前用户」的依赖。**对匿名访客必须返回 None
        （或 ``user`` 为空的鉴权上下文）而不是抛 401**：广场、榜单、动态要能匿名浏览，
        写接口自己用 ``require_actor`` 卡 401。返回值形状随意（``Actor`` / identity 的
        ``AuthContext`` / 用户对象 / 字典 / 用户 id 字符串），由 ``api.deps.coerce_actor``
        收敛——社区刻意不与身份实现绑死。
    - ``community_db`` — 覆盖库路径（测试用）；缺省走 ``src.shared.paths.community_db()``。
    """
    router = APIRouter()
    router.include_router(
        build_community_strategies_router(
            write_dependency=write_dependency,
            auth_dependency=auth_dependency,
            community_db=community_db,
        )
    )
    router.include_router(
        build_community_social_router(
            write_dependency=write_dependency,
            auth_dependency=auth_dependency,
            community_db=community_db,
        )
    )
    return router
