"""用例：策略广场的列表 / 筛选 / 分页。

排序四选一：``hot`` / ``new`` / ``score`` / ``stars``。
- ``hot``  = 收藏x3 + 克隆x2 + 评论x1 + 浏览x0.1（越费劲的动作权重越高，
      浏览只给 0.1，否则刷阅读量就能上热榜）
- ``score``= 最近一期 ``strategy_metrics.score``（风险调整 x 时间折扣，见 domain/scoring）
- ``new``  = 上架时间倒序
- ``stars``= 收藏数倒序

**广场入口永远只看 listed + public**：unlisted 靠直链访问，private 只有作者自己看得到。
"""

from __future__ import annotations

from typing import Any

from src.community.domain.models import SORTS, Actor, ValidationError
from src.community.infrastructure.store import CommunityStore


def list_square(
    store: CommunityStore,
    *,
    sort: str = "hot",
    kind: str = "",
    tag: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int | None = None,
    viewer: Actor | None = None,
) -> dict[str, Any]:
    """广场列表。返回 ``items`` / ``total`` / ``page`` / ``page_size`` / ``pages``。"""
    if sort not in SORTS:
        raise ValidationError(f"未知排序：{sort}（可选 {', '.join(SORTS)}）")
    result = store.search_publishes(
        sort=sort,
        kind=kind.strip(),
        tag=tag.strip(),
        keyword=keyword.strip(),
        page=page,
        page_size=page_size,
    )
    if viewer is not None:
        starred = set(store.list_starred(viewer.user_id, limit=500))
        for item in result["items"]:
            item["starred"] = item["publish_id"] in starred
    return result


def list_starred(
    store: CommunityStore, *, actor: Actor, limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    """「我收藏的」列表。条目与广场列表**同形状**（含 ``metrics``），前端复用卡片组件。

    分页用 ``limit`` / ``offset`` 而不是 ``page``：收藏是一条按时间倒序的长流，
    前端多半是无限滚动，页码在这里没有意义。

    只回**当前仍可见**的：作者后来改私有 / 下架的不再露出（收藏关系还在库里），
    自己的作品永远看得到。口径与 ``PublishedStrategy.visible_to`` 一致。
    """
    return store.list_starred_publishes(actor.user_id, limit=limit, offset=offset)


def list_mine(
    store: CommunityStore, *, actor: Actor, page: int = 1, page_size: int | None = None
) -> dict[str, Any]:
    """「我的发布」：含未列出 / 私有 / 已下架，只有本人（或 admin）能调。"""
    return store.search_publishes(
        sort="new",
        owner_user_id=actor.user_id,
        page=page,
        page_size=page_size,
        include_hidden=True,
    )


def user_profile(
    store: CommunityStore, user_id: str, *, viewer: Actor | None = None
) -> dict[str, Any]:
    """公开主页：作品列表 + 关注数 + 累计收藏。

    统计只数**公开且在架**的作品——私有草稿不该出现在别人看的主页上，
    也不该把「我有多少个草稿」这种信息漏出去。
    """
    include_hidden = bool(viewer and viewer.owns(user_id))
    items = store.list_owner_publishes(user_id, include_hidden=include_hidden, limit=100)
    total_stars = sum(int(item.get("stars") or 0) for item in items)
    total_clones = sum(int(item.get("clones") or 0) for item in items)
    display_name = ""
    for item in items:
        if item.get("owner_name"):
            display_name = str(item["owner_name"])
            break
    return {
        "user_id": user_id,
        "display_name": display_name,
        "strategies": items,
        "counts": {
            "strategies": len(items),
            "stars": total_stars,
            "clones": total_clones,
            "followers": store.count_followers(user_id),
            "following": len(store.list_following(user_id)),
        },
        "viewer": {
            "is_self": bool(viewer and viewer.user_id == user_id),
            "following": bool(viewer and store.is_following(viewer.user_id, user_id)),
        },
    }


def popular_tags(store: CommunityStore, *, limit: int = 30) -> list[dict[str, Any]]:
    return store.list_tags(limit=limit)
