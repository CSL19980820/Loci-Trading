"""多通道告警：注册表、加签对拍、失败隔离、限流去重、secret 不回显。

外部 HTTP 一律 mock（`_http_post_json` / `send_wecom_text` / `_smtp_send`
三个桩点），照 `src/AGENTS.md` 第 7 节的硬要求，任何用例都不真的出网。

重点守的几条，都是「坏了不会有人立刻发现」的那种：

- **旧键回退**：只配过 `wecom_webhook` 的老部署升级后必须照常出声。这条坏了
是**静默**坏——告警不响，而「告警不响」本身没有告警。
- **单通道失败隔离**：一个通道挂掉不能带走同批的其他通道，更不能把调用它的
  任务一起拖死。
- **secret 不回显**：webhook URL 的 key 段就是凭据本身，回显完整 URL 等于
  把群机器人送人。
"""
from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.ops.application import notify_registry
from src.ops.application.notify_send_queue import reset_rate_limits
from src.ops.application.notify_registry import (
    NotifyChannelError,
    describe_channel,
    dispatch,
    dispatch_report,
    get_channel_config,
    list_channels,
    mask_secret,
    reset_rate_limiter,
    save_channel_config,
    # 必须改名导入：pytest 会把任何叫 test_* 的可调用当成用例收集，
    # 直接 `import test_channel` 会让它以「fixture 'name' not found」报错。
    test_channel as send_test_message,
)
from src.ops.domain.notify import NotifyMessage
from src.ops.infrastructure import notify_channels
from src.ops.infrastructure.notify_channels import (
    channel_names,
    dingtalk_signature,
    feishu_signature,
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
    """限流表与令牌桶都是进程级的，不清会让用例互相顶掉。

    ``tests/ops/conftest.py`` 已经全局清一遍；这里再写一次是为了让本文件单跑时
    也自洽——「20 条/分钟」那两条用例数的是**绝对条数**，被上一个用例先花掉几个
    令牌就会莫名其妙地红。
    """
    reset_rate_limiter()
    reset_rate_limits()
    yield
    reset_rate_limiter()
    reset_rate_limits()


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


def _fake_urlopen(payload: dict[str, Any]):
    """最小可用的 urlopen 替身：只为把一份 JSON 塞回 ``notify._post``。

    注意 autouse 的 ``_no_real_network`` 已经把 ``urlopen`` 换成记账 + 抛错；
    这里用 ``patch.object`` 在更内层临时盖住它，退出时自动恢复成守卫版本。
    """
    import json
    from contextlib import contextmanager

    body = json.dumps(payload).encode("utf-8")

    @contextmanager
    def _open(_request: Any, timeout: float = 0):  # noqa: ARG001
        yield type("_Resp", (), {"read": staticmethod(lambda: body)})()

    return _open


# ---- 注册表 ---------------------------------------------------------------


def test_registry_holds_exactly_the_six_channels() -> None:
    """加通道只该改注册表一处；顺序即前端展示顺序，企微在前。"""
    assert channel_names() == ["wecom", "dingtalk", "feishu", "webhook", "email", "inbox"]
    for name in channel_names():
        channel = get_channel(name)
        assert channel is not None
        assert channel.name == name
    assert channel.label, f"{name} 缺中文标签"


def test_registry_lookup_is_case_insensitive_and_misses_are_none() -> None:
    assert get_channel("WeCom") is get_channel("wecom")
    assert get_channel("  dingtalk  ") is get_channel("dingtalk")
    assert get_channel("telegram") is None


def test_unknown_channel_raises_instead_of_silently_doing_nothing(store: OpsStore) -> None:
    """打错通道名要炸；静默无操作会让人以为配好了。"""
    with pytest.raises(NotifyChannelError):
        get_channel_config(store, "telegram")
    with pytest.raises(NotifyChannelError):
        save_channel_config(store, "telegram", {"url": "x"})
    with pytest.raises(NotifyChannelError):
        dispatch(store, _message(), channels=["telegram"])


def test_every_channel_satisfies_the_domain_protocol() -> None:
    """域层的 NotifyChannel 是 runtime_checkable，注册表必须真的符合它。"""
    from src.ops.domain.notify import NotifyChannel

    for channel in (get_channel(name) for name in channel_names()):
        assert isinstance(channel, NotifyChannel)


# ---- 加签（固定时间戳对拍） -------------------------------------------------


def test_dingtalk_signature_matches_pinned_vector() -> None:
    """钉钉加签：HMAC-SHA256(secret, f"{ts}\\n{secret}") → base64 → urlencode。

    期望值由官方算法独立算出后钉死。改了这里就是改了协议，不是改了实现。
    """
    signature = dingtalk_signature("SECe1f2a3b4c5d6", 1735689600000)

    assert signature == "zIW%2B46MSulioclbD%2FbdecDGOPkHHWIQDIk1zSoCgojo%3D"
    # base64 的 + / = 必须已被 urlencode，否则进 query 会被对端截断。
    assert "+" not in signature and "/" not in signature


def test_feishu_signature_is_not_the_dingtalk_one() -> None:
    """飞书拿 f"{ts}\\n{secret}" 当**密钥**对**空串**签；照抄钉钉会一直 401。"""
    assert feishu_signature("SECe1f2a3b4c5d6", 1735689600) == "9eU+yHQ8PvULVe0RqXxY5zuZYhSdsLdV8hVBQs7+j20="
    assert feishu_signature("SECe1f2a3b4c5d6", 1735689600) != dingtalk_signature(
        "SECe1f2a3b4c5d6", 1735689600
    )


def test_dingtalk_signs_the_request_when_secret_is_configured(store: OpsStore) -> None:
    """配了 secret 就必须带 timestamp+sign，且用的是**发送时刻**的时间戳。"""
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK, "secret": "SECe1f2a3b4c5d6"})
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(url: str, payload: Any, *, headers: Any = None) -> dict[str, Any]:
        calls.append((url, dict(payload)))
        return {"errcode": 0}

    with (
    patch.object(notify_channels, "_http_post_json", side_effect=fake_post),
        patch.object(notify_channels.time, "time", return_value=1735689600.0),
    ):
        assert dispatch(store, _message()) == {"dingtalk": True}

    url, payload = calls[0]
    assert "timestamp=1735689600000" in url
    assert "sign=zIW%2B46MSulioclbD%2FbdecDGOPkHHWIQDIk1zSoCgojo%3D" in url
    assert payload["msgtype"] == "text"


