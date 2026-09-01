"""社区库保留期：只清可重建的三张表，用户作品一条都不许动。

社区库里绝大多数行是**用户作品**（发布物、版本、评论、收藏、克隆留痕、订阅、
关注），删一行 = 抹掉一个人的策略或一段讨论。所以这套用例一半在验「该清的
清掉了」，另一半在验「不该清的一条没少」——后者才是真正会出事的方向。

``signal_broadcasts`` 另有一条保底：每个 ``publish_id`` 至少留最近 1 条，
否则一个长期没发信号的策略在订阅页会看起来像从没发过。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from src.community import CommunityStore
from src.community.application.retention import purge_expired


def _iso(days_ago: float) -> str:
    """本地带偏移的 ISO 串（与 ``domain.models.now_iso()`` 同格式）。"""
    return (datetime.now().astimezone() - timedelta(days=days_ago)).isoformat(
        timespec="microseconds"
    )


def _legacy_utc(days_ago: float) -> str:
    """历史行的 UTC 裸串。两种格式并存时判定必须一致。"""
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _feed(store: CommunityStore, fid: str, *, created: str) -> None:
    store.conn.execute(
        "INSERT INTO activity_feed(id, actor_id, verb, created_at) VALUES(?,?,?,?)",
        (fid, "u-1", "published", created),
    )
    store.conn.commit()


def _board(store: CommunityStore, board: str, *, as_of: str, rank: int = 1) -> None:
    store.conn.execute(
        "INSERT INTO leaderboard_snapshots(board, as_of_date, rank, publish_id)"
        " VALUES(?,?,?,?)",
        (board, as_of, rank, "P-1"),
    )
    store.conn.commit()


def _broadcast(store: CommunityStore, publish_id: str, *, trade_date: str) -> str:
    bid = f"B-{publish_id}-{trade_date}"
    store.conn.execute(
        "INSERT INTO signal_broadcasts(id, publish_id, trade_date, created_at)"
        " VALUES(?,?,?,?)",
        (bid, publish_id, trade_date, _iso(0)),
    )
    store.conn.commit()
    return bid


def _count(store: CommunityStore, table: str) -> int:
    return int(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# --------------------------------------------------------------------------
# 1. 三张可重建的表
# --------------------------------------------------------------------------


def test_activity_feed_is_truncated_at_fifteen_days(store: CommunityStore) -> None:
    _feed(store, "F-old", created=_iso(90))
    _feed(store, "F-edge", created=_iso(16))
    _feed(store, "F-new", created=_iso(2))

    result = purge_expired(store, feed_days=15)

    assert result["activity_feed"]["deleted"] == 2
    alive = {r[0] for r in store.conn.execute("SELECT id FROM activity_feed")}
    assert alive == {"F-new"}


def test_feed_age_gate_handles_mixed_timestamp_formats(store: CommunityStore) -> None:
    """字符串比会差 8 小时；两种格式的同龄行必须同进同出。"""
    _feed(store, "F-legacy-fresh", created=_legacy_utc(1))
    _feed(store, "F-legacy-old", created=_legacy_utc(90))
    _feed(store, "F-modern-fresh", created=_iso(1))
    _feed(store, "F-modern-old", created=_iso(90))

    purge_expired(store, feed_days=15)

    alive = {r[0] for r in store.conn.execute("SELECT id FROM activity_feed")}
    assert alive == {"F-legacy-fresh", "F-modern-fresh"}


def test_leaderboard_snapshots_are_truncated(store: CommunityStore) -> None:
    """榜单快照可由 ``rebuild_leaderboard`` 整表重算，存下来只为回看当天视角。"""
    _board(store, "main", as_of=_day(90))
    _board(store, "sharpe", as_of=_day(3))

    result = purge_expired(store, board_days=15)

    assert result["leaderboard_snapshots"]["deleted"] == 1
    alive = {r[0] for r in store.conn.execute("SELECT board FROM leaderboard_snapshots")}
    assert alive == {"sharpe"}


def test_broadcasts_keep_at_least_one_per_publish(store: CommunityStore) -> None:
    """全部超龄时，每个 publish_id 仍要留下最近的那一条。"""
    for days in (90, 60, 30):
        _broadcast(store, "P-1", trade_date=_day(days))
    _broadcast(store, "P-2", trade_date=_day(400))

    result = purge_expired(store, broadcast_days=15, broadcast_keep_min=1)

    assert result["signal_broadcasts"]["deleted"] == 2
    rows = {
        (r[0], r[1])
        for r in store.conn.execute("SELECT publish_id, trade_date FROM signal_broadcasts")
    }
    assert rows == {("P-1", _day(30)), ("P-2", _day(400))}


def test_broadcast_keep_min_zero_removes_everything_stale(store: CommunityStore) -> None:
    """显式配 0 时才允许清空——但那不是默认值。"""
    _broadcast(store, "P-1", trade_date=_day(90))

    purge_expired(store, broadcast_days=15, broadcast_keep_min=0)

    assert _count(store, "signal_broadcasts") == 0


def test_fresh_broadcasts_survive(store: CommunityStore) -> None:
    _broadcast(store, "P-1", trade_date=_day(1))
    _broadcast(store, "P-1", trade_date=_day(2))

    result = purge_expired(store, broadcast_days=15)

    assert result["signal_broadcasts"]["deleted"] == 0


# --------------------------------------------------------------------------
# 2. 不该清的东西（这一段才是真正会出事的方向）
# --------------------------------------------------------------------------


def test_user_work_is_never_touched(
    store: CommunityStore, published: dict[str, Any], reader: Any
) -> None:
    """发布物 / 版本 / 评论 / 收藏 / 订阅 / 关注：一条都不许少。"""
    from src.community.application import engagement, subscribe

    publish_id = published["strategy"]["publish_id"]
    engagement.star(store, actor=reader, publish_id=publish_id)
    engagement.add_comment(store, actor=reader, publish_id=publish_id, body="不错")
    subscribe.subscribe(store, actor=reader, publish_id=publish_id)
    before = store.stats()

    purge_expired(store, feed_days=1, board_days=1, broadcast_days=1)

    after = store.stats()
    for table in (
        "published_strategies",
        "published_versions",
        "strategy_comments",
        "strategy_stars",
        "strategy_clones",
        "subscriptions",
        "follows",
    ):
        assert after[table] == before[table], f"{table} 被清理动过了"


def test_zero_days_disables_each_segment(store: CommunityStore) -> None:
    """0 是「关闭该段」，不是「全部删光」。"""
    _feed(store, "F-old", created=_iso(900))
    _board(store, "main", as_of=_day(900))
    _broadcast(store, "P-1", trade_date=_day(900))
    _broadcast(store, "P-1", trade_date=_day(901))

    result = purge_expired(store, feed_days=0, board_days=0, broadcast_days=0)

    assert result["activity_feed"]["skipped"] == "未启用"
    assert _count(store, "activity_feed") == 1
    assert _count(store, "leaderboard_snapshots") == 1
    assert _count(store, "signal_broadcasts") == 2


# --------------------------------------------------------------------------
# 3. 健壮性
# --------------------------------------------------------------------------


def test_one_failing_segment_does_not_take_down_the_round(
    store: CommunityStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.community.application import retention

    _feed(store, "F-old", created=_iso(90))
    _board(store, "main", as_of=_day(90))

    def boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(retention, "_purge_feed", boom)
    result = purge_expired(store)

    assert "database is locked" in result["activity_feed"]["error"]
    assert result["leaderboard_snapshots"]["deleted"] == 1


def test_batched_delete_clears_everything_due(store: CommunityStore) -> None:
    for i in range(43):
        _feed(store, f"F-{i}", created=_iso(90))

    result = purge_expired(store, feed_days=15, batch=6)

    assert result["activity_feed"]["deleted"] == 43
    assert _count(store, "activity_feed") == 0


def test_payload_reports_per_table_numbers(store: CommunityStore) -> None:
    result = purge_expired(store)

    assert set(result) == {
        "activity_feed",
        "leaderboard_snapshots",
        "signal_broadcasts",
    }
    for name, entry in result.items():
        assert entry["table"] == name
        assert "deleted" in entry and "ms" in entry
