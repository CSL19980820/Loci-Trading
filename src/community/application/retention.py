"""社区库的保留期清理：动态流 / 榜单快照 / 当日信号广播。

**只清可重建的派生数据**。社区库里绝大多数行是用户作品，删一行 = 抹掉一个人
的策略或一段讨论，备份优先级与 ``palace.db`` 同级（见 ``infrastructure/schema``
模块头）。因此本模块**永不**碰 ``published_strategies`` / ``published_versions``
/ ``strategy_comments`` / ``strategy_stars`` / ``strategy_clones`` /
``subscriptions`` / ``follows``——那四类的清理需求应该被拒绝，不是被实现。

三张能清的表，以及各自为什么能清：

- ``activity_feed`` —— 「谁发了什么」的时间线。它是**只追加**的展示缓存，
  前端只翻最近几屏；两周前的动态没人看，也不构成任何事实（真相在
  ``published_*`` 与 ``strategy_comments``）。
- ``leaderboard_snapshots`` —— ``rebuild_leaderboard`` 能整表重算，
  存下来只为「当天榜首是谁」可回看。
- ``signal_broadcasts`` —— 作者当日信号，一天一条，订阅者当天拉走就完事。
  **但每个 publish_id 至少保底最近 1 条**：订阅页要显示「这个策略最近一次
  发的信号是什么」，全删光会让一个长期没发信号的策略看起来像从没发过。

时间闸：``activity_feed.created_at`` 是带偏移的 ISO 串（``domain.models.now_iso``），
必须走 ``julianday()``；``as_of_date`` / ``trade_date`` 是纯 ``YYYY-MM-DD``，
直接串比即可（理由见 ``src.shared.sqlite_retention`` 模块头）。

调用方是 ``ops`` 的系统级 prune 执行器（community.db 跨租户全局唯一，只能在
主租户跑一份，否则 N 个租户会同时删同一个库）。
"""
from __future__ import annotations

from typing import Any

from src.shared.sqlite_retention import (
    DEFAULT_BATCH,
    age_param,
    age_predicate,
    count_rows,
    delete_in_batches,
    segment,
)

#: 三段默认保留天数。
DEFAULT_FEED_DAYS = 15
DEFAULT_BOARD_DAYS = 15
DEFAULT_BROADCAST_DAYS = 15

#: 每个 publish_id 的信号广播保底条数。见模块头。
DEFAULT_BROADCAST_KEEP_MIN = 1


def _purge_feed(conn: Any, days: int, batch: int, pause: float) -> dict[str, Any]:
    kept_before = count_rows(conn, "activity_feed")
    if days <= 0:
        return {"deleted": 0, "kept": kept_before, "skipped": "未启用"}
    deleted = delete_in_batches(
        conn,
        "activity_feed",
        where=age_predicate("created_at"),
        params=(age_param(days),),
        batch=batch,
        pause=pause,
    )
    return {"deleted": deleted, "kept": max(0, kept_before - deleted), "keep_days": days}


def _purge_board(conn: Any, days: int, batch: int, pause: float) -> dict[str, Any]:
    kept_before = count_rows(conn, "leaderboard_snapshots")
    if days <= 0:
        return {"deleted": 0, "kept": kept_before, "skipped": "未启用"}
    deleted = delete_in_batches(
        conn,
        "leaderboard_snapshots",
        where=age_predicate("as_of_date", date_only=True),
        params=(age_param(days, date_only=True),),
        batch=batch,
        pause=pause,
    )
    return {"deleted": deleted, "kept": max(0, kept_before - deleted), "keep_days": days}


def _purge_broadcasts(
    conn: Any, days: int, keep_min: int, batch: int, pause: float
) -> dict[str, Any]:
    """按日期清，但每个 ``publish_id`` 保底最近 ``keep_min`` 条。"""
    kept_before = count_rows(conn, "signal_broadcasts")
    if days <= 0:
        return {"deleted": 0, "kept": kept_before, "skipped": "未启用"}
    floor = max(0, int(keep_min))
    size = max(1, int(batch))
    subquery = (
        "SELECT rowid FROM ("
        " SELECT rowid AS rowid, trade_date AS trade_date,"
        " ROW_NUMBER() OVER (PARTITION BY publish_id ORDER BY trade_date DESC) AS rn"
        " FROM signal_broadcasts"
        f" ) WHERE rn > ? AND trade_date < ? LIMIT {size}"
    )
    deleted = delete_in_batches(
        conn,
        "signal_broadcasts",
        subquery=subquery,
        params=(floor, age_param(days, date_only=True)),
        batch=size,
        pause=pause,
    )
    return {
        "deleted": deleted,
        "kept": max(0, kept_before - deleted),
        "keep_days": days,
        "keep_min": floor,
    }


def purge_expired(
    store: Any,
    *,
    feed_days: int = DEFAULT_FEED_DAYS,
    board_days: int = DEFAULT_BOARD_DAYS,
    broadcast_days: int = DEFAULT_BROADCAST_DAYS,
    broadcast_keep_min: int = DEFAULT_BROADCAST_KEEP_MIN,
    batch: int = DEFAULT_BATCH,
    pause: float = 0.0,
) -> dict[str, Any]:
    """清 ``activity_feed`` / ``leaderboard_snapshots`` / ``signal_broadcasts``。

    ``store`` 是 ``CommunityStore``（只用它的 ``conn``）。

    **每段各自 try**：一张表删不动（被别的连接锁住、schema 漂移）不该让另外
    两张也不清。失败写进返回值里的 ``error``，由调用方的 job payload 透出。
    """
    conn = getattr(store, "conn", store)
    return {
        "activity_feed": segment(
            "activity_feed", lambda: _purge_feed(conn, feed_days, batch, pause)
        ),
        "leaderboard_snapshots": segment(
            "leaderboard_snapshots", lambda: _purge_board(conn, board_days, batch, pause)
        ),
        "signal_broadcasts": segment(
            "signal_broadcasts",
            lambda: _purge_broadcasts(
                conn, broadcast_days, broadcast_keep_min, batch, pause
            ),
        ),
    }


__all__ = [
    "DEFAULT_BOARD_DAYS",
    "DEFAULT_BROADCAST_DAYS",
    "DEFAULT_BROADCAST_KEEP_MIN",
    "DEFAULT_FEED_DAYS",
    "purge_expired",
]
