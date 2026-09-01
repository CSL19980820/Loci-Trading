"""用例：发布 / 发新版 / 下架 / 改可见性。

编排顺序固定：**先跑上架清单 → 再落库 → 最后写动态**。清单在前是因为它是纯函数，
不通过就一行都不该写进库；动态在后是因为它是「已经发生了」的播报，写在事务前会
出现「广场说他发布了、点进去 404」。
"""

from __future__ import annotations

from typing import Any, Mapping

from src.community.domain.models import (
    VISIBILITIES,
    Actor,
    ConflictError,
    NotFoundError,
    PublishedStrategy,
    ValidationError,
)
from src.community.domain.publish_rules import check_publish_ready, ensure_publishable
from src.community.infrastructure.store import CommunityStore
from src.community.infrastructure.store_helpers import slugify


def preflight(payload: Mapping[str, Any]) -> dict[str, Any]:
    """发布前预检：不写库，只回清单结果。前端「检查一下」按钮用。"""
    violations = [item.to_dict() for item in check_publish_ready(payload)]
    return {"ok": not violations, "violations": violations}


def publish_strategy(
    store: CommunityStore, *, actor: Actor, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """上架一个新策略（同时冻结第 1 版）。"""
    ensure_publishable(payload)
    title = str(payload.get("title") or "").strip()
    slug = slugify(str(payload.get("slug") or "") or title)
    if store.find_publish_by_slug(actor.user_id, slug):
        raise ConflictError(f"你已经有一个 slug={slug} 的发布物，换个标题或发新版")
    record = store.create_publish(
        owner_user_id=actor.user_id,
        owner_name=actor.name,
        slug=slug,
        title=title,
        summary=str(payload.get("summary") or "").strip(),
        kind=str(payload.get("kind") or "screen"),
        entry_timing=str(payload.get("entry_timing") or ""),
        visibility=_visibility(payload.get("visibility")),
        tags=[str(tag) for tag in (payload.get("tags") or [])],
        source_text=str(payload.get("source_text") or ""),
        params=dict(payload.get("params") or dict()),
        manifest=_manifest(payload),
        release_notes=str(payload.get("release_notes") or "首次发布"),
    )
    if record.get("visibility") == "public":
        store.add_feed_item(
            actor_id=actor.user_id,
            actor_name=actor.name,
            verb="published",
            object_type="strategy",
            object_id=record["publish_id"],
            object_title=record.get("title", ""),
        )
    return detail(store, record["publish_id"], actor=actor)


def publish_new_version(
    store: CommunityStore, publish_id: str, *, actor: Actor, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """发新版。旧版原地冻结，不会被改写。"""
    record = store.require_publish(publish_id)
    actor.require_owner(str(record["owner_user_id"]))
    merged = {
        "title": record.get("title", ""),
        "summary": record.get("summary", ""),
        "kind": record.get("kind", "screen"),
        "entry_timing": payload.get("entry_timing") or record.get("entry_timing", ""),
        "tags": record.get("tags", []),
    }
    merged.update({key: value for key, value in payload.items() if value is not None})
    ensure_publishable(merged)
    version = store.add_version(
        publish_id,
        source_text=str(payload.get("source_text") or ""),
        params=dict(payload.get("params") or dict()),
        manifest=_manifest(payload),
        release_notes=str(payload.get("release_notes") or ""),
    )
    if record.get("visibility") == "public" and record.get("status") == "listed":
        store.add_feed_item(
            actor_id=actor.user_id,
            actor_name=actor.name,
            verb="released",
            object_type="strategy",
            object_id=publish_id,
            object_title=f"{record.get('title', '')} v{version.get('version')}",
        )
    return {"strategy": store.get_publish(publish_id), "version": version}


def delist_strategy(store: CommunityStore, publish_id: str, *, actor: Actor) -> dict[str, Any]:
    """下架。**不删数据**：版本冻结着，已克隆的人还要能对账。"""
    record = store.require_publish(publish_id)
    actor.require_owner(str(record["owner_user_id"]))
    if record.get("status") == "delisted":
        return {"strategy": record, "changed": False}
    updated = store.set_status(publish_id, "delisted")
    store.add_feed_item(
        actor_id=actor.user_id,
        actor_name=actor.name,
        verb="delisted",
        object_type="strategy",
        object_id=publish_id,
        object_title=record.get("title", ""),
    )
    return {"strategy": updated, "changed": True}


def relist_strategy(store: CommunityStore, publish_id: str, *, actor: Actor) -> dict[str, Any]:
    """重新上架（下架是可逆的；作者改完就该能放回去）。"""
    record = store.require_publish(publish_id)
    actor.require_owner(str(record["owner_user_id"]))
    if record.get("status") == "listed":
        return {"strategy": record, "changed": False}
    return {"strategy": store.set_status(publish_id, "listed"), "changed": True}


def set_visibility(
    store: CommunityStore, publish_id: str, *, actor: Actor, visibility: str
) -> dict[str, Any]:
    record = store.require_publish(publish_id)
    actor.require_owner(str(record["owner_user_id"]))
    return store.update_publish(publish_id, visibility=_visibility(visibility)) or dict()


def update_listing(
    store: CommunityStore, publish_id: str, *, actor: Actor, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """改标题 / 摘要 / 标签（**不碰任何版本内容**）。"""
    record = store.require_publish(publish_id)
    actor.require_owner(str(record["owner_user_id"]))
    fields: dict[str, Any] = dict()
    for key in ("title", "summary", "kind"):
        if payload.get(key) is not None:
            fields[key] = str(payload[key]).strip()
    if payload.get("tags") is not None:
        fields["tags"] = [str(tag) for tag in payload["tags"]]
    merged = {
        "title": fields.get("title", record.get("title", "")),
        "summary": fields.get("summary", record.get("summary", "")),
        "kind": fields.get("kind", record.get("kind", "screen")),
        "entry_timing": record.get("entry_timing", ""),
        "tags": fields.get("tags", record.get("tags", [])),
        "source_text": "unchanged",
        "backtest": _fake_backtest_ok(),
    }
    blocking = [item for item in check_publish_ready(merged) if item.blocking]
    text_blocking = [item for item in blocking if not item.field.startswith("backtest")]
    if text_blocking:
        from src.community.domain.models import PublishRuleError

        raise PublishRuleError(
            f"文案检查未通过（{len(text_blocking)} 项）", [item.to_dict() for item in text_blocking]
        )
    return store.update_publish(publish_id, **fields) or dict()


def detail(
    store: CommunityStore,
    publish_id: str,
    *,
    actor: Actor | None = None,
    count_view: bool = False,
) -> dict[str, Any]:
    """详情页数据：发布物 + 当前版本 + 最新绩效 + 观察者视角。"""
    record = _visible_or_404(store, publish_id, actor)
    if count_view:
        store.bump_views(publish_id)
        record = store.get_publish(publish_id) or record
    viewer = {
        "starred": bool(actor and store.has_starred(publish_id, actor.user_id)),
        "subscribed": bool(actor and store.get_subscription(publish_id, actor.user_id)),
        "can_edit": bool(actor and actor.owns(str(record["owner_user_id"]))),
    }
    return {
        "strategy": record,
        "version": store.get_version(publish_id),
        "metrics": store.latest_metrics(publish_id),
        "subscribers": store.count_subscribers(publish_id),
        "viewer": viewer,
    }


def list_versions(
    store: CommunityStore, publish_id: str, *, actor: Actor | None = None
) -> list[dict[str, Any]]:
    record = _visible_or_404(store, publish_id, actor)
    versions = store.list_versions(str(record["publish_id"]))
    owner = bool(actor and actor.owns(str(record["owner_user_id"])))
    if owner:
        return versions
    # 非作者不给看正文历史（只给当前版）：旧版正文属于作者的迭代过程。
    current = int(record.get("current_version") or 1)
    trimmed: list[dict[str, Any]] = []
    for item in versions:
        copy = dict(item)
        if int(copy.get("version") or 0) != current:
            copy["source_text"] = ""
        trimmed.append(copy)
    return trimmed


def clone_bundle(
    store: CommunityStore,
    publish_id: str,
    *,
    version: int | None = None,
    actor: Actor | None = None,
) -> dict[str, Any]:
    """组装可导入的 bundle。

    **只返回 payload，不写对方的租户库。** 社区不知道调用者的 palace.db 在哪，
    也不该知道：导入是客户端拿到 bundle 之后自己那边的事。
    """
    record = _visible_or_404(store, publish_id, actor)
    snapshot = store.get_version(publish_id, version)
    if snapshot is None:
        raise NotFoundError(f"版本不存在：{publish_id} v{version}")
    return {
        "publish_id": publish_id,
        "slug": record.get("slug", ""),
        "title": record.get("title", ""),
        "summary": record.get("summary", ""),
        "kind": record.get("kind", "screen"),
        "entry_timing": record.get("entry_timing", ""),
        "owner_name": record.get("owner_name", ""),
        "version": snapshot.get("version"),
        "source_text": snapshot.get("source_text", ""),
        "params": snapshot.get("params", dict()),
        "manifest": snapshot.get("manifest", dict()),
        "content_sha256": snapshot.get("content_sha256", ""),
        "imported_from": "community",
    }


def _visible_or_404(store: CommunityStore, publish_id: str, actor: Actor | None) -> dict[str, Any]:
    """看不见的一律 404 而不是 403：403 会泄露「这个 id 确实存在」。"""
    record = store.get_publish(publish_id)
    if record is None:
        raise NotFoundError(f"发布物不存在：{publish_id}")
    if not PublishedStrategy.from_row(record).visible_to(actor):
        raise NotFoundError(f"发布物不存在：{publish_id}")
    return record


def _visibility(raw: Any) -> str:
    value = str(raw or "public").strip() or "public"
    if value not in VISIBILITIES:
        raise ValidationError(f"未知可见性：{value}（可选 {', '.join(VISIBILITIES)}）")
    return value


def _manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """版本清单：回测证据与成本假设一起冻进版本里。

    把 backtest 塞进 manifest 而不是另开一张表，是因为它是**这一版的证据**：
    没有它，日后没人说得清「当时凭什么给上架」。
    """
    manifest = dict(payload.get("manifest") or dict())
    backtest = payload.get("backtest")
    if isinstance(backtest, Mapping):
        manifest["backtest"] = dict(backtest)
    return manifest


def _fake_backtest_ok() -> dict[str, Any]:
    """仅供 ``update_listing`` 跑文案检查时占位。

    改标题不该重跑回测门槛（那份证据已经冻在版本里了），但清单是一整套的，
    所以塞一份合规占位、再把 backtest 相关的 violation 过滤掉。
    """
    return {
        "trades": 999,
        "start": "2000-01-01",
        "end": "2020-01-01",
        "commission_bps": 3,
        "stamp_duty_bps": 10,
        "slippage_bps": 5,
    }
