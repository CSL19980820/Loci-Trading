"""用例：收藏 / 克隆 / 评论 / 关注 / 动态流。

一条通用规则：**互动写入都要顺手写一条动态**，但动态失败不能回滚互动
（动态是播报，收藏才是事实）。所以动态写在事务之外、互动成功之后。
"""

from __future__ import annotations

from typing import Any

from src.community.application.publishing import clone_bundle
from src.community.domain.models import (
    Actor,
    Comment,
    ConflictError,
    NotFoundError,
    PublishedStrategy,
    ValidationError,
)
from src.community.infrastructure.store import CommunityStore

#: 评论正文长度上限。超长的多半是贴回测日志，那该发新版而不是刷屏。
MAX_COMMENT_LEN = 1000


def star(store: CommunityStore, publish_id: str, *, actor: Actor) -> dict[str, Any]:
    record = _visible(store, publish_id, actor)
    changed = store.add_star(publish_id, actor.user_id)
    if changed:
        store.add_feed_item(
            actor_id=actor.user_id,
            actor_name=actor.name,
            verb="starred",
            object_type="strategy",
            object_id=publish_id,
            object_title=record.get("title", ""),
        )
    fresh = store.get_publish(publish_id) or record
    return {
        "publish_id": publish_id,
        "starred": True,
        "changed": changed,
        "stars": fresh.get("stars", 0),
    }


def unstar(store: CommunityStore, publish_id: str, *, actor: Actor) -> dict[str, Any]:
    record = _visible(store, publish_id, actor)
    changed = store.remove_star(publish_id, actor.user_id)
    fresh = store.get_publish(publish_id) or record
    return {
        "publish_id": publish_id,
        "starred": False,
        "changed": changed,
        "stars": fresh.get("stars", 0),
    }


def clone(
    store: CommunityStore, publish_id: str, *, actor: Actor, version: int | None = None
) -> dict[str, Any]:
    """克隆：返回可导入的 bundle + 加一次计数。

    **这里不写对方的租户库**。社区连别人 palace.db 的路径都不知道，也不该知道；
    导入发生在客户端拿到 bundle 之后，由目标上下文自己校验、自己落库。
    """
    record = _visible(store, publish_id, actor)
    bundle = clone_bundle(store, publish_id, version=version, actor=actor)
    store.record_clone(publish_id, version=int(bundle.get("version") or 1), user_id=actor.user_id)
    store.add_feed_item(
        actor_id=actor.user_id,
        actor_name=actor.name,
        verb="cloned",
        object_type="strategy",
        object_id=publish_id,
        object_title=record.get("title", ""),
    )
    fresh = store.get_publish(publish_id) or record
    return {"bundle": bundle, "clones": fresh.get("clones", 0)}


def add_comment(
    store: CommunityStore, publish_id: str, *, actor: Actor, body: str, parent_id: str = ""
) -> dict[str, Any]:
    text = (body or "").strip()
    if not text:
        raise ValidationError("评论不能为空")
    if len(text) > MAX_COMMENT_LEN:
        raise ValidationError(f"评论不得超过 {MAX_COMMENT_LEN} 字")
    record = _visible(store, publish_id, actor)
    created = store.add_comment(
        publish_id,
        user_id=actor.user_id,
        user_name=actor.name,
        body=text,
        parent_id=(parent_id or "").strip(),
    )
    store.add_feed_item(
        actor_id=actor.user_id,
        actor_name=actor.name,
        verb="commented",
        object_type="strategy",
        object_id=publish_id,
        object_title=record.get("title", ""),
    )
    return Comment.from_row(created).to_dict()


def list_comments(
    store: CommunityStore, publish_id: str, *, actor: Actor | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    _visible(store, publish_id, actor)
    rows = store.list_comments(publish_id, limit=limit)
    return [Comment.from_row(row).to_dict() for row in rows]


def delete_comment(store: CommunityStore, comment_id: str, *, actor: Actor) -> dict[str, Any]:
    """软删。作者本人、发布物主人、admin 三种人可删。"""
    row = store.get_comment(comment_id)
    if row is None:
        raise NotFoundError(f"评论不存在：{comment_id}")
    publish = store.get_publish(str(row.get("publish_id") or ""))
    owner_id = str(publish.get("owner_user_id") or "") if publish else ""
    if not (
        actor.is_admin or actor.user_id == str(row.get("user_id")) or actor.user_id == owner_id
    ):
        from src.community.domain.models import PermissionDeniedError

        raise PermissionDeniedError("只能删自己的评论（或自己发布物下的评论）")
    updated = store.soft_delete_comment(comment_id)
    return Comment.from_row(updated).to_dict()


def follow(store: CommunityStore, followee_id: str, *, actor: Actor) -> dict[str, Any]:
    if not followee_id.strip():
        raise ValidationError("缺少 followee_id")
    changed = store.follow(actor.user_id, followee_id)
    if changed:
        store.add_feed_item(
            actor_id=actor.user_id,
            actor_name=actor.name,
            verb="followed",
            object_type="user",
            object_id=followee_id,
        )
    return {
        "followee_id": followee_id,
        "following": True,
        "changed": changed,
        "followers": store.count_followers(followee_id),
    }


def unfollow(store: CommunityStore, followee_id: str, *, actor: Actor) -> dict[str, Any]:
    changed = store.unfollow(actor.user_id, followee_id)
    return {
        "followee_id": followee_id,
        "following": False,
        "changed": changed,
        "followers": store.count_followers(followee_id),
    }


def feed(
    store: CommunityStore,
    *,
    actor: Actor | None = None,
    scope: str = "all",
    limit: int = 50,
    before: str = "",
) -> list[dict[str, Any]]:
    """动态流。``scope='following'`` 只看关注的人（需要登录）。"""
    if scope not in ("all", "following", "mine"):
        raise ValidationError(f"未知动态范围：{scope}")
    actor_ids: list[str] | None = None
    if scope == "following":
        if actor is None:
            raise ValidationError("看关注动态需要先登录")
        actor_ids = store.list_following(actor.user_id)
    elif scope == "mine":
        if actor is None:
            raise ValidationError("看自己的动态需要先登录")
        actor_ids = [actor.user_id]
    return store.list_feed(actor_ids=actor_ids, limit=limit, before=before)


def recount(store: CommunityStore, publish_id: str, *, actor: Actor) -> dict[str, int]:
    """计数校准（计数是缓存，明细才是真相）。只有 admin 能调。"""
    if not actor.is_admin:
        from src.community.domain.models import PermissionDeniedError

        raise PermissionDeniedError("计数校准仅限管理员")
    store.require_publish(publish_id)
    return store.recount_engagement(publish_id)


def _visible(store: CommunityStore, publish_id: str, actor: Actor | None) -> dict[str, Any]:
    record = store.get_publish(publish_id)
    if record is None:
        raise NotFoundError(f"发布物不存在：{publish_id}")
    if not PublishedStrategy.from_row(record).visible_to(actor):
        raise NotFoundError(f"发布物不存在：{publish_id}")
    if record.get("status") == "delisted" and not (
        actor and actor.owns(str(record["owner_user_id"]))
    ):
        raise ConflictError("该策略已下架")
    return record