def test_dingtalk_without_secret_sends_a_bare_url(store: OpsStore) -> None:
    """没配 secret 就不该凭空加签名参数。"""
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK})
    calls: list[str] = []

    def fake_post(url: str, payload: Any, *, headers: Any = None) -> dict[str, Any]:
        calls.append(url)
        return {"errcode": 0}

    with patch.object(notify_channels, "_http_post_json", side_effect=fake_post):
        dispatch(store, _message())

    assert calls == [_DING_HOOK]


# ---- 未配置的通道不发 -------------------------------------------------------


def test_unconfigured_channels_are_never_contacted(store: OpsStore) -> None:
    """一个通道都没配 = 一次出站都不该发生，而且不许抛。"""
    with patch.object(notify_channels, "_http_post_json") as post:
        report = dispatch_report(store, _message())

    post.assert_not_called()
    assert report["results"] == {}
    assert sorted(report["unconfigured"]) == sorted(channel_names())


def test_only_configured_channels_are_dispatched(store: OpsStore) -> None:
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})

    with patch.object(notify_channels, "_http_post_json", return_value={"code": 0}) as post:
        results = dispatch(store, _message())

    assert results == {"feishu": True}
    assert post.call_count == 1


def test_clearing_a_config_stops_that_channel(store: OpsStore) -> None:
    """空配置等于停用：删掉后不能还在偷偷发。"""
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})
    card = save_channel_config(store, "feishu", {})
    assert card["configured"] is False
    with patch.object(notify_channels, "_http_post_json") as post:
        assert dispatch(store, _message()) == {}
    post.assert_not_called()


# ---- 单通道失败不影响其他 ---------------------------------------------------


