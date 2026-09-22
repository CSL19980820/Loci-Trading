"""单次 Agent 运行的连接所有权；不跨运行、租户或执行线程共享。"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from contextvars import ContextVar
from threading import get_ident
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from src.shared.tenancy import current_tenant

if TYPE_CHECKING:
    from src.ai.infrastructure.client import ProviderConfig

T = TypeVar("T")


class _ClientSession:
    def __init__(self) -> None:
        self.thread = get_ident()
        self.tenant = current_tenant()
        self.active = True
        self.stack = ExitStack()
        self.clients: dict[tuple[str, ...], object] = {}


_CURRENT: ContextVar[_ClientSession | None] = ContextVar("llm_client_session", default=None)


@contextmanager
def llm_client_scope() -> Iterator[None]:
    """每次调用都创建独立作用域，包括嵌套的子 Agent；所有出口释放资源。"""
    session = _ClientSession()
    token = _CURRENT.set(session)
    try:
        with session.stack:
            yield
    finally:
        session.active = False
        session.clients.clear()
        _CURRENT.reset(token)


@contextmanager
def borrow_client(
    config: ProviderConfig,
    factory: Callable[[], AbstractContextManager[T]],
    *,
    kind: Literal["sync", "async"] = "sync",
) -> Iterator[T]:
    session = _CURRENT.get()
    # copy_context 会把作用域带进工具线程；不得把 Runner/连接借给另一个线程。
    if (session is None or not session.active or session.thread != get_ident()
            or session.tenant != current_tenant()):
        with factory() as client:
            yield client
        return

    # 超时和模型名是逐请求参数，不应让墙钟预算变化导致每轮重建连接。
    # 凭据仅用于内存内隔离，不写日志。
    key = (kind, config.name, config.protocol, config.base_url, config.api_key, config.proxy_url,
           config.grpc_endpoint, config.grpc_token, config.grpc_ca_file, str(config.grpc_fallback),
           config.model if config.grpc_endpoint else "", config.grpc_tenant)
    if key not in session.clients:
        session.clients[key] = session.stack.enter_context(factory())
    yield cast(T, session.clients[key])
