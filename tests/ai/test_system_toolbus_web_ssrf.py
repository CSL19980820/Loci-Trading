"""web_fetch / web_search 的 SSRF 护栏回归。

web_fetch 注册为 ``write=False``：LLM 和只读子 Agent 不用 ExecutionGrant 就能
点名 URL。修之前只按字面主机名拦 localhost/127.0.0.1/::1/.local 四个写法，
httpx 还自带 follow_redirects——于是一个合法公网站点回一句
``302 Location: http://169.254.169.254/…`` 就能把全部检查绕过去。

全部用 httpx2.MockTransport + 假 DNS，不联网。
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

import httpx2
import pytest

from src.ai.application import system_toolbus_web as web

MODULE = "src.ai.application.system_toolbus_web"
PUBLIC_IP = "93.184.216.34"
PAGE = b"<html><head><title>Hi</title></head><body><p>hello world</p></body></html>"


class _Recorder:
    """记下 MockTransport 真正被要求发出的每一跳。"""

    def __init__(self, makers):
        self.makers = makers
        self.urls = []

    def __call__(self, request):
        self.urls.append(str(request.url))
        maker = self.makers[min(len(self.urls) - 1, len(self.makers) - 1)]
        return maker(request)

    @property
    def hosts(self):
        return [httpx2.URL(url).host for url in self.urls]


def _html(_request):
    return httpx2.Response(200, content=PAGE, headers={"content-type": "text/html"})


def _redirect_to(target):
    def _make(_request):
        return httpx2.Response(302, headers={"location": target})

    return _make


def _dns(ip):
    def _fake(host, port, *_args, **_kwargs):
        return [(2, 1, 6, "", (ip, port))]

    return _fake


def _call(tool, args, recorder, dns=None):
    client = httpx2.Client(
        transport=httpx2.MockTransport(recorder),
        timeout=web._TIMEOUT,
        follow_redirects=False,
    )
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}._client", return_value=client))
        if dns is not None:
            stack.enter_context(patch(f"{MODULE}.socket.getaddrinfo", _dns(dns)))
        return web.web_specs(None)[tool].handler(args)


def _fetch(url, recorder, dns=None, **extra):
    return _call("web_fetch", {"url": url, **extra}, recorder, dns=dns)


BLOCKED = [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://100.100.100.200/latest/meta-data/",
    "http://10.0.0.5/admin",
    "http://172.16.0.9/",
    "http://192.168.1.1/",
    "http://127.1/",
    "http://2130706433/",
    "http://0.0.0.0:8000/",
    "http://127.0.0.2:8080/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://localhost:9000/api",
    "http://nas.local/",
    "https://198.18.0.7/",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_intranet_and_metadata_targets_are_rejected(url):
    recorder = _Recorder([_html])
    result = _fetch(url, recorder)
    assert result["is_error"] is True
    assert "拒绝" in result["text"]
    assert recorder.urls == []


def test_public_literal_is_still_fetched():
    recorder = _Recorder([_html])
    result = _fetch(f"http://{PUBLIC_IP}/news", recorder)
    assert result["is_error"] is False
    assert result["structured"]["title"] == "Hi"
    assert "hello world" in result["structured"]["text"]
    assert recorder.hosts == [PUBLIC_IP]


def test_public_dns_name_is_still_fetched():
    recorder = _Recorder([_html])
    result = _fetch("https://example.com/a", recorder, dns=PUBLIC_IP)
    assert result["is_error"] is False
    assert recorder.hosts == ["example.com"]


def test_dns_name_resolving_into_metadata_range_is_rejected():
    recorder = _Recorder([_html])
    result = _fetch("https://looks-fine.example.com/", recorder, dns="169.254.169.254")
    assert result["is_error"] is True
    assert "拒绝" in result["text"]
    assert recorder.urls == []


def test_redirect_into_cloud_metadata_is_blocked():
    """本轮最要命的一条：只校验原始 URL 时，302 一跳就能拿到云凭据。"""
    meta = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
    recorder = _Recorder([_redirect_to(meta), _html])
    result = _fetch(f"http://{PUBLIC_IP}/start", recorder)
    assert result["is_error"] is True
    assert "拒绝" in result["text"]
    assert recorder.hosts == [PUBLIC_IP]
    assert "169.254" not in result["text"]


def test_redirect_into_private_lan_is_blocked():
    recorder = _Recorder([_redirect_to("http://192.168.31.7/router"), _html])
    result = _fetch(f"http://{PUBLIC_IP}/start", recorder)
    assert result["is_error"] is True
    assert recorder.hosts == [PUBLIC_IP]
    assert "192.168" not in result["text"]


def test_redirect_via_dns_name_into_intranet_is_blocked():
    recorder = _Recorder([_redirect_to("http://intranet.example.com/secret"), _html])
    result = _fetch(f"http://{PUBLIC_IP}/start", recorder, dns="10.1.2.3")
    assert result["is_error"] is True
    assert recorder.hosts == [PUBLIC_IP]


def test_redirect_to_public_target_still_followed():
    other = "http://93.184.216.35/final"
    recorder = _Recorder([_redirect_to(other), _html])
    result = _fetch(f"http://{PUBLIC_IP}/start", recorder)
    assert result["is_error"] is False
    assert recorder.urls == [f"http://{PUBLIC_IP}/start", other]


def test_redirect_hops_are_capped():
    recorder = _Recorder([_redirect_to(f"http://{PUBLIC_IP}/next")])
    result = _fetch(f"http://{PUBLIC_IP}/start", recorder)
    assert result["is_error"] is True
    assert "重定向" in result["text"]
    assert len(recorder.urls) == web._MAX_REDIRECTS + 1


def test_redirect_to_non_http_scheme_is_refused():
    recorder = _Recorder([_redirect_to("file:///etc/passwd"), _html])
    result = _fetch(f"http://{PUBLIC_IP}/start", recorder)
    assert result["is_error"] is True
    assert len(recorder.urls) == 1


def test_web_search_redirect_into_intranet_is_blocked():
    recorder = _Recorder([_redirect_to("http://192.168.31.7/router"), _html])
    result = _call("web_search", {"query": "涨停"}, recorder, dns=PUBLIC_IP)
    assert result["is_error"] is True
    assert "拒绝" in result["text"]
    assert recorder.hosts == ["html.duckduckgo.com"]


def test_proxy_fake_ip_allowed_for_dns_name_but_not_for_literal():
    """Clash/Surge Fake-IP：域名落到 198.18/15 是代理产物，拦了 web_search 全挂。"""
    allowed = _Recorder([_html])
    result = _fetch("https://example.com/", allowed, dns="198.18.0.7")
    assert result["is_error"] is False
    assert allowed.hosts == ["example.com"]

    literal = _Recorder([_html])
    refused = _fetch("https://198.18.0.7/", literal)
    assert refused["is_error"] is True
    assert literal.urls == []


def test_url_with_credentials_is_refused():
    recorder = _Recorder([_html])
    result = _fetch(f"http://user:pw@{PUBLIC_IP}/", recorder)
    assert result["is_error"] is True
    assert recorder.urls == []


def test_client_keeps_18s_timeout_and_disables_auto_redirect():
    client = web._client()
    try:
        assert client.timeout.read == 18.0
        assert client.timeout.connect == 18.0
        assert client.follow_redirects is False
        assert "LociAssistant" in client.headers["user-agent"]
    finally:
        client.close()


def test_non_text_content_type_still_refused():
    def _json(_request):
        return httpx2.Response(200, content=b"{}", headers={"content-type": "application/json"})

    recorder = _Recorder([_json])
    result = _fetch(f"http://{PUBLIC_IP}/data.json", recorder)
    assert result["is_error"] is True
    assert "不支持的内容类型" in result["text"]


def test_body_cap_still_truncates():
    def _big(_request):
        body = b"<html><body><p>" + b"x" * 3000 + b"</p></body></html>"
        return httpx2.Response(200, content=body, headers={"content-type": "text/html"})

    recorder = _Recorder([_big])
    result = _fetch(f"http://{PUBLIC_IP}/big", recorder, max_chars=500)
    assert result["is_error"] is False
    assert result["structured"]["truncated"] is True
    assert len(result["structured"]["text"]) == 500
