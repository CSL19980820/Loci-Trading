"""行情 HTTP：线程隔离的短连接池、显式超时和有限幂等重试。

调用方提供的 Session 仍由调用方管理。默认连接池只缓存传输连接，不跨请求保留
Cookie，也不共享认证状态；不再全局 monkeypatch 第三方 HTTP 客户端。
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
import hashlib
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

CONNECT_TIMEOUT_CAP = 3.0
TRANSIENT_RETRIES = 1
_RETRY_BACKOFF_SEC = 0.25
_MAX_POOLS_PER_THREAD = 8
_local = threading.local()


def market_session() -> requests.Session:
    """独立直连会话；用于需要由调用方显式限定生命周期的连续请求。"""
    session = requests.Session()
    session.trust_env = False
    return session


class _ThreadSessions:
    def __init__(self) -> None:
        self.sessions: OrderedDict[tuple[str, str, str], requests.Session] = OrderedDict()

    def close(self) -> None:
        while self.sessions:
            _, session = self.sessions.popitem(last=False)
            session.close()

    def __del__(self) -> None:
        self.close()


def close_thread_sessions() -> None:
    """测试和持久工作线程关闭时释放连接；线程销毁也会释放。"""
    pool = getattr(_local, "pool", None)
    if pool is not None:
        pool.close()
        del _local.pool


def _pooled_session(url: str, headers: Mapping[str, str] | None) -> requests.Session:
    parsed = urlparse(url)
    # 带凭据的请求连池也隔离；散列仅作内存键，既不记录也不输出。
    credentials = sorted((k.casefold(), str(v)) for k, v in (headers or {}).items()
                         if k.casefold() in {"authorization", "cookie", "x-api-key"})
    digest = hashlib.sha256(repr(credentials).encode()).hexdigest()
    key = (parsed.scheme, parsed.netloc, digest)
    pool = getattr(_local, "pool", None)
    if pool is None:
        pool = _local.pool = _ThreadSessions()
    session = pool.sessions.pop(key, None)
    if session is None:
        session = market_session()
    pool.sessions[key] = session
    while len(pool.sessions) > _MAX_POOLS_PER_THREAD:
        _, old = pool.sessions.popitem(last=False)
        old.close()
    return session


def market_get(
    url: str, *, params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None, timeout: float = 12,
    session: requests.Session | None = None, retries: int = TRANSIENT_RETRIES,
    connect_timeout: float | None = None,
) -> requests.Response:
    """直连 GET；复用同线程同主机连接，连接/读取超时有限重试。"""
    if float(timeout) <= 0:
        raise ValueError("timeout 必须为正数")
    caller = session if session is not None else _pooled_session(url, headers)
    owned = session is None
    handshake = float(connect_timeout) if connect_timeout is not None else CONNECT_TIMEOUT_CAP
    budget = (min(float(timeout), max(0.5, handshake)), float(timeout))
    attempts = min(3, max(0, int(retries)) + 1)
    if owned:
        caller.cookies.clear()
    try:
        for attempt in range(attempts):
            try:
                return caller.get(url, params=dict(params) if params else None,
                                  headers=dict(headers) if headers else None, timeout=budget)
            except (RequestsConnectionError, Timeout):
                if attempt + 1 >= attempts:
                    raise
                time.sleep(_RETRY_BACKOFF_SEC * (attempt + 1))
    finally:
        if owned:
            caller.cookies.clear()
    raise RuntimeError("GET 未执行")  # pragma: no cover
