"""社区 api 层共用依赖：Store 打开器、当前用户、领域错误映射。

放这里而不是组合根：``src/app`` 只需要注入 ``write_dependency`` 与
``auth_dependency`` 两个可调用对象，剩下的装配全在本上下文内部完成
（见 ``.importlinter`` 的 contexts-must-not-import-composition-root）。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Callable, Mapping

from fastapi import HTTPException

from src.community.domain.models import Actor, CommunityError, PublishRuleError
from src.community.infrastructure.store import CommunityStore


def store_opener(community_db: str | None) -> Callable[[], Iterator[CommunityStore]]:
    """造一个「每请求一个连接」的依赖。SQLite 连接不跨线程复用。"""

    def _open() -> Iterator[CommunityStore]:
        store = CommunityStore(community_db)
        try:
            yield store
        finally:
            store.close()

    return _open


def coerce_actor(raw: Any) -> Actor | None:
    """把 ``auth_dependency`` 的返回值收敛成 ``Actor``。

    刻意用鸭子类型而不是 ``from src.identity import AuthContext``：社区不该跟身份
    实现绑死（组合根今天注入 identity 的 AuthContext，明天可能注入一个测试替身）。
    支持四种形状：``Actor`` / 带 ``user`` 的鉴权上下文 / 用户对象 / 字典 / 纯字符串。
    """
    if raw is None:
        return None
    if isinstance(raw, Actor):
        return raw
    if isinstance(raw, str):
        return Actor(user_id=raw) if raw.strip() else None
    if isinstance(raw, Mapping):
        return _from_mapping(raw)
    user = getattr(raw, "user", None)
    if user is not None and not isinstance(user, (str, Mapping)):
        return _from_object(user)
    if user is None and hasattr(raw, "user"):
        # 鉴权上下文明确表示「未登录」
        return None
    return _from_object(raw)


def _from_mapping(raw: Mapping[str, Any]) -> Actor | None:
    user = raw.get("user")
    if isinstance(user, Mapping):
        return _from_mapping(user)
    user_id = str(raw.get("user_id") or raw.get("id") or raw.get("sub") or "").strip()
    if not user_id:
        return None
    role = str(raw.get("role") or "")
    return Actor(
        user_id=user_id,
        display_name=str(raw.get("display_name") or raw.get("username") or ""),
        is_admin=bool(raw.get("is_admin")) or role == "admin",
    )


def _from_object(raw: Any) -> Actor | None:
    user_id = str(getattr(raw, "user_id", "") or getattr(raw, "id", "") or "").strip()
    if not user_id:
        return None
    role = str(getattr(raw, "role", "") or "")
    return Actor(
        user_id=user_id,
        display_name=str(getattr(raw, "display_name", "") or getattr(raw, "username", "") or ""),
        is_admin=bool(getattr(raw, "is_admin", False)) or role == "admin",
    )


def require_actor(raw: Any) -> Actor:
    """写操作用：拿不到当前用户就 401，绝不退化成匿名写。"""
    actor = coerce_actor(raw)
    if actor is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return actor


@contextmanager
def domain_errors() -> Iterator[None]:
    """领域错误 → HTTP。

    ``APIRouter`` 挂不了 exception handler（那是 app 级的），所以每个端点在这个
    上下文管理器里调 application。捕获的是具体的 ``CommunityError``，不是裸
    ``Exception``——真 bug 仍然应该 500 并留完整栈。
    """
    try:
        yield
    except PublishRuleError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"code": exc.code, "message": str(exc), "violations": exc.violations},
        ) from exc
    except CommunityError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail={"code": exc.code, "message": str(exc)}
        ) from exc