def test_one_dead_channel_does_not_take_down_the_others(store: OpsStore) -> None:
    """钉钉炸了，飞书和通用 Webhook 照发；调用方拿到逐通道结果而不是异常。"""
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK})
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})
    save_channel_config(store, "webhook", {"url": "https://ops.example.com/hook"})

    def flaky(url: str, payload: Any, *, headers: Any = None) -> dict[str, Any]:
        if "dingtalk" in url:
            raise TimeoutError("timed out")
        return {"code": 0}

    with patch.object(notify_channels, "_http_post_json", side_effect=flaky):
        results = dispatch(store, _message())

    assert results == {"dingtalk": False, "feishu": True, "webhook": True}


def test_a_channel_never_raises_out_of_send(store: OpsStore) -> None:
    """通道契约：失败返回 False，绝不抛——推送不能带死调用它的任务。"""
    channel = get_channel("webhook")
    assert channel is not None

    with patch.object(notify_channels, "_http_post_json", side_effect=RuntimeError("boom")):
        assert channel.send(_message(), {"url": "https://ops.example.com/hook"}) is False


def test_business_error_code_counts_as_failure_not_success(store: OpsStore) -> None:
    """HTTP 200 但 errcode!=0 是失败。只看 HTTP 状态会把丢掉的消息记成已送达。"""
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK})

    with patch.object(
        notify_channels, "_http_post_json", return_value={"errcode": 310000, "errmsg": "keywords not in content"}
    ):
        assert dispatch(store, _message()) == {"dingtalk": False}


# ---- 限流去重 ---------------------------------------------------------------


def test_same_message_is_not_resent_within_the_window(store: OpsStore) -> None:
    """任务重试风暴：同一条告警 60s 内只出声一次。"""
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})

    with patch.object(notify_channels, "_http_post_json", return_value={"code": 0}) as post:
        first = dispatch_report(store, _message("同一条"))
        second = dispatch_report(store, _message("同一条"))

    assert post.call_count == 1
    assert first["sent"] == ["feishu"]
    assert second["sent"] == []
    assert second["suppressed"] == ["feishu"]


def test_a_different_message_still_gets_through(store: OpsStore) -> None:
    """限流按指纹，不是按通道——别把不同的告警一起憋住。"""
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})

    with patch.object(notify_channels, "_http_post_json", return_value={"code": 0}) as post:
        dispatch(store, _message("第一条"))
        dispatch(store, _message("第二条"))

    assert post.call_count == 2


def test_rate_limit_window_expires(store: OpsStore) -> None:
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})
    clock = {"now": 1_000.0}

    with (
        patch.object(notify_channels, "_http_post_json", return_value={"code": 0}) as post,
        patch.object(notify_registry.time, "time", lambda: clock["now"]),
    ):
        dispatch(store, _message("同一条"))
        clock["now"] += notify_registry.RATE_LIMIT_SECONDS + 1
        dispatch(store, _message("同一条"))

    assert post.call_count == 2


def test_link_is_excluded_from_the_fingerprint(store: OpsStore) -> None:
    """重试生成的链接带不同 run_id；算进指纹等于限流白做。"""
    first = NotifyMessage(title="t", body="b", link="https://x/run/1")
    second = NotifyMessage(title="t", body="b", link="https://x/run/2")

    assert first.fingerprint() == second.fingerprint()


def test_manual_test_bypasses_the_rate_limiter(store: OpsStore) -> None:
    """连点两次「测试」必须两次都真的发，否则用户以为通道坏了。"""
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})

    with patch.object(notify_channels, "_http_post_json", return_value={"code": 0}) as post:
        assert send_test_message(store, "feishu") is True
        assert send_test_message(store, "feishu") is True

    assert post.call_count == 2


# ---- secret 不回显 ----------------------------------------------------------


def test_mask_secret_keeps_only_the_last_six() -> None:
    assert mask_secret("abcdef1234567890") == "…567890"
    assert mask_secret("short") == "*****"
    assert mask_secret("") == ""


def test_listing_channels_never_echoes_a_full_webhook_or_secret(store: OpsStore) -> None:
    """回显完整 URL = 把群机器人送人；key 段本身就是凭据。"""
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK, "secret": "SECe1f2a3b4c5d6"})

    card = next(row for row in list_channels(store) if row["name"] == "dingtalk")
    blob = repr(card)

    assert card["configured"] is True
    assert _DING_HOOK not in blob
    assert "deadbeefcafe" not in blob
    assert "SECe1f2a3b4c5d6" not in blob
    assert card["config"]["url"] == "…efcafe"
    assert card["config"]["secret"] == "…b4c5d6"


