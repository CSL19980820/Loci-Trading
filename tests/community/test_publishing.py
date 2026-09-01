"""发布用例单测：上架清单接线、版本冻结、权限、可见性、克隆 bundle。"""

from __future__ import annotations

import sqlite3

import pytest

from src.community import CommunityStore
from src.community.application import publishing
from src.community.domain.models import (
    Actor,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    PublishRuleError,
)
from tests.community.conftest import valid_payload


def test_publish_creates_strategy_and_first_frozen_version(
    store: CommunityStore, author: Actor
) -> None:
    result = publishing.publish_strategy(store, actor=author, payload=valid_payload())
    strategy = result["strategy"]
    assert strategy["owner_user_id"] == author.user_id
    assert strategy["owner_name"] == "老王"
    assert strategy["status"] == "listed"
    assert strategy["current_version"] == 1
    assert strategy["tags"] == ["打板", "龙头"]
    assert result["version"]["version"] == 1
    assert len(result["version"]["content_sha256"]) == 64
    # 回测证据冻进版本 manifest，日后能解释「当时凭什么给上架」
    assert result["version"]["manifest"]["backtest"]["trades"] == 42


def test_publish_writes_activity_feed(store: CommunityStore, author: Actor) -> None:
    publishing.publish_strategy(store, actor=author, payload=valid_payload())
    feed = store.list_feed()
    assert [item["verb"] for item in feed] == ["published"]
    assert feed[0]["actor_id"] == author.user_id


def test_private_publish_stays_out_of_the_feed(store: CommunityStore, author: Actor) -> None:
    """私有发布不该广播出去。"""
    publishing.publish_strategy(store, actor=author, payload=valid_payload(visibility="private"))
    assert store.list_feed() == []


def test_publish_rejects_payload_failing_the_checklist(
    store: CommunityStore, author: Actor
) -> None:
    with pytest.raises(PublishRuleError) as excinfo:
        publishing.publish_strategy(store, actor=author, payload=valid_payload(backtest=None))
    assert excinfo.value.violations[0]["code"] == "backtest_required"
    # 清单没过，一行都不许落库
    assert store.stats()["published_strategies"] == 0


def test_duplicate_slug_for_same_owner_conflicts(store: CommunityStore, author: Actor) -> None:
    publishing.publish_strategy(store, actor=author, payload=valid_payload(slug="qianlong"))
    with pytest.raises(ConflictError):
        publishing.publish_strategy(store, actor=author, payload=valid_payload(slug="qianlong"))


def test_same_slug_is_fine_for_another_owner(
    store: CommunityStore, author: Actor, reader: Actor
) -> None:
    publishing.publish_strategy(store, actor=author, payload=valid_payload(slug="qianlong"))
    other = publishing.publish_strategy(store, actor=reader, payload=valid_payload(slug="qianlong"))
    assert other["strategy"]["owner_user_id"] == reader.user_id


def test_new_version_freezes_the_previous_one(
    store: CommunityStore, author: Actor, published: dict
) -> None:
    publish_id = published["strategy"]["publish_id"]
    result = publishing.publish_new_version(
        store,
        publish_id,
        actor=author,
        payload={
            "source_text": "v2 code",
            "release_notes": "换参数",
            "backtest": valid_payload()["backtest"],
        },
    )
    assert result["version"]["version"] == 2
    assert result["strategy"]["current_version"] == 2
    versions = store.list_versions(publish_id)
    assert [item["version"] for item in versions] == [2, 1]
    # 上架即冻结：改写旧版会被库层触发器打回
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "UPDATE published_versions SET source_text = 'tampered' WHERE publish_id = ? AND version = 1",
            (publish_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "DELETE FROM published_versions WHERE publish_id = ? AND version = 1", (publish_id,)
        )


