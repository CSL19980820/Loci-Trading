"""行情 HTTP：直连 Session + 系统代理失败时自动回退。

Windows 常把 Clash 写入注册表；``requests`` 默认会走 ``127.0.0.1:xxxx``。
代理挂掉时东财变成 ``ProxyError``。境内行情源应优先直连，或在代理失败后
直连重试。境外 LLM 的 ``proxy_url`` 不走本模块。
"""
from __future__ import annotations

from collections.abc import Mapping
import threading
from typing import Any
from urllib.parse import urlparse

import requests
from requests.exceptions import ProxyError

NO_PROXY: dict[str, None] = {"http": None, "https": None}

_MARKET_HOST_SUFFIXES = (
    "eastmoney.com",
    "sina.com.cn",
    "sinaimg.cn",
    "gtimg.cn",
    "qq.com",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
)

_patch_lock = threading.Lock()
_proxy_fallback_installed = False
_original_session_request = None


def market_session() -> requests.Session:
    """境内行情专用 Session：不读系统代理。"""
    session = requests.Session()
    session.trust_env = False
    return session


def market_get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 20,
    session: requests.Session | None = None,
) -> requests.Response:
    """GET；默认直连（不走系统代理）。"""
    caller = session or market_session()
    return caller.get(
        url,
        params=dict(params) if params else None,
        headers=dict(headers) if headers else None,
        timeout=timeout,
    )


def _is_market_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in _MARKET_HOST_SUFFIXES)


def install_market_proxy_fallback() -> None:
    """给 akshare 等内部 Session 打补丁：行情域名遇 ProxyError 则直连重试。

    幂等；只影响匹配 ``_MARKET_HOST_SUFFIXES`` 的 URL。
    """
    global _proxy_fallback_installed, _original_session_request
    with _patch_lock:
        if _proxy_fallback_installed:
            return
        _original_session_request = requests.Session.request

        def patched(
            self: requests.Session,
            method: str,
            url: str,
            **kwargs: Any,
        ) -> requests.Response:
            assert _original_session_request is not None
            # 只重试幂等行情读取；全局补丁绝不能让 POST/PUT 重复提交。
            if method.upper() != "GET" or not _is_market_host(url):
                return _original_session_request(self, method, url, **kwargs)
            try:
                return _original_session_request(self, method, url, **kwargs)
            except ProxyError:
                # trust_env 是 Session 可变状态；仅在代理失败的短窗口串行修改。
                with _patch_lock:
                    kwargs = {**kwargs, "proxies": NO_PROXY}
                    saved = self.trust_env
                    self.trust_env = False
                    try:
                        return _original_session_request(self, method, url, **kwargs)
                    finally:
                        self.trust_env = saved

        requests.Session.request = patched  # type: ignore[method-assign]
        _proxy_fallback_installed = True