def test_webhook_header_values_are_masked_too(store: OpsStore) -> None:
    """headers 里常放 Authorization；键名可以给，值不行。"""
    save_channel_config(
        store,
        "webhook",
        {"url": "https://ops.example.com/hook", "headers": {"Authorization": "Bearer supersecrettoken"}},
    )

    card = describe_channel(store, "webhook")

    assert "supersecrettoken" not in repr(card)
    assert "Authorization" in card["config"]["headers"]


def test_saving_still_stores_the_real_value(store: OpsStore) -> None:
    """打码只发生在**回显**路径上；库里必须是能用的真值，否则第二次就发不出去。"""
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK, "secret": "SECe1f2a3b4c5d6"})

    assert get_channel_config(store, "dingtalk") == {
        "url": _DING_HOOK,
        "secret": "SECe1f2a3b4c5d6",
    }


#  ---- 企微旧腿也过限流 -------------------------------------------------------
#
#  这一节守的是「告警刷屏 = 告警失效」。旧腿（wecom/bark）曾经直接 send、从不问
#  限流器，而 `run_job` 的**失败分支**也推、且失败路径没有 `wecom_push_mark` 那种
#  按日去重：一个 `*/5 9-14` 的 alert_scan 持续失败就是全天 60+ 条企微。


def test_the_wecom_leg_goes_through_the_rate_limiter(store: OpsStore) -> None:
    """同一条告警 60s 内只出一次声。旧腿以前完全不问这一句。"""
    from src.ops.application.notify_dispatch import dispatch_text

    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})

    with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
        first = dispatch_text(store, title="任务失败", body="alert_scan 连续失败")
        second = dispatch_text(store, title="任务失败", body="alert_scan 连续失败")

    assert first["sent"] == ["wecom"]
    assert send.call_count == 1
    #  「刻意没发」必须与「发失败」分得开，否则运维页会满屏假故障。
    assert second["sent"] == []
    assert second["skipped"] == "rate_limited"
    assert second["suppressed"] == ["wecom"]
    assert "errors" not in second


def test_a_different_alert_still_gets_through_the_wecom_leg(store: OpsStore) -> None:
    """限流按指纹，不是「一分钟只准发一条」——别把不同的告警一起憋住。"""
    from src.ops.application.notify_dispatch import dispatch_text

    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})

    with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
        dispatch_text(store, title="任务失败", body="alert_scan 失败")
        outcome = dispatch_text(store, title="任务失败", body="日终同步 failed=3")

    assert outcome["sent"] == ["wecom"]
    assert send.call_count == 2


def test_manual_notify_test_bypasses_the_wecom_rate_limiter(store: OpsStore) -> None:
    """连点两次「测试」必须两次都真的发，否则用户以为通道坏了。"""
    from src.ops.application.notify_dispatch import dispatch_text

    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})

    with patch("src.ops.application.notify_dispatch.send_wecom_text") as send:
        for _ in range(2):
            outcome = dispatch_text(
                store,
                title="Loci 连通测试",
                body="通知分发已接通",
                bypass_rate_limit=True,
            )
            assert outcome["sent"] == ["wecom"]

    assert send.call_count == 2


def test_the_two_legs_share_one_fingerprint_ledger(store: OpsStore) -> None:
    """企微被压住时，钉钉不该借着「各算各的」再冒出来一条。"""
    from src.ops.application.notify_dispatch import dispatch_text

    store.set_setting("wecom_webhook", {"url": _WECOM_HOOK})
    save_channel_config(store, "dingtalk", {"url": _DING_HOOK})

    with (
        patch("src.ops.application.notify_dispatch.send_wecom_text"),
        patch.object(notify_channels, "_http_post_json", return_value={"errcode": 0}) as post,
    ):
        first = dispatch_text(store, title="任务失败", body="同一条")
        second = dispatch_text(store, title="任务失败", body="同一条")

    assert sorted(first["sent"]) == ["dingtalk", "wecom"]
    assert second["sent"] == []
    assert sorted(second["suppressed"]) == ["dingtalk", "wecom"]
    assert post.call_count == 1


