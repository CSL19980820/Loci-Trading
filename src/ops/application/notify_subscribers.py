"""社区订阅信号 → 告警通道分发。

背景：`src/community` 里订阅这条链**只有一半**——`subscribe()` 把
``notify_channels``（inapp / desktop / email）存进 `subscriptions` 表，
`publish_signals()` 写一行 `signal_broadcasts` 就收工，谁也不通知；
`CommunityStore.list_subscribers()` 全仓零调用。订阅者只能自己去轮询
`GET /api/community/subscriptions/signals`。这里补上推的那一半。

**为什么落在 ops 而不是 community**：community 不许 import identity/ops
（`.importlinter` 的两条 protect 契约 + `community/api/deps.py` 里刻意的鸭子
类型），而站内信在 identity、通道注册表在 ops。所以由 ops 提供这个函数，
community 侧（或组合根）把 store 传进来调用即可——依赖方向不反。

``community_store`` 是**鸭子类型**参数：只要有 ``list_subscribers`` /
``get_subscription`` 两个方法就行。不 import `CommunityStore`，测试塞个假的
就能跑，也不用为了发一条信号把整个社区上下文拉起来。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from src.ops.application.notify_registry import dispatch_report
from src.ops.domain.notify import NotifyMessage

logger = logging.getLogger(__name__)

__all__ = [
"SUBSCRIPTION_CHANNEL_MAP",
"UNSUPPORTED_SUBSCRIPTION_CHANNELS",
"dispatch_subscription_signal",
"reset_signal_dedup",
"resolve_subscriber_targets",
]

#: 社区侧的订阅偏好 -> 本地通道名。
SUBSCRIPTION_CHANNEL_MAP = {"inapp": "inbox", "email": "email"}
#: 本仓没有桌面推送传输；照实记下来，不要假装发过。
UNSUPPORTED_SUBSCRIPTION_CHANNELS = ("desktop",)
#: 订阅时没勾任何渠道 = 站内信。静默不发是最坏的默认值。
DEFAULT_SUBSCRIPTION_CHANNELS = ("inapp",)

#: 同一条信号的去重窗口。按 ``(publish_id, trade_date)`` 记，一个交易日只推一次。
SIGNAL_DEDUP_SECONDS = 24 * 3600

#: (租户, publish_id, trade_date) -> 上次推送时刻。
#:
#: **为什么不靠 ``NotifyMessage.fingerprint()`` 的 60s 限流**：那个指纹是
#: ``title\x1flevel\x1fbody``，**不含 tags**，而 ``publish_id`` 恰恰只在 tags 里。
#: 同一作者两条不同策略，正文由同一套模板拼出来时字节级相同 —— 60s 内第二条会被
#: 当成重复吃掉，用户永远收不到那条信号，且没有任何日志说「我压了它」。
#:
#: 把 tags 塞进 fingerprint 也能修，但那会连带改掉所有通道的既有限流行为
#: （任务重试风暴那条防线依赖「link/tags 不参与指纹」）。所以去重放在这一层，
#: 按业务真正的唯一键做，然后 ``dispatch_report(bypass_rate_limit=True)`` 把
#: 通用限流让开——两套口径不叠加，谁在压住消息一目了然。
_recent_signals: dict[tuple[str, str, str], float] = {}
_dedup_lock = threading.Lock()


def reset_signal_dedup() -> None:
    """清空信号去重表。测试与运维手动重置用；生产路径不调。"""
    with _dedup_lock:
        _recent_signals.clear()


def _tenant() -> str:
    """去重表按租户分区：A 租户推过的信号不能顶掉 B 租户的同一条。"""
    try:
        from src.shared.tenancy import current_tenant

        return current_tenant()
    except Exception:  # noqa: BLE001
        return ""


def _claim_signal(publish_id: str, trade_date: str) -> bool:
    """占坑：本交易日第一次推这条信号返回 True，重复返回 False。"""
    key = (_tenant(), publish_id, str(trade_date or ""))
    now = time.time()
    with _dedup_lock:
        last = _recent_signals.get(key)
        if last is not None and now - last < SIGNAL_DEDUP_SECONDS:
            return False
        _recent_signals[key] = now
        if len(_recent_signals) > 512:
            stale = [k for k, ts in _recent_signals.items() if now - ts >= SIGNAL_DEDUP_SECONDS]
            for k in stale:
                _recent_signals.pop(k, None)
        return True


def _prefs_of(community_store: Any, publish_id: str, user_id: str) -> tuple[str, ...]:
    """读一个订阅者的渠道偏好；读不到就按默认（站内信）。"""
    getter = getattr(community_store, "get_subscription", None)
    if not callable(getter):
        return DEFAULT_SUBSCRIPTION_CHANNELS
    try:
        row = getter(publish_id, user_id) or {}
    except Exception as exc:  # noqa: BLE001 — 一个订阅者读崩不该拖垮整轮分发
        logger.warning("read subscription %s/%s failed: %s", publish_id, user_id, exc)
        return DEFAULT_SUBSCRIPTION_CHANNELS
    raw = row.get("notify_channels") if isinstance(row, dict) else None
    if isinstance(raw, (list, tuple)) and raw:
        return tuple(str(item).strip().lower() for item in raw if str(item).strip())
    return DEFAULT_SUBSCRIPTION_CHANNELS


def _emails_of(user_ids: list[str], *, identity_db: str | None) -> list[str]:
    """把 user_id 换成邮箱。查不到的静默跳过——宁可少发，不能发错人。"""
    if not user_ids:
        return []
    from src.identity import IdentityStore

    found: list[str] = []
    try:
        with IdentityStore(identity_db) as store:
            for user_id in user_ids:
                user = store.get_user(user_id)
                email = str(getattr(user, "email", "") or "").strip()
                if email:
                    found.append(email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve subscriber emails failed: %s", exc)
        return []
    return found


def resolve_subscriber_targets(
community_store: Any,
publish_id: str,
) -> dict[str, list[str]]:
    """按渠道分桶订阅者 user_id。

    返回 ``{"inbox": [...], "email": [...], "desktop": [...]}``；
    ``desktop`` 单列是为了让调用方看得见「有人想要但我们发不了」，
    而不是把它悄悄丢掉。
    """
    lister = getattr(community_store, "list_subscribers", None)
    if not callable(lister):
        return {}
    try:
        user_ids = [str(uid).strip() for uid in (lister(publish_id) or ()) if str(uid).strip()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("list subscribers of %s failed: %s", publish_id, exc)
        return {}

    buckets: dict[str, list[str]] = {}
    for user_id in user_ids:
        for pref in _prefs_of(community_store, publish_id, user_id):
            if pref in UNSUPPORTED_SUBSCRIPTION_CHANNELS:
                buckets.setdefault(pref, []).append(user_id)
                continue
            channel = SUBSCRIPTION_CHANNEL_MAP.get(pref)
            if channel:
                buckets.setdefault(channel, []).append(user_id)
    return buckets


def dispatch_subscription_signal(
ops_store: Any,
community_store: Any,
publish_id: str,
*,
title: str,
body: str,
link: str = "",
level: str = "info",
trade_date: str = "",
identity_db: str | None = None,
) -> dict[str, Any]:
    """把一条已发布的策略信号推给它的订阅者。

    收件人由**本次调用**决定（这条策略的订阅者），不是运维在设置页填的固定
    名单，所以走 ``dispatch_report`` 的 ``config_overrides``，不落库。

    **去重按 ``(publish_id, trade_date)``，不按消息指纹。** 社区那边
    ``put_broadcast`` 是按这个键 upsert 的，同一天重发很常见（改个价位再发一次），
    不能每次都轰订阅者一遍。而通用限流的指纹是 ``title/level/body``、**不含 tags**，
    ``publish_id`` 恰恰只活在 tags 里：同一作者两条不同策略若模板化正文相同，
    60s 内第二条会被静默吃掉。所以这里自己按业务唯一键占坑，然后
    ``bypass_rate_limit=True`` 把通用限流让开，避免两套口径互相打架。

    ``trade_date`` 留空表示「不按日去重，只按 publish_id」——调用方拿得到交易日
    就一定要传，否则同一条策略换一天再发会被当成重复压掉。
    """
    buckets = resolve_subscriber_targets(community_store, publish_id)
    inbox_users = buckets.get("inbox") or []
    email_users = buckets.get("email") or []
    skipped = {
        name: buckets.get(name) or []
        for name in UNSUPPORTED_SUBSCRIPTION_CHANNELS
        if buckets.get(name)
    }

    overrides: dict[str, dict[str, Any]] = {}
    if inbox_users:
        overrides["inbox"] = {
            "user_ids": inbox_users,
            "identity_db": identity_db or "",
            "kind": "signal",
        }
    emails = _emails_of(email_users, identity_db=identity_db)
    if emails:
        overrides["email"] = {"to": emails}

    if not overrides:
        return {
            "publish_id": publish_id,
            "subscribers": 0,
            "results": {},
            "sent": [],
            "skipped": skipped,
            "notice": "只推信号，不自动下单",
        }

    message = NotifyMessage(
        title=title,
        body=body,
        level=level if level in ("info", "warn", "critical") else "info",
        link=link,
        tags=("community", "signal", publish_id),
    )
    if not _claim_signal(publish_id, trade_date):
        logger.info("signal %s@%s 今日已推过，跳过", publish_id, trade_date or "-")
        return {
            "publish_id": publish_id,
            "subscribers": len({*inbox_users, *email_users}),
            "results": {},
            "sent": [],
            "suppressed": [],
            "deduped": True,
            "skipped": skipped,
            "notice": "只推信号，不自动下单",
        }

    report = dispatch_report(
        ops_store,
        message,
        channels=list(overrides),
        config_overrides=overrides,
        #  去重已在上面按 (publish_id, trade_date) 做过；再叠一层 60s 指纹限流只会
        #  把「两条不同策略正文恰好相同」误伤成重复。
        bypass_rate_limit=True,
    )
    return {
        "publish_id": publish_id,
        "subscribers": len({*inbox_users, *email_users}),
        "results": report["results"],
        "sent": report["sent"],
        "suppressed": report["suppressed"],
        "deduped": False,
        "skipped": skipped,
        #  与 community.publish_signals 的返回值同口径，别让两边说法不一致。
        "notice": "只推信号，不自动下单",
    }
