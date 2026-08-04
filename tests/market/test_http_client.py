"""行情 HTTP 客户端单测。"""
from __future__ import annotations

import unittest
from unittest import mock

import requests
from requests.exceptions import ProxyError

from src.market.infrastructure import http_client
from src.market.infrastructure.http_client import (
    NO_PROXY,
    _is_market_host,
    install_market_proxy_fallback,
    market_get,
    market_session,
)


class HttpClientTests(unittest.TestCase):
    def test_market_host_suffixes(self) -> None:
        self.assertTrue(_is_market_host("https://push2his.eastmoney.com/api/x"))
        self.assertTrue(_is_market_host("https://finance.sina.com.cn/a"))
        self.assertTrue(_is_market_host("https://proxy.finance.qq.com/x"))
        self.assertFalse(_is_market_host("https://api.openai.com/v1"))
        self.assertFalse(_is_market_host("https://example.com/"))

    def test_market_session_ignores_env_proxy(self) -> None:
        self.assertFalse(market_session().trust_env)

    def test_market_get_uses_session(self) -> None:
        session = market_session()
        with mock.patch.object(
            session, "get", return_value=mock.Mock(status_code=200)
        ) as get:
            market_get("https://finance.sina.com.cn/x", session=session, timeout=5)
            get.assert_called_once()

    def test_proxy_fallback_retries_direct_on_proxy_error(self) -> None:
        calls: list[object] = []

        def fake_original(
            self: requests.Session, method: str, url: str, **kwargs: object
        ) -> mock.Mock:
            calls.append(kwargs.get("proxies"))
            if len(calls) == 1:
                raise ProxyError("proxy down")
            return mock.Mock(status_code=200)

        saved_flag = http_client._proxy_fallback_installed
        saved_orig = http_client._original_session_request
        saved_request = requests.Session.request
        try:
            http_client._proxy_fallback_installed = False
            http_client._original_session_request = None
            requests.Session.request = fake_original  # type: ignore[method-assign]
            install_market_proxy_fallback()
            session = requests.Session()
            out = session.request("GET", "https://82.push2.eastmoney.com/api/x")
            self.assertEqual(out.status_code, 200)
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0])
            self.assertEqual(calls[1], NO_PROXY)
            # 非行情域名不重试
            calls.clear()

            def ok_only(
                self: requests.Session, method: str, url: str, **kwargs: object
            ) -> mock.Mock:
                calls.append(url)
                return mock.Mock(status_code=200)

            http_client._original_session_request = ok_only
            session.request("GET", "https://api.openai.com/v1/x")
            self.assertEqual(calls, ["https://api.openai.com/v1/x"])
        finally:
            requests.Session.request = saved_request  # type: ignore[method-assign]
            http_client._proxy_fallback_installed = False
            http_client._original_session_request = None
            if saved_flag:
                install_market_proxy_fallback()
            else:
                http_client._proxy_fallback_installed = saved_flag
                http_client._original_session_request = saved_orig

    def test_proxy_fallback_does_not_retry_market_post(self) -> None:
        calls: list[str] = []

        def fake_original(
            self: requests.Session, method: str, url: str, **kwargs: object
        ) -> mock.Mock:
            calls.append(method)
            raise ProxyError("proxy down")

        saved_flag = http_client._proxy_fallback_installed
        saved_orig = http_client._original_session_request
        saved_request = requests.Session.request
        try:
            http_client._proxy_fallback_installed = False
            http_client._original_session_request = None
            requests.Session.request = fake_original  # type: ignore[method-assign]
            install_market_proxy_fallback()
            with self.assertRaises(ProxyError):
                requests.Session().request("POST", "https://push2.eastmoney.com/api/x")
            self.assertEqual(calls, ["POST"])
        finally:
            requests.Session.request = saved_request  # type: ignore[method-assign]
            http_client._proxy_fallback_installed = False
            http_client._original_session_request = None
            if saved_flag:
                install_market_proxy_fallback()
            else:
                http_client._proxy_fallback_installed = saved_flag
                http_client._original_session_request = saved_orig


if __name__ == "__main__":
    unittest.main()