def test_a_broken_webhook_config_still_reports_an_error(store: OpsStore) -> None:
    """闸门在 URL 解析**之后**：配置本身坏掉要报错，不能被限流盖成「已跳过」。"""
    from src.ops.application.notify_dispatch import dispatch_text

    outcome = dispatch_text(store, title="任务失败", body="正文")

    assert outcome["sent"] == []
    assert outcome["suppressed"] == []
    assert "没有可用的通知渠道" in outcome["error"]


#  ---- 45009：不可重试 --------------------------------------------------------


def test_45009_maps_to_a_non_retryable_error() -> None:
    """企微的 45009 是「这一分钟满了」。当普通失败再打 2 次是火上浇油。"""
    import urllib.request

    from src.ops.application.notify import NotifyError, NotifyNotRetryable, _post
    from src.ops.application.notify_send_queue import NonRetryableSendError

    with patch.object(urllib.request, "urlopen", _fake_urlopen({"errcode": 45009, "errmsg": "freq"})):
        with pytest.raises(NotifyNotRetryable) as caught:
            _post(_WECOM_HOOK, b"{}")

    #  仍是 NotifyError 子类：所有 `except NotifyError` 的调用点一行都不用改。
    assert isinstance(caught.value, NotifyError)
    assert isinstance(caught.value, NonRetryableSendError)


def test_a_transient_errcode_stays_retryable() -> None:
    """表外的错误码保持可重试：把「抖了一下」判成永久失败等于静音。"""
    import urllib.request

    from src.ops.application.notify import NotifyError, NotifyNotRetryable, _post

    with patch.object(urllib.request, "urlopen", _fake_urlopen({"errcode": -1, "errmsg": "busy"})):
        with pytest.raises(NotifyError) as caught:
            _post(_WECOM_HOOK, b"{}")

    assert not isinstance(caught.value, NotifyNotRetryable)


