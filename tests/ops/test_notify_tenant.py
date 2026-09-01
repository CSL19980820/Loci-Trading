"""通知渠道的**租户隔离**：企微 webhook 绝不能被两个租户共用。

这一条坏起来是最难发现的一种：不报错、不刷红，只是 A 租户的告警发进了 B 的群，
或者 A 改了 webhook 顺手把 B 的改掉。发现它的唯一方式就是这个文件。

背景（也是这些用例存在的理由）：组合根把 ``PALACE_OPS_DB`` 读成字符串，一路
``main.py`` → ``legacy/quant_router.py`` → ``ops/api/settings.py`` 传给通知路由，
再进 ``OpsStore(ops_db)``。``paths._tenant_scoped`` 里「env 只对主租户生效」的护栏
只在**不传参**时起作用，显式传字符串把它整条绕过。生产暂未设该变量所以没引爆，
但 ``tests/conftest.py`` **全程设着**——于是在这个文件出现之前，没有任何用例能发现
回归。所以这里刻意**把 ops_db 传进去**（模拟运维填了 PALACE_OPS_DB），再断言
两个租户互相看不见。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.ops.application.notify_dispatch import dispatch_text
from src.ops.application.notify_registry import get_channel_config, reset_rate_limiter
from src.ops.infrastructure.store import OpsStore
from src.shared.tenancy import reset_current_tenant, set_current_tenant, tenant_scope

_ALICE = "t-alice"
_BOB = "t-bob"
_ALICE_HOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aaaaaaaa11112222"
_BOB_HOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bbbbbbbb33334444"


@pytest.fixture(autouse=True)
def _clean_rate_limiter() -> None:
    """限流表是进程级的，不清会让用例互相顶掉。"""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何真的出网都让用例失败。

    **记账 + teardown 断言**，不是当场抛就完事：通道契约是「吞掉一切异常返回
    False」，在 urlopen 里抛 AssertionError 会被通道自己接住翻译成一次「发送失败」，
    用例照样绿。朴素守卫对真实泄漏毫无反应——上一轮真有用例打到了 open.feishu.cn。
    """
    import smtplib
    import urllib.request

    leaked: list[str] = []

    def _boom(*_args: object, **_kwargs: object) -> None:
        leaked.append("network")
        raise AssertionError("用例试图真的出网：外部 HTTP/SMTP 必须 mock")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(smtplib, "SMTP", _boom)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _boom)
    yield
    assert not leaked, "用例试图真的出网：外部 HTTP/SMTP 必须 mock"


