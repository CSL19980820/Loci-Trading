"""多通道告警分发：配置读写、并行投递、限流去重。

三条不变量：

1. **绝不回显 secret。** ``list_channels`` / HTTP 只回末 6 位。Webhook URL 的
   key 段就是凭据本身，回显完整 URL 等于把群机器人送人；``headers`` 里常放
   ``Authorization``，值一律一起打码。
2. **限流按 (租户, 通道, 消息指纹)。** 任务重试风暴是真实存在的——一次失败
   的日终同步重试 3 次就会把同一条告警推 3 遍。60s 内同指纹只发一次。
   指纹不含 link（重试的 run_id 会变，含进去等于没限流），见 ``NotifyMessage``。
3. **老部署不许失效。** 只配过 ``wecom_webhook`` 旧键的库读不到 ``notify:wecom``
   时回退读旧键。这条有回归测试兜着，别顺手删。

配置落 ops.db 的 ``meta`` KV，键名 ``notify:<name>``。这些键**不在**
``share_pack_sanitize.META_ALLOWLIST`` 里，所以分享包默认不外发（fail-closed）。
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.ops.domain.notify import NotifyMessage
from src.ops.infrastructure.notify_channels import (
SECRET_FIELDS,
channel_names,
get_channel,
iter_channels,
)
from src.shared.tenancy import submit_with_tenant

logger = logging.getLogger(__name__)

__all__ = [
"NotifyChannelError",
"RATE_LIMIT_SECONDS",
"allow_send",
"configured_channels",
"describe_channel",
"dispatch",
"dispatch_report",
"get_channel_config",
"list_channels",
"mask_secret",
"reset_rate_limiter",
"save_channel_config",
"test_channel",
]

#: meta KV 前缀。
CHANNEL_KEY_PREFIX = "notify:"
#: 只配过企微旧键的老部署走这里回退。
LEGACY_WECOM_KEY = "wecom_webhook"
#: 同一 (通道, 指纹) 的最小重发间隔。
RATE_LIMIT_SECONDS = 60

#: 指纹 -> 上次发送时刻。key 含租户，多租户下不许互相顶掉。
_recent: dict[tuple[str, str, str], float] = {}
_recent_lock = threading.Lock()


class NotifyChannelError(RuntimeError):
    """通道名未知或配置非法；HTTP 层转 4xx。"""


def _tenant() -> str:
    """限流缓存必须按租户隔离，否则 A 租户的告警会顶掉 B 租户的同名告警。"""
    try:
        from src.shared.tenancy import current_tenant

        return current_tenant()
    except Exception:
        return ""


def mask_secret(value: str) -> str:
    """只留末 6 位。空值回空串，短值整条打码——不能靠长度反推原文。"""
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 6:
        return "*" * len(text)
    return "…" + text[-6:]


def _mask_config(name: str, config: dict[str, Any]) -> dict[str, Any]:
    """把一份通道配置压成可以安全回给前端的形状。"""
    secrets = set(SECRET_FIELDS.get(name, ()))
    masked: dict[str, Any] = {}
    for key, value in config.items():
        if key == "headers" and isinstance(value, dict):
            #  header 值常是 Authorization / 签名；键名可以给，值不行。
            masked[key] = {str(k): mask_secret(str(v)) for k, v in value.items()}
        elif key in secrets:
            masked[key] = mask_secret(str(value))
        else:
            masked[key] = value
    return masked


def get_channel_config(store: Any, name: str) -> dict[str, Any]:
    """读一个通道的配置；``wecom`` 读不到新键时回退旧键。"""
    channel = get_channel(name)
    if channel is None:
        raise NotifyChannelError(f"未知的推送通道：{name}")
    getter = getattr(store, "get_setting", None)
    raw = getter(CHANNEL_KEY_PREFIX + channel.name, {}) if callable(getter) else {}
    config = dict(raw) if isinstance(raw, dict) else {}
    if config or channel.name != "wecom" or not callable(getter):
        return config
    #  行为兼容：只配过 wecom_webhook 的老部署不能因为这次改造静音。
    legacy = getter(LEGACY_WECOM_KEY, {}) or {}
    url = str(legacy.get("url") or "").strip() if isinstance(legacy, dict) else ""
    return {"url": url} if url else {}


def save_channel_config(store: Any, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """写一个通道的配置；返回**打码后**的名片。空配置等于删除该通道。"""
    channel = get_channel(name)
    if channel is None:
        raise NotifyChannelError(f"未知的推送通道：{name}")
    if not isinstance(payload, dict):
        raise NotifyChannelError("通道配置必须是对象")
    cleaned = {str(k): v for k, v in payload.items() if v not in (None, "")}
    key = CHANNEL_KEY_PREFIX + channel.name
    if cleaned:
        store.set_setting(key, cleaned)
    else:
        deleter = getattr(store, "delete_setting", None)
        if callable(deleter):
            deleter(key)
    return describe_channel(store, channel.name)


def describe_channel(store: Any, name: str) -> dict[str, Any]:
    """一张通道名片：名字、中文标签、是否已配置、打码后的配置。"""
    channel = get_channel(name)
    if channel is None:
        raise NotifyChannelError(f"未知的推送通道：{name}")
    config = get_channel_config(store, channel.name)
    return {
        "name": channel.name,
        "label": channel.label,
        "configured": channel.is_configured(config),
        "config": _mask_config(channel.name, config),
    }


def list_channels(store: Any) -> list[dict[str, Any]]:
    """六张通道名片（含是否已配置）。**不含任何明文 secret。**"""
    return [describe_channel(store, channel.name) for channel in iter_channels()]


def configured_channels(store: Any) -> list[str]:
    """当前真正可发的通道名，按注册表顺序。"""
    return [row["name"] for row in list_channels(store) if row["configured"]]


def reset_rate_limiter() -> None:
    """测试与运维手动重置用；生产路径不调。"""
    with _recent_lock:
        _recent.clear()


def _allow(channel_name: str, fingerprint: str, *, now: float) -> bool:
    """限流闸门。返回 True 表示放行，并已记账。"""
    key = (_tenant(), channel_name, fingerprint)
    with _recent_lock:
        last = _recent.get(key)
        if last is not None and now - last < RATE_LIMIT_SECONDS:
            return False
        _recent[key] = now
        if len(_recent) > 512:
            #  顺手清理过期项，免得长跑进程把指纹表涨成内存泄漏。
            stale = [k for k, ts in _recent.items() if now - ts >= RATE_LIMIT_SECONDS]
            for k in stale:
                _recent.pop(k, None)
        return True


def allow_send(channel_name: str, fingerprint: str, *, now: float | None = None) -> bool:
    """限流闸门的**公开**入口；返回 True 表示放行，并已记账。

    ``notify_dispatch`` 的旧腿（企微 / Bark）必须经这里过一道。它以前直接 send、
    从不问限流器，于是 ``run_job`` 失败分支的推送能一整天每 5 分钟响一次——
    失败路径又没有 ``wecom_push_mark`` 那种按日去重兜着。

    记账落在**同一张** ``_recent`` 表上：两条腿共用一个 (租户, 通道, 指纹) 口径，
    不会出现「企微被压住、钉钉又冒出来」这种半拉子降噪。
    """
    return _allow(channel_name, fingerprint, now=time.time() if now is None else now)


def dispatch_report(
    store: Any,
    message: NotifyMessage,
    *,
    channels: list[str] | None = None,
    bypass_rate_limit: bool = False,
    config_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """并行投递并返回完整战报：逐通道结果 + 被限流的 + 未配置的。

    ``dispatch`` 只要 ``results``；HTTP 层和测试要能区分「发失败」与
    「压根没发」，所以战报把三种情况分开列，不糊成一个 bool。

    ``config_overrides`` 给「收件人由本次调用决定」的场景用（社区订阅信号
    分发：站内信收件人是这条策略的订阅者，不是运维在设置页填的固定名单）。
    覆盖只影响本次，不落库。
    """
    wanted = [str(n).strip().lower() for n in channels] if channels else channel_names()
    from src.ops.application.notify_calendar import notification_silence_reason
    silence = notification_silence_reason()
    if silence:
        return {"results": {name: False for name in wanted}, "sent": [], "suppressed": wanted, "unconfigured": [], "skipped": silence}
    overrides = {str(k).strip().lower(): dict(v) for k, v in (config_overrides or {}).items()}
    selected: list[tuple[Any, dict[str, Any]]] = []
    unconfigured: list[str] = []
    for name in wanted:
        channel = get_channel(name)
        if channel is None:
            raise NotifyChannelError(f"未知的推送通道：{name}")
        if channel.name in overrides:
            config = overrides[channel.name]
        else:
            config = get_channel_config(store, channel.name)
        if channel.is_configured(config):
            selected.append((channel, config))
        else:
            unconfigured.append(channel.name)

    now = time.time()
    fingerprint = message.fingerprint()
    ready: list[tuple[Any, dict[str, Any]]] = []
    suppressed: list[str] = []
    for channel, config in selected:
        if bypass_rate_limit or _allow(channel.name, fingerprint, now=now):
            ready.append((channel, config))
        else:
            suppressed.append(channel.name)

    results: dict[str, bool] = {}
    if ready:
        #  并行：六个通道串行最坏 48s，会顶到调度器的心跳窗。
        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            #  **必须走 submit_with_tenant**：ContextVar 不跨 ThreadPoolExecutor 边界，
            #  裸 ``pool.submit`` 会让通道线程里的 ``current_tenant()`` 静默落回主租户。
            #  今天六个通道恰好都不读租户上下文，所以「没泄漏」纯属巧合——只要有人给
            #  inbox 通道加一句「按当前租户解析 identity.db」，巧合当场变成串户，且不报错。
            #  这一行就是把那个不变量钉死的地方，别改回裸 submit。
            futures = {
                submit_with_tenant(pool, channel.send, message, config): channel.name
                for channel, config in ready
            }
            for future, name in futures.items():
                #  channel.send 自己不抛（_BaseChannel 的契约）；这里再兜一层是防
                #  线程池本身出事，一个通道挂不能带死整批。
                try:
                    results[name] = bool(future.result())
                except Exception as exc:  # noqa: BLE001
                    logger.warning("notify dispatch %s crashed: %s", name, exc)
                    results[name] = False
    for name in suppressed:
        results[name] = False
    return {
        "results": results,
        "sent": sorted(n for n, ok in results.items() if ok),
        "suppressed": suppressed,
        "unconfigured": unconfigured,
    }


def dispatch(
store: Any,
message: NotifyMessage,
*,
channels: list[str] | None = None,
) -> dict[str, bool]:
    """逐通道结果。未配置的通道不出现在返回值里（压根没试）。"""
    return dict(dispatch_report(store, message, channels=channels)["results"])


def test_channel(store: Any, name: str) -> bool:
    """发一条测试消息。绕过限流：连点两次「测试」必须两次都真的发。"""
    message = NotifyMessage(
        title="Loci 连通测试",
        body="多通道告警已接通。可在运维配置任务完成/失败与触价提醒推送。",
        level="info",
        tags=("test",),
    )
    report = dispatch_report(store, message, channels=[name], bypass_rate_limit=True)
    return bool(report["results"].get((name or "").strip().lower()))