def test_the_queue_stops_retrying_a_45009(monkeypatch: pytest.MonkeyPatch) -> None:
    """出站队列见到不可重试的异常就 break——**只打一次**。"""
    from src.ops.application import notify_send_queue
    from src.ops.application.notify import NotifyNotRetryable, send_wecom_text

    calls = {"n": 0}

    def _always_45009(_url: str, _body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        raise NotifyNotRetryable("企微错误 45009：freq out of limit")

    monkeypatch.setattr(notify_send_queue.time, "sleep", lambda _s: None)
    with patch("src.ops.application.notify._post", side_effect=_always_45009):
        with pytest.raises(NotifyNotRetryable):
            send_wecom_text(_WECOM_HOOK, "nope")

    assert calls["n"] == 1, "45009 被当成普通失败又打了两次"


def test_an_ordinary_failure_is_still_retried_three_times(monkeypatch: pytest.MonkeyPatch) -> None:
    """别把不可重试的口子开太大：普通失败的 3 次重试是既有契约。"""
    from src.ops.application import notify_send_queue
    from src.ops.application.notify import NotifyError, send_wecom_text

    calls = {"n": 0}

    def _flaky(_url: str, _body: bytes) -> dict[str, Any]:
        calls["n"] += 1
        raise NotifyError("timed out")

    monkeypatch.setattr(notify_send_queue.time, "sleep", lambda _s: None)
    with patch("src.ops.application.notify._post", side_effect=_flaky):
        with pytest.raises(NotifyError):
            send_wecom_text(_WECOM_HOOK, "nope")

    assert calls["n"] == 3


#  ---- 20 条/分钟令牌桶 -------------------------------------------------------


def test_the_token_bucket_throttles_at_twenty_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方口径：每个 webhook key 20 条/分钟。第 21 条排队等，**不丢**。"""
    from src.ops.application import notify_send_queue
    from src.ops.application.notify import send_wecom_text

    slept: list[float] = []
    monkeypatch.setattr(notify_send_queue.time, "sleep", lambda secs: slept.append(secs))

    with patch("src.ops.application.notify._post", return_value={"errcode": 0}) as post:
        for i in range(notify_send_queue.RATE_LIMIT_PER_MINUTE):
            send_wecom_text(_WECOM_HOOK, f"m{i}")
        assert not slept, "桶还没空就开始等，节流窗口算错了"
        send_wecom_text(_WECOM_HOOK, "overflow")

    #  第 21 条：等一个令牌的补充时间（60s / 20 = 3s），然后照发——排队不丢。
    assert len(slept) == 1
    assert 2.5 <= slept[0] <= 3.5
    assert post.call_count == notify_send_queue.RATE_LIMIT_PER_MINUTE + 1


def test_the_bucket_is_per_webhook_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """限的是 key，不是进程：打满一个机器人不该连累另一个。"""
    from src.ops.application import notify_send_queue
    from src.ops.application.notify import send_wecom_text

    other = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=zzzzzzzz99998888"
    slept: list[float] = []
    monkeypatch.setattr(notify_send_queue.time, "sleep", lambda secs: slept.append(secs))

    with patch("src.ops.application.notify._post", return_value={"errcode": 0}):
        for i in range(notify_send_queue.RATE_LIMIT_PER_MINUTE):
            send_wecom_text(_WECOM_HOOK, f"m{i}")
        send_wecom_text(other, "另一个机器人")

    assert not slept


#  ---- run_serialized 不挂死 --------------------------------------------------


def test_run_serialized_times_out_instead_of_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    """工人线程没了，等待方也必须能回来。

    真实路径：工人因不可捕获错误退出，``finally`` 把 ``_worker_started`` 置回 False
    （下次能重启），**但已经在队列里等的 item 永远等不到 ``done.set()``**。无超时的
    ``wait()`` 会把调用线程永久挂死——而那很可能是调度线程。
    """
    from src.ops.application import notify_send_queue

    monkeypatch.setattr(notify_send_queue, "SEND_WAIT_TIMEOUT_SEC", 0.2)
    #  模拟「工人已经死了/起不来」：换一条没人消费的队列 + 不许起新工人。
    #  只 patch ``_ensure_worker`` 是不够的——别的用例可能已经把工人拉起来了，
    #  它会照常把这条消息处理掉，用例就测了个寂寞。
    monkeypatch.setattr(notify_send_queue, "_queue", queue.Queue())
    monkeypatch.setattr(notify_send_queue, "_ensure_worker", lambda: None)

    started = time.monotonic()
    with pytest.raises(notify_send_queue.SendQueueTimeout):
        notify_send_queue.run_serialized(lambda: "never", rate_key=None)
    waited = time.monotonic() - started

    assert waited < 5, "超时没生效，调用线程被挂住了"


def test_an_abandoned_item_is_dropped_not_sent_late() -> None:
    """调用方已经放弃了，几分钟后再把那条告警发出去只会让人更困惑。"""
    from src.ops.application import notify_send_queue

    fired: list[str] = []
    item = notify_send_queue._SendItem(
        fn=lambda: fired.append("late"),
        deadline=time.monotonic() - 1.0,
    )
    #  直接喂给工人循环的那一段判断：过期的 item 不执行，只记账。
    notify_send_queue._queue.put(item)
    notify_send_queue._ensure_worker()
    assert item.done.wait(5.0), "工人没处理这条已过期的消息"
    assert fired == []
    assert isinstance(item.error, notify_send_queue.SendQueueTimeout)


#  ---- 线程池带着租户上下文 ---------------------------------------------------


def test_channels_run_with_the_caller_tenant_bound(store: OpsStore) -> None:
    """``ThreadPoolExecutor.submit`` 不复制 Context；必须走 ``submit_with_tenant``。

    今天六个通道都不读租户上下文，所以「没泄漏」纯属巧合。这条用例把不变量钉住：
    有人给 inbox 通道加一句「按当前租户解析 identity.db」时，回归会在这里响。
    """
    from src.shared.tenancy import current_tenant, tenant_scope

    seen: list[str] = []
    channel = get_channel("feishu")
    save_channel_config(store, "feishu", {"url": _FEISHU_HOOK})

    def _record(_message: Any, _config: Any) -> bool:
        seen.append(current_tenant())
        return True

    with patch.object(channel, "send", _record), tenant_scope("t-carol"):
        dispatch_report(store, _message(), channels=["feishu"])

    assert seen == ["t-carol"]
