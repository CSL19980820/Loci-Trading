"""外网工具的专用代理开关(``LOCI_WEB_TOOL_PROXY``)。

为什么要单独一个开关、而不是复用全局 ``HTTP_PROXY``:同一个进程还要拉 akshare /
腾讯 / 新浪 / 通达信这些**国内**行情源,全局代理会把它们一起绕到境外出口——又慢
又容易直接断,而行情是这套系统的命根子。

生产实测(2026-08-26,容器内):直连 ``html.duckduckgo.com`` 报
``Network is unreachable``;经宿主 ``172.17.0.1:7890`` 380ms 拿到 HTTP 202。
没有这个开关,``web_search`` 在生产上永远不可用(用户看到的就是助手回
「外网调研暂时不可达」)。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.ai.application import system_toolbus_web as web


def _spy_client_kwargs() -> dict:
    """替换 httpx2.Client,只记录构造参数,不真的建连接。"""
    seen: dict = dict()

    def _spy(**kwargs):
        seen.update(kwargs)
        return object()

    with patch.object(web.httpx2, "Client", _spy):
        web._client()
    return seen


def test_web_tools_use_the_dedicated_proxy_when_configured(monkeypatch) -> None:
    """配了开关就必须走它。"""
    monkeypatch.setenv(web._PROXY_ENV, "http://172.17.0.1:7890")
    assert _spy_client_kwargs()["proxy"] == "http://172.17.0.1:7890"


def test_without_the_switch_behaviour_is_unchanged(monkeypatch) -> None:
    """没配开关时必须传 None,交回 httpx 的 trust_env。

    写死一个代理会把开发机现有的走法顶掉;写死 ``trust_env=False`` 又会让开发机
    原本能用的全局代理失效。两种都不行,所以是 None——这条钉的是「本改动对未
    配置的环境零影响」。
    """
    monkeypatch.delenv(web._PROXY_ENV, raising=False)
    assert _spy_client_kwargs()["proxy"] is None


def test_blank_switch_is_treated_as_unset(monkeypatch) -> None:
    """空串/纯空白当没配。``.env`` 里留个空值是常见写法,不能变成非法代理 URL。"""
    monkeypatch.setenv(web._PROXY_ENV, "   ")
    assert web._web_proxy() is None


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/",
        "http://127.0.0.1:8787/api/health",
    ],
)
def test_proxy_does_not_loosen_the_ssrf_guard(monkeypatch, url: str) -> None:
    """走代理**不放松** SSRF 护栏。

    很容易想当然地以为「既然出站交给代理了,本地就不用判了」——那样 ``web_fetch``
    会变成一台内网探测器,而且代理往往就蹲在内网里,离目标比调用方更近。护栏判
    的是**目标 URL 解析出来的地址**,与走不走代理无关。
    """
    monkeypatch.setenv(web._PROXY_ENV, "http://172.17.0.1:7890")
    with pytest.raises(web.WebAccessBlocked):
        web._guard_url(url)