class _TenantHeaderMiddleware:
    """按 ``X-Loci-Tenant`` 头绑租户。

    与 ``src/app/tenant_middleware.py`` 同构（纯 ASGI，不是 ``BaseHTTPMiddleware``）：
    ContextVar 只在任务创建那一刻做快照，``BaseHTTPMiddleware`` 会把下游放进另一个
    任务里跑，绑定关系随 Starlette 版本漂。纯 ASGI 在同一个任务里 await 下游，
    同步路由经 ``run_in_threadpool`` 由 anyio 复制 context，读得到。

    这里不接 identity：本文件测的是「隔离有没有生效」，不是「怎么认人」。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or ()).get(b"x-loci-tenant", b"").decode() or None
        token = set_current_tenant(raw)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_tenant(token)


def _client(pinned_ops_db: Path):
    """**刻意**把 ops_db 钉进组合入口，模拟运维填了 PALACE_OPS_DB。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ops.api.settings import build_ops_settings_router

    app = FastAPI()
    app.include_router(
        build_ops_settings_router(
            write_dependency=lambda: None,
            ops_db=str(pinned_ops_db),
        )
    )
    app.add_middleware(_TenantHeaderMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def _put_hook(client: Any, tenant: str, url: str):
    return client.put(
        "/api/ops/settings/wecom",
        json={"url": url},
        headers={"X-Loci-Tenant": tenant},
    )


def _get_settings(client: Any, tenant: str) -> dict[str, Any]:
    response = client.get(
        "/api/ops/settings/wecom", headers={"X-Loci-Tenant": tenant}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


#  ---- HTTP：两个租户各配一个 webhook，互不可见 ------------------------------


def test_two_tenants_never_share_a_wecom_webhook(tmp_path: Path) -> None:
    """核心回归。挂掉 = A 的告警会发进 B 的群。"""
    pinned = tmp_path / "pinned-ops.db"
    with _client(pinned) as client:
        assert _put_hook(client, _ALICE, _ALICE_HOOK).status_code == 200
        assert _put_hook(client, _BOB, _BOB_HOOK).status_code == 200

        alice = _get_settings(client, _ALICE)
        bob = _get_settings(client, _BOB)

    assert alice["configured"] is True
    assert bob["configured"] is True
    #  只回显末 4 位，所以对拍掩码就够——同时也顺手守住「不回显完整 URL」。
    assert alice["url_masked"] != bob["url_masked"]
    assert alice["url_masked"].endswith("2222")
    assert bob["url_masked"].endswith("4444")


def test_each_tenant_writes_its_own_ops_db(tmp_path: Path) -> None:
    """隔离必须落到**文件**上，不只是读出来的值不同。"""
    pinned = tmp_path / "pinned-ops.db"
    with _client(pinned) as client:
        assert _put_hook(client, _ALICE, _ALICE_HOOK).status_code == 200

    with tenant_scope(_ALICE), OpsStore(None) as store:
        assert str(store.get_setting("wecom_webhook", {}).get("url")) == _ALICE_HOOK
        alice_db = Path(store.db_path)

    with tenant_scope(_BOB), OpsStore(None) as store:
        assert store.get_setting("wecom_webhook", {}) in ({}, None)
        bob_db = Path(store.db_path)

    assert alice_db != bob_db
    #  被钉进来的那个库**一个字节都不该被写**：通知支路已经不认它了。
    assert not pinned.exists() or pinned.stat().st_size == 0


def test_one_tenant_clearing_the_hook_does_not_mute_the_other(tmp_path: Path) -> None:
    """A 删自己的 webhook 不能顺手把 B 静音——静音是最难发现的故障。"""
    pinned = tmp_path / "pinned-ops.db"
    with _client(pinned) as client:
        _put_hook(client, _ALICE, _ALICE_HOOK)
        _put_hook(client, _BOB, _BOB_HOOK)
        assert _put_hook(client, _ALICE, "").status_code == 200

        assert _get_settings(client, _ALICE)["configured"] is False
        assert _get_settings(client, _BOB)["configured"] is True


def test_channel_registry_endpoint_is_tenant_scoped_too(tmp_path: Path) -> None:
    """新键 ``notify:wecom`` 那套（六通道名片）走的是同一个 ``_ops()``。"""
    pinned = tmp_path / "pinned-ops.db"
    with _client(pinned) as client:
        saved = client.put(
            "/api/ops/notify/channels/feishu",
            json={"url": "https://open.feishu.cn/open-apis/bot/v2/hook/alice1"},
            headers={"X-Loci-Tenant": _ALICE},
        )
        assert saved.status_code == 200 and saved.json()["configured"] is True

        cards = client.get(
            "/api/ops/notify/channels", headers={"X-Loci-Tenant": _BOB}
        ).json()["channels"]

    by_name = {row["name"]: row for row in cards}
    assert by_name["feishu"]["configured"] is False


#  ---- 限流不跨租户 -----------------------------------------------------------


def test_same_message_reaches_both_tenants(tmp_path: Path) -> None:
    """两个租户的同标题消息必须**都**真的发出去。

    限流键含租户（``notify_registry._allow``）。少了租户这一维，B 租户的告警会被
    A 租户 10 秒前那条同标题的消息顶掉，而且悄无声息。
    """
    sent_urls: list[str] = []

    def _fake_send(url: str, _content: str) -> dict[str, Any]:
        sent_urls.append(url)
        return {"errcode": 0}

    with tenant_scope(_ALICE), OpsStore(None) as store:
        store.set_setting("wecom_webhook", {"url": _ALICE_HOOK})
    with tenant_scope(_BOB), OpsStore(None) as store:
        store.set_setting("wecom_webhook", {"url": _BOB_HOOK})

    with patch("src.ops.application.notify_dispatch.send_wecom_text", _fake_send):
        with tenant_scope(_ALICE), OpsStore(None) as store:
            first = dispatch_text(store, title="盘中提醒", body="600519 触价")
        with tenant_scope(_BOB), OpsStore(None) as store:
            second = dispatch_text(store, title="盘中提醒", body="600519 触价")

    assert first["sent"] == ["wecom"]
    assert second["sent"] == ["wecom"], "B 租户被 A 租户的同名消息顶掉了"
    assert sent_urls == [_ALICE_HOOK, _BOB_HOOK]


def test_rate_limit_still_bites_inside_one_tenant(tmp_path: Path) -> None:
    """隔离不是放弃限流：同一个租户内 60s 里第二条同指纹仍然被压住。"""
    calls: list[str] = []

    def _fake_send(url: str, _content: str) -> dict[str, Any]:
        calls.append(url)
        return {"errcode": 0}

    with tenant_scope(_ALICE), OpsStore(None) as store:
        store.set_setting("wecom_webhook", {"url": _ALICE_HOOK})
        with patch("src.ops.application.notify_dispatch.send_wecom_text", _fake_send):
            first = dispatch_text(store, title="盘中提醒", body="600519 触价")
            second = dispatch_text(store, title="盘中提醒", body="600519 触价")

    assert first["sent"] == ["wecom"]
    assert second["sent"] == []
    assert second["skipped"] == "rate_limited"
    assert second["suppressed"] == ["wecom"]
    assert len(calls) == 1


def test_legacy_key_still_resolves_per_tenant(tmp_path: Path) -> None:
    """旧键 ``wecom_webhook`` 的回退**不许删**，而且必须也是按租户解析的。"""
    with tenant_scope(_BOB), OpsStore(None) as store:
        store.set_setting("wecom_webhook", {"url": _BOB_HOOK})
        assert get_channel_config(store, "wecom") == {"url": _BOB_HOOK}

    with tenant_scope(_ALICE), OpsStore(None) as store:
        assert get_channel_config(store, "wecom") == {}