def test_only_owner_can_publish_a_new_version(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    with pytest.raises(PermissionDeniedError):
        publishing.publish_new_version(
            store,
            published["strategy"]["publish_id"],
            actor=reader,
            payload={"source_text": "偷改", "backtest": valid_payload()["backtest"]},
        )


def test_admin_may_act_on_someone_elses_publication(
    store: CommunityStore, admin: Actor, published: dict
) -> None:
    result = publishing.delist_strategy(store, published["strategy"]["publish_id"], actor=admin)
    assert result["strategy"]["status"] == "delisted"


def test_delist_hides_from_others_but_not_from_owner(
    store: CommunityStore, author: Actor, reader: Actor, published: dict
) -> None:
    publish_id = published["strategy"]["publish_id"]
    result = publishing.delist_strategy(store, publish_id, actor=author)
    assert result["changed"] is True
    assert result["strategy"]["delisted_at"]
    # 幂等：再下架一次不报错也不重复记
    assert publishing.delist_strategy(store, publish_id, actor=author)["changed"] is False
    with pytest.raises(NotFoundError):
        publishing.detail(store, publish_id, actor=reader)
    assert publishing.detail(store, publish_id, actor=author)["strategy"]["status"] == "delisted"
    # 数据仍在：已克隆的人还要能对账
    assert store.list_versions(publish_id)
    assert (
        publishing.relist_strategy(store, publish_id, actor=author)["strategy"]["status"]
        == "listed"
    )


def test_private_strategy_is_404_for_strangers(
    store: CommunityStore, author: Actor, reader: Actor
) -> None:
    """看不见的一律 404，不用 403——403 会泄露「这个 id 确实存在」。"""
    result = publishing.publish_strategy(
        store, actor=author, payload=valid_payload(visibility="private")
    )
    publish_id = result["strategy"]["publish_id"]
    with pytest.raises(NotFoundError):
        publishing.detail(store, publish_id, actor=reader)
    with pytest.raises(NotFoundError):
        publishing.detail(store, publish_id, actor=None)
    assert publishing.detail(store, publish_id, actor=author)["viewer"]["can_edit"] is True


def test_detail_counts_views_and_reports_viewer_state(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    publish_id = published["strategy"]["publish_id"]
    first = publishing.detail(store, publish_id, actor=reader, count_view=True)
    assert first["strategy"]["views"] == 1
    assert first["viewer"] == {"starred": False, "subscribed": False, "can_edit": False}
    second = publishing.detail(store, publish_id, actor=reader, count_view=False)
    assert second["strategy"]["views"] == 1


def test_non_owner_only_sees_current_version_source(
    store: CommunityStore, author: Actor, reader: Actor, published: dict
) -> None:
    publish_id = published["strategy"]["publish_id"]
    publishing.publish_new_version(
        store,
        publish_id,
        actor=author,
        payload={"source_text": "v2 code", "backtest": valid_payload()["backtest"]},
    )
    as_owner = publishing.list_versions(store, publish_id, actor=author)
    assert all(item["source_text"] for item in as_owner)
    as_stranger = publishing.list_versions(store, publish_id, actor=reader)
    by_version = {item["version"]: item for item in as_stranger}
    assert by_version[2]["source_text"] == "v2 code"
    assert by_version[1]["source_text"] == ""


def test_update_listing_touches_text_only(
    store: CommunityStore, author: Actor, published: dict
) -> None:
    publish_id = published["strategy"]["publish_id"]
    updated = publishing.update_listing(
        store, publish_id, actor=author, payload={"title": "潜龙 v2", "tags": ["打板"]}
    )
    assert updated["title"] == "潜龙 v2"
    assert updated["tags"] == ["打板"]
    assert updated["current_version"] == 1
    # 文案仍然过引流检查
    with pytest.raises(PublishRuleError):
        publishing.update_listing(
            store, publish_id, actor=author, payload={"summary": "加微信 quant888 领代码"}
        )


def test_visibility_switch_requires_ownership(
    store: CommunityStore, author: Actor, reader: Actor, published: dict
) -> None:
    publish_id = published["strategy"]["publish_id"]
    assert (
        publishing.set_visibility(store, publish_id, actor=author, visibility="unlisted")[
            "visibility"
        ]
        == "unlisted"
    )
    with pytest.raises(PermissionDeniedError):
        publishing.set_visibility(store, publish_id, actor=reader, visibility="public")


def test_clone_bundle_is_self_contained(
    store: CommunityStore, reader: Actor, published: dict
) -> None:
    """bundle 里必须带足导入所需的一切，且**不写任何别人的库**。"""
    publish_id = published["strategy"]["publish_id"]
    bundle = publishing.clone_bundle(store, publish_id, actor=reader)
    assert bundle["source_text"]
    assert bundle["entry_timing"] == "next_open"
    assert bundle["params"] == {"top_n": 5}
    assert bundle["imported_from"] == "community"
    assert bundle["content_sha256"] == store.get_version(publish_id)["content_sha256"]
    # 社区库只有社区自己的表，导入是客户端那边的事
    assert store.stats()["strategy_clones"] == 0


def test_clone_bundle_rejects_unknown_version(store: CommunityStore, published: dict) -> None:
    with pytest.raises(NotFoundError):
        publishing.clone_bundle(store, published["strategy"]["publish_id"], version=99)


def test_preflight_never_writes(store: CommunityStore) -> None:
    assert publishing.preflight(valid_payload())["ok"] is True
    bad = publishing.preflight(valid_payload(entry_timing=""))
    assert bad["ok"] is False
    assert bad["violations"][0]["code"] == "entry_timing_required"
    assert store.stats()["published_strategies"] == 0
