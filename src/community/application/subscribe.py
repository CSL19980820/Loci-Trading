"""用例：跟单订阅与信号拉取。

**合规红线：只推信号，不自动下单。**
本模块能做的只有两件事：把订阅关系存下来；把作者当天发的信号快照读出来。
它**不会**、也永远不该：调用任何下单通道、写订阅者的 ``palace.db``、
替订阅者生成成交。见 ``domain/models.py::Subscription`` 的说明。
"""

from __future__ import annotations

from typing import Any, Mapping

from src.community.domain.models import (
    Actor,
    ConflictError,
    NotFoundError,
    PublishedStrategy,
    Subscription,
    today_iso,
)
from src.community.infrastructure.store import CommunityStore

#: 通知渠道白名单。站内信永远可用；其余留给组合根接真实通道。
NOTIFY_CHANNELS = ("inapp", "desktop", "email")


def subscribe(
    store: CommunityStore,
    publish_id: str,
    *,
    actor: Actor,
    notify_channels: list[str] | None = None,
) -> dict[str, Any]:
    """订阅（幂等）。只有在架且可见的发布物能订。"""
    record = _subscribable(store, publish_id, actor)
    channels = [str(item) for item in (notify_channels or ["inapp"])]
    unknown = [item for item in channels if item not in NOTIFY_CHANNELS]
    if unknown:
        raise ConflictError(f"未知通知渠道：{', '.join(unknown)}")
    row = store.subscribe(publish_id, actor.user_id, notify_channels=channels)
    payload = Subscription.from_row(row).to_dict()
    payload["title"] = record.get("title", "")
    payload["notice"] = "只推信号，不自动下单"
    return payload


def unsubscribe(store: CommunityStore, publish_id: str, *, actor: Actor) -> dict[str, Any]:
    changed = store.unsubscribe(publish_id, actor.user_id)
    return {"publish_id": publish_id, "subscribed": False, "changed": changed}


def pause(
    store: CommunityStore, publish_id: str, *, actor: Actor, paused: bool = True
) -> dict[str, Any]:
    row = store.pause_subscription(publish_id, actor.user_id, paused=paused)
    return Subscription.from_row(row).to_dict()


def list_subscriptions(store: CommunityStore, *, actor: Actor) -> list[dict[str, Any]]:
    """我的订阅列表（带发布物标题与作者）。"""
    out: list[dict[str, Any]] = []
    for row in store.list_subscriptions(actor.user_id):
        item = Subscription.from_row(row).to_dict()
        item["title"] = row.get("title", "")
        item["owner_name"] = row.get("owner_name", "")
        item["owner_user_id"] = row.get("owner_user_id", "")
        item["status"] = row.get("status", "")
        out.append(item)
    return out


def publish_signals(
    store: CommunityStore,
    publish_id: str,
    *,
    actor: Actor,
    payload: Mapping[str, Any],
    trade_date: str = "",
) -> dict[str, Any]:
    """作者发布当日信号快照（一天一条，重发覆盖）。

    只有作者本人（或 admin）能发；这是「作者说今天他的策略给了什么信号」，
    不是行情，也不是成交——订阅者拿去自己判断。
    """
    record = store.require_publish(publish_id)
    actor.require_owner(str(record["owner_user_id"]), what="策略信号")
    day = (trade_date or "").strip() or today_iso()
    body = dict(payload or dict())
    body.setdefault("entry_timing", record.get("entry_timing", ""))
    body.setdefault("version", record.get("current_version", 1))
    row = store.put_broadcast(publish_id, trade_date=day, payload=body)
    return {
        "publish_id": publish_id,
        "trade_date": day,
        "payload": row.get("payload", dict()),
        "subscribers": store.count_subscribers(publish_id),
        "notice": "只推信号，不自动下单",
    }


def pull_signals(
    store: CommunityStore, *, actor: Actor, trade_date: str = "", limit: int = 200
) -> dict[str, Any]:
    """拉我订阅的策略的信号。

    ``trade_date`` 为空时取每个策略各自的**最新一期**（有的策略今天没发信号，
    那就应该看到它上一次发的是什么，而不是凭空补一条空信号）。
    """
    subs = [row for row in store.list_subscriptions(actor.user_id, active_only=True)]
    publish_ids = [str(row["publish_id"]) for row in subs]
    titles = {str(row["publish_id"]): str(row.get("title") or "") for row in subs}
    rows = store.list_broadcasts_for(publish_ids, trade_date=trade_date, limit=limit)
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "publish_id": row.get("publish_id"),
                "title": titles.get(str(row.get("publish_id")), ""),
                "trade_date": row.get("trade_date"),
                "payload": row.get("payload", dict()),
                "created_at": row.get("created_at"),
            }
        )
    items.sort(key=lambda item: (str(item["trade_date"]), str(item["publish_id"])), reverse=True)
    return {
        "trade_date": trade_date or "",
        "subscriptions": len(publish_ids),
        "items": items,
        "notice": "只推信号，不自动下单；是否成交由你自己决定并记在自己的账本里",
    }


def _subscribable(store: CommunityStore, publish_id: str, actor: Actor) -> dict[str, Any]:
    record = store.get_publish(publish_id)
    if record is None:
        raise NotFoundError(f"发布物不存在：{publish_id}")
    if not PublishedStrategy.from_row(record).visible_to(actor):
        raise NotFoundError(f"发布物不存在：{publish_id}")
    if record.get("status") != "listed":
        raise ConflictError("已下架的策略不能订阅")
    return record
