"""多通道告警（下半）：旧键兼容、邮件与站内信、社区订阅分发、HTTP 端点。

从 `test_notify_channels.py` 拆出——原文件 637 行，超了仓库 600 行/文件的硬上限。
注册表、加签对拍、失败隔离、限流与打码留在原文件。

夹具与桩点约定跟上半一致，尤其是 `_no_real_network`：外部 HTTP/SMTP 必须 mock，
漏网的出站会在 teardown 被记账并断言失败（通道自己吞异常，当场抛拦不住）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.ops.application.notify_registry import (
    describe_channel,
    dispatch,
    get_channel_config,
    reset_rate_limiter,
    save_channel_config,
)
from src.ops.domain.notify import NotifyMessage
from src.ops.infrastructure import notify_channels
from src.ops.infrastructure.notify_channels import (
    get_channel,
)
from src.ops.infrastructure.store import OpsStore

_WECOM_HOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef1234567890"
_DING_HOOK = "https://oapi.dingtalk.com/robot/send?access_token=deadbeefcafe"
_FEISHU_HOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/1a2b3c4d5e6f"


@pytest.fixture()
def store(tmp_path: Path):
    with OpsStore(tmp_path / "ops.db") as opened:
        yield opened


@pytest.fixture(autouse=True)
def _clean_rate_limiter() -> None:
    """限流表是进程级的，不清会让用例互相顶掉。"""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何真的出网都让用例失败。

    不是洁癖：本文件最初有一处 ``with patch(...)`` 缩进写歪，第二个断言掉到
    mock 作用域外面，用例真的打到了 open.feishu.cn，靠对端回 19001 才暴露。

    **为什么在 teardown 断言而不是当场抛**：通道的契约就是「吞掉一切异常返回
    False」（`_BaseChannel.send`），所以在 urlopen 里抛 AssertionError 会被
    通道自己接住、翻译成一次「发送失败」，用例照样绿。实测过：只抛不记的版本
    对真实泄漏毫无反应。所以这里记账 + 事后清算。
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


def _message(body: str = "正文") -> NotifyMessage:
    return NotifyMessage(title="标题", body=body, level="warn")



#  ---- 行为兼容：旧的 wecom_webhook 配置仍然生效 -----------------------------


def test_legacy_wecom_webhook_key_still_works(store: OpsStore) -> None:
    """只配过旧键 ``wecom_webhook`` 的部署，升级后必须照常出声。

    这条坏了是**静默**坏：告警不响，而「告警不响」本身没有告警。所以哪怕
    ``notify:wecom`` 这个新键将来成了唯一写入口，回退读也不许删。
    """
    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})

    assert get_channel_config(store, "wecom") == {"url": _WECOM_HOOK}
    assert describe_channel(store, "wecom")["configured"] is True

    with patch("src.ops.application.notify.send_wecom_text") as send:
        assert dispatch(store, _message(), channels=["wecom"]) == {"wecom": True}

    send.assert_called_once()
    assert send.call_args.args[0] == _WECOM_HOOK


def test_legacy_wecom_key_still_reaches_dispatch_text(store: OpsStore) -> None:
    """任务完成/失败与触价提醒都走 ``dispatch_text``；旧键部署必须一字不变地照发。"""
    from src.ops.application.notify_dispatch import dispatch_text

    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})

    with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
        outcome = dispatch_text(store, title="价格提醒", body="600519 触价")

    assert outcome["sent"] == ["wecom"]
    #  企微正文的「【标题】\n正文」拼法是既有契约，多通道改造不许动它。
    assert send.call_args.args[1] == "【价格提醒】\n600519 触价"


def test_new_key_takes_priority_over_the_legacy_one(store: OpsStore) -> None:
    """两个键都在时以新键为准，否则改了配置却发去老地址。"""
    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})
    save_channel_config(store, "wecom", {"url": _WECOM_HOOK + "NEW"})

    assert get_channel_config(store, "wecom")["url"] == _WECOM_HOOK + "NEW"


def test_dispatch_text_also_fans_out_to_the_new_channels(store: OpsStore) -> None:
    """接入点只有 dispatch_text 一处，所以两个既有调用点自动拿到多通道。"""
    from src.ops.application.notify_dispatch import dispatch_text

    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK})

    with (
        patch("src.ops.application.notify_dispatch.send_wecom_text"),
        patch.object(notify_channels, "_http_post_json", return_value={"errcode": 0}),
    ):
        outcome = dispatch_text(store, title="任务失败", body="日终同步 failed=3")

    assert sorted(outcome["sent"]) == ["dingtalk", "wecom"]


def test_wecom_is_not_double_sent_by_the_two_legs(store: OpsStore) -> None:
    """旧腿和注册表最终都调 send_wecom_text；企微必须只发一遍。"""
    from src.ops.application.notify_dispatch import dispatch_text

    save_channel_config(store, "wecom", {"url": _WECOM_HOOK})

    with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
        outcome = dispatch_text(store, title="标题", body="正文")

    assert send.call_count == 1
    assert outcome["sent"] == ["wecom"]


#  ---- 邮件 / 站内信 ---------------------------------------------------------


def test_email_channel_needs_both_smtp_env_and_recipients(monkeypatch, store: OpsStore) -> None:
    """收件人在通道配置里，SMTP 凭据在环境变量里——密码不进 ops.db。"""
    channel = get_channel("email")
    assert channel is not None

    monkeypatch.delenv("LOCI_SMTP_HOST", raising=False)
    assert channel.is_configured({"to": "ops@example.com"}) is False

    monkeypatch.setenv("LOCI_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LOCI_SMTP_FROM", "loci@example.com")
    assert channel.is_configured({"to": "ops@example.com"}) is True
    assert channel.is_configured({}) is False


def test_email_channel_sends_one_message_to_all_recipients(monkeypatch, store: OpsStore) -> None:
    monkeypatch.setenv("LOCI_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LOCI_SMTP_FROM", "loci@example.com")
    save_channel_config(store, "email", {"to": "a@example.com, b@example.com"})
    captured: list[Any] = []

    def fake_smtp(**kwargs: Any) -> None:
        captured.append(kwargs)

    with patch.object(notify_channels, "_smtp_send", side_effect=fake_smtp):
        assert dispatch(store, _message()) == {"email": True}

    mail = captured[0]["message"]
    assert mail["To"] == "a@example.com, b@example.com"
    assert "WARN" in mail["Subject"]


def test_inbox_channel_writes_identity_notifications(tmp_path: Path, store: OpsStore) -> None:
    """站内信落 identity.db，经 ``from src.identity import IdentityStore`` 包根导入。"""
    from src.identity import IdentityStore

    identity_db = tmp_path / "identity.db"
    save_channel_config(
        store,
        "inbox",
        {"user_ids": ["u-1", "u-2"], "identity_db": str(identity_db)},
    )

    assert dispatch(store, _message("站内信正文")) == {"inbox": True}

    with IdentityStore(identity_db) as identity:
        rows = identity.list_notifications("u-1")
        assert [row["title"] for row in rows] == ["标题"]
        assert identity.unread_count("u-2") == 1


#  ---- 社区订阅信号分发 -------------------------------------------------------


class _FakeCommunityStore:
    """鸭子类型替身：只实现 ops 侧真正用到的两个方法。"""

    def __init__(self, subscribers: dict[str, list[str]]) -> None:
        self._subscribers = subscribers

    def list_subscribers(self, publish_id: str) -> list[str]:
        return list(self._subscribers.get(publish_id, ()))

    def get_subscription(self, publish_id: str, user_id: str) -> dict[str, Any]:
        prefs = {"u-inapp": ["inapp"], "u-desktop": ["desktop"], "u-both": ["inapp", "email"]}
        return {"notify_channels": prefs.get(user_id, ["inapp"])}


def test_subscription_signal_reaches_inapp_subscribers(tmp_path: Path, store: OpsStore) -> None:
    """收件人由本次调用决定（这条策略的订阅者），不是设置页里的固定名单。"""
    from src.ops.application.notify_subscribers import dispatch_subscription_signal

    identity_db = tmp_path / "identity.db"
    community = _FakeCommunityStore({"pub-1": ["u-inapp", "u-desktop"]})

    outcome = dispatch_subscription_signal(
        store,
        community,
        "pub-1",
        title="信号·三源尾盘",
        body="600519 触发买点",
        identity_db=str(identity_db),
    )

    assert outcome["sent"] == ["inbox"]
    assert outcome["subscribers"] == 1
    #  桌面推送本仓没有传输实现；照实记下来，不假装发过。
    assert outcome["skipped"] == {"desktop": ["u-desktop"]}
    assert outcome["notice"] == "只推信号，不自动下单"

    from src.identity import IdentityStore

    with IdentityStore(identity_db) as identity:
        assert identity.unread_count("u-inapp") == 1
        assert identity.unread_count("u-desktop") == 0


def test_subscription_signal_with_no_subscribers_sends_nothing(store: OpsStore) -> None:
    from src.ops.application.notify_subscribers import dispatch_subscription_signal

    outcome = dispatch_subscription_signal(
        store, _FakeCommunityStore({}), "pub-empty", title="t", body="b"
    )

    assert outcome["subscribers"] == 0
    assert outcome["results"] == {}


def test_two_different_signals_with_identical_bodies_both_get_through(
    tmp_path: Path, store: OpsStore
) -> None:
    """同一作者两条不同策略，模板化正文恰好相同——第二条**必须**也发出去。

    通用限流的指纹是 ``title\x1flevel\x1fbody``，**不含 tags**，而 ``publish_id``
    恰恰只活在 tags 里。靠指纹去重的话，第二条会在 60s 内被静默吃掉：用户永远
    收不到那条信号，日志里也没有一句「我压了它」。
    """
    from src.ops.application.notify_subscribers import dispatch_subscription_signal

    identity_db = tmp_path / "identity.db"
    community = _FakeCommunityStore({"pub-a": ["u-inapp"], "pub-b": ["u-inapp"]})

    kwargs = {"title": "信号·尾盘", "body": "600519 触发买点", "trade_date": "2026-08-27"}
    first = dispatch_subscription_signal(
        store, community, "pub-a", identity_db=str(identity_db), **kwargs
    )
    second = dispatch_subscription_signal(
        store, community, "pub-b", identity_db=str(identity_db), **kwargs
    )

    assert first["sent"] == ["inbox"]
    assert second["sent"] == ["inbox"], "第二条策略的信号被同正文的第一条顶掉了"
    assert second["deduped"] is False

    from src.identity import IdentityStore

    with IdentityStore(identity_db) as identity:
        assert identity.unread_count("u-inapp") == 2


def test_republishing_the_same_signal_the_same_day_is_deduped(
    tmp_path: Path, store: OpsStore
) -> None:
    """``put_broadcast`` 按 ``(publish_id, trade_date)`` upsert，同一天重发很常见。

    改个价位再发一次不该把订阅者再轰一遍。去重按业务唯一键，不按消息内容——
    正文改了也算同一条信号。
    """
    from src.ops.application.notify_subscribers import dispatch_subscription_signal

    identity_db = tmp_path / "identity.db"
    community = _FakeCommunityStore({"pub-a": ["u-inapp"]})

    first = dispatch_subscription_signal(
        store,
        community,
        "pub-a",
        title="信号·尾盘",
        body="600519 触发买点",
        trade_date="2026-08-27",
        identity_db=str(identity_db),
    )
    second = dispatch_subscription_signal(
        store,
        community,
        "pub-a",
        title="信号·尾盘",
        body="600519 触发买点（改价 1720）",
        trade_date="2026-08-27",
        identity_db=str(identity_db),
    )

    assert first["sent"] == ["inbox"]
    assert second["sent"] == []
    assert second["deduped"] is True

    from src.identity import IdentityStore

    with IdentityStore(identity_db) as identity:
        assert identity.unread_count("u-inapp") == 1


def test_a_new_trade_date_reopens_the_signal(tmp_path: Path, store: OpsStore) -> None:
    """换一天再发是**新**信号。去重键含交易日，不然策略只能出一次声。"""
    from src.ops.application.notify_subscribers import dispatch_subscription_signal

    identity_db = tmp_path / "identity.db"
    community = _FakeCommunityStore({"pub-a": ["u-inapp"]})

    for day in ("2026-08-27", "2026-08-28"):
        outcome = dispatch_subscription_signal(
            store,
            community,
            "pub-a",
            title="信号·尾盘",
            body="600519 触发买点",
            trade_date=day,
            identity_db=str(identity_db),
        )
        assert outcome["sent"] == ["inbox"], day

    from src.identity import IdentityStore

    with IdentityStore(identity_db) as identity:
        assert identity.unread_count("u-inapp") == 2


def test_signal_dedup_is_per_tenant(tmp_path: Path, store: OpsStore) -> None:
    """A 租户推过的信号不能顶掉 B 租户的同一条。"""
    from src.ops.application.notify_subscribers import dispatch_subscription_signal
    from src.shared.tenancy import tenant_scope

    identity_db = tmp_path / "identity.db"
    community = _FakeCommunityStore({"pub-a": ["u-inapp"]})
    kwargs = {
        "title": "信号·尾盘",
        "body": "600519 触发买点",
        "trade_date": "2026-08-27",
        "identity_db": str(identity_db),
    }

    with tenant_scope("t-alice"):
        first = dispatch_subscription_signal(store, community, "pub-a", **kwargs)
    with tenant_scope("t-bob"):
        second = dispatch_subscription_signal(store, community, "pub-a", **kwargs)

    assert first["sent"] == ["inbox"]
    assert second["sent"] == ["inbox"], "B 租户被 A 租户的同一条信号顶掉了"


#  ---- HTTP ------------------------------------------------------------------


def _client(ops_db: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ops.api.notifications import build_notification_settings_router

    app = FastAPI()
    app.include_router(
        build_notification_settings_router(write_dependency=lambda: None, ops_db=str(ops_db))
    )
    return TestClient(app, raise_server_exceptions=False)


def test_http_lists_channels_without_leaking_secrets(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as seed:
        save_channel_config(seed, "dingtalk", {"url": _DING_HOOK, "secret": "SECe1f2a3b4c5d6"})

    with _client(ops_db) as client:
        response = client.get("/api/ops/notify/channels")

    assert response.status_code == 200
    body = response.text
    assert "deadbeefcafe" not in body
    assert "SECe1f2a3b4c5d6" not in body
    names = [row["name"] for row in response.json()["channels"]]
    assert names == ["wecom", "dingtalk", "feishu", "webhook", "email", "inbox"]


def test_http_put_saves_and_delete_clears_a_channel(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with _client(ops_db) as client:
        saved = client.put("/api/ops/notify/channels/feishu", json={"url": _FEISHU_HOOK})
        assert saved.status_code == 200
        assert saved.json()["configured"] is True

        cleared = client.put("/api/ops/notify/channels/feishu", json={})
        assert cleared.json()["configured"] is False

    with OpsStore(ops_db) as check:
        assert get_channel_config(check, "feishu") == {}


def test_http_rejects_an_unknown_channel_name(tmp_path: Path) -> None:
    with _client(tmp_path / "ops.db") as client:
        response = client.put("/api/ops/notify/channels/telegram", json={"url": "x"})

    assert response.status_code == 422
    assert "telegram" in response.json()["detail"]


def test_http_test_endpoint_reports_failure_as_422(tmp_path: Path) -> None:
    """通道契约是吞异常返回 False，所以 HTTP 层要把 False 翻译成 4xx。"""
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as seed:
        save_channel_config(seed, "feishu", {"url": _FEISHU_HOOK})

    with patch.object(notify_channels, "_http_post_json", side_effect=TimeoutError("timed out")):
        with _client(ops_db) as client:
            response = client.post("/api/ops/notify/channels/feishu/test")

    assert response.status_code == 422


def test_http_test_endpoint_returns_ok_on_success(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as seed:
        save_channel_config(seed, "feishu", {"url": _FEISHU_HOOK})

    with patch.object(notify_channels, "_http_post_json", return_value={"code": 0}):
        with _client(ops_db) as client:
            response = client.post("/api/ops/notify/channels/feishu/test")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "channel": "feishu"}
