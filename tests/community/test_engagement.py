"""互动用例单测：收藏 / 克隆 / 评论软删 / 关注 / 动态流。"""

from __future__ import annotations

import pytest

from src.community import CommunityStore
from src.community.application import engagement, publishing
from src.community.domain.models import (
    Actor,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from tests.community.conftest import valid_payload


def _pid(published: dict) -> str:
    return str(published["strategy"]["publish_id"])


def test_star_is_idempotent_and_counted(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    publish_id = _pid(published)
    first = engagement.star(store, publish_id, actor=reader)
    assert first == {"publish_id": publish_id, "starred": True, "changed": True, "stars": 1}
    again = engagement.star(store, publish_id, actor=reader)
    assert again["changed"] is False
    assert again["stars"] == 1
    # 明细才是真相，计数只是缓存
    assert store.list_starred(reader.user_id) == [publish_id]


def test_unstar_decrements_but_never_goes_negative(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    publish_id = _pid(published)
    engagement.star(store, publish_id, actor=reader)
    assert engagement.unstar(store, publish_id, actor=reader)["stars"] == 0
    assert engagement.unstar(store, publish_id, actor=reader)["changed"] is False
    assert store.get_publish(publish_id)["stars"] == 0


def test_clone_returns_bundle_and_counts_without_writing_foreign_state(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    publish_id = _pid(published)
    result = engagement.clone(store, publish_id, actor=reader)
    assert result["clones"] == 1
    assert result["bundle"]["publish_id"] == publish_id
    assert result["bundle"]["version"] == 1
    assert store.count_clones(publish_id) == 1
    verbs = [item["verb"] for item in store.list_feed()]
    assert "cloned" in verbs


def test_comment_flow_with_soft_delete(
    store: CommunityStore, author: Actor, reader: Actor, published: dict
) -> None:
    publish_id = _pid(published)
    root = engagement.add_comment(store, publish_id, actor=reader, body="思路清晰")
    child = engagement.add_comment(
        store, publish_id, actor=author, body="谢谢", parent_id=root["id"]
    )
    assert child["parent_id"] == root["id"]
    assert store.get_publish(publish_id)["comments_count"] == 2
    deleted = engagement.delete_comment(store, root["id"], actor=reader)
    assert deleted["deleted"] is True
    assert deleted["body"] == ""
    assert deleted["user_name"] == ""
    listed = engagement.list_comments(store, publish_id, actor=reader)
    # 软删：楼层还在，父子关系不塌
    assert len(listed) == 2
    assert listed[0]["deleted"] is True
    assert listed[1]["parent_id"] == root["id"]
    assert store.get_publish(publish_id)["comments_count"] == 1


def test_comment_validation(store: CommunityStore, reader: Actor, published: dict) -> None:
    publish_id = _pid(published)
    with pytest.raises(ValidationError):
        engagement.add_comment(store, publish_id, actor=reader, body="   ")
    with pytest.raises(ValidationError):
        engagement.add_comment(store, publish_id, actor=reader, body="龙" * 1001)
    with pytest.raises(NotFoundError):
        engagement.add_comment(store, publish_id, actor=reader, body="x", parent_id="CMT-nope")


def test_comment_deletion_permissions(
    store: CommunityStore, author: Actor, reader: Actor, admin: Actor, published: dict
) -> None:
    publish_id = _pid(published)
    by_reader = engagement.add_comment(store, publish_id, actor=reader, body="一楼")
    stranger = Actor(user_id="u-stranger", display_name="路人")
    with pytest.raises(PermissionDeniedError):
        engagement.delete_comment(store, by_reader["id"], actor=stranger)
    # 发布物主人可以删自己楼下的评论
    assert engagement.delete_comment(store, by_reader["id"], actor=author)["deleted"] is True
    another = engagement.add_comment(store, publish_id, actor=reader, body="二楼")
    assert engagement.delete_comment(store, another["id"], actor=admin)["deleted"] is True


def test_comments_on_delisted_strategy_are_closed(
    store: CommunityStore, author: Actor, reader: Actor, published: dict
) -> None:
    publish_id = _pid(published)
    publishing.delist_strategy(store, publish_id, actor=author)
    with pytest.raises(NotFoundError):
        engagement.add_comment(store, publish_id, actor=reader, body="还能买吗")


def test_follow_and_unfollow(store: CommunityStore, author: Actor, reader: Actor) -> None:
    result = engagement.follow(store, author.user_id, actor=reader)
    assert result == {
        "followee_id": author.user_id,
        "following": True,
        "changed": True,
        "followers": 1,
    }
    assert engagement.follow(store, author.user_id, actor=reader)["changed"] is False
    assert store.list_following(reader.user_id) == [author.user_id]
    assert engagement.unfollow(store, author.user_id, actor=reader)["followers"] == 0


def test_cannot_follow_yourself(store: CommunityStore, reader: Actor) -> None:
    with pytest.raises(ConflictError):
        engagement.follow(store, reader.user_id, actor=reader)


def test_feed_scopes(store: CommunityStore, author: Actor, reader: Actor, published: dict) -> None:
    publish_id = _pid(published)
    engagement.star(store, publish_id, actor=reader)
    engagement.follow(store, author.user_id, actor=reader)
    everything = engagement.feed(store, actor=reader, scope="all")
    assert {item["verb"] for item in everything} == {"published", "starred", "followed"}
    following = engagement.feed(store, actor=reader, scope="following")
    assert [item["actor_id"] for item in following] == [author.user_id]
    mine = engagement.feed(store, actor=reader, scope="mine")
    assert {item["verb"] for item in mine} == {"starred", "followed"}
    with pytest.raises(ValidationError):
        engagement.feed(store, actor=reader, scope="宇宙")
    with pytest.raises(ValidationError):
        engagement.feed(store, actor=None, scope="following")


def test_feed_of_a_user_following_nobody_is_empty(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    assert engagement.feed(store, actor=reader, scope="following") == []


def test_recount_repairs_counter_drift(
    store: CommunityStore, admin: Actor, reader: Actor, published: dict
) -> None:
    """计数是缓存，明细才是真相：直接改坏计数后能重算回来。"""
    publish_id = _pid(published)
    engagement.star(store, publish_id, actor=reader)
    store.conn.execute(
        "UPDATE published_strategies SET stars = 999 WHERE publish_id = ?", (publish_id,)
    )
    store.conn.commit()
    assert engagement.recount(store, publish_id, actor=admin) == {
        "stars": 1,
        "clones": 0,
        "comments_count": 0,
    }
    assert store.get_publish(publish_id)["stars"] == 1


def test_recount_is_admin_only(store: CommunityStore, reader: Actor, published: dict) -> None:
    with pytest.raises(PermissionDeniedError):
        engagement.recount(store, _pid(published), actor=reader)


def test_engagement_targets_must_be_visible(
    store: CommunityStore, reader: Actor, author: Actor
) -> None:
    hidden = publishing.publish_strategy(
        store, actor=author, payload=valid_payload(visibility="private")
    )
    with pytest.raises(NotFoundError):
        engagement.star(store, _pid(hidden), actor=reader)
