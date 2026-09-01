"""community.db：跟单订阅与当日信号广播。

**合规红线（写在最显眼处）：只推信号，不自动下单。**
``subscriptions.mode`` 只有 ``signal_only``，DDL 里有 CHECK 兜底。订阅者能做的
只有「拉到作者当天发的信号快照」；要不要买、买多少、在哪个账户买，全部发生在
订阅者自己的账本里，社区一步都不参与。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from src.community.domain.models import ConflictError, NotFoundError
from src.community.infrastructure.store_helpers import (
    dumps,
    json_columns,
    new_id,
    row_to_dict,
)


class CommunitySubscriptionMixin:
    def _subscription_row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = row_to_dict(row)
        data["notify_channels"] = _channels(data.pop("notify_channels", "[]"))
        return data

    def subscribe(
        self,
        publish_id: str,
        user_id: str,
        *,
        notify_channels: list[str] | None = None,
        mode: str = "signal_only",
    ) -> dict[str, Any]:
        """订阅。重复订阅是幂等的（更新通知渠道并解除暂停）。"""
        if mode != "signal_only":
            raise ConflictError("只支持 signal_only：社区不做自动下单，见模块 docstring")
        now = self._now()
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO subscriptions(publish_id, user_id, mode, notify_channels, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(publish_id, user_id) DO UPDATE SET
                        notify_channels=excluded.notify_channels,
                        paused_at=''
                    """,
                    (publish_id, user_id, mode, dumps(list(notify_channels or [])), now),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"订阅失败：{exc}") from exc
        return self.get_subscription(publish_id, user_id) or dict()

    def unsubscribe(self, publish_id: str, user_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM subscriptions WHERE publish_id = ? AND user_id = ?",
                (publish_id, user_id),
            )
            return cursor.rowcount > 0

    def pause_subscription(
        self, publish_id: str, user_id: str, *, paused: bool = True
    ) -> dict[str, Any]:
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE subscriptions SET paused_at = ? WHERE publish_id = ? AND user_id = ?",
                (self._now() if paused else "", publish_id, user_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError("订阅不存在")
        return self.get_subscription(publish_id, user_id) or dict()

    def get_subscription(self, publish_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM subscriptions WHERE publish_id = ? AND user_id = ?",
            (publish_id, user_id),
        ).fetchone()
        return self._subscription_row(row)

    def list_subscriptions(
        self, user_id: str, *, active_only: bool = False
    ) -> list[dict[str, Any]]:
        """某人的订阅列表，带上发布物标题/作者，省得前端再挨个查详情。"""
        sql = (
            "SELECT s.*, p.title, p.owner_user_id, p.owner_name, p.status, p.current_version"
            " FROM subscriptions s"
            " LEFT JOIN published_strategies p ON p.publish_id = s.publish_id"
            " WHERE s.user_id = ?"
        )
        if active_only:
            sql += " AND s.paused_at = ''"
        sql += " ORDER BY s.created_at DESC"
        rows = self.conn.execute(sql, (user_id,)).fetchall()
        return [item for item in (self._subscription_row(row) for row in rows) if item]

    def count_subscribers(self, publish_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE publish_id = ? AND paused_at = ''",
            (publish_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_subscribers(self, publish_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT user_id FROM subscriptions WHERE publish_id = ? AND paused_at = ''",
            (publish_id,),
        ).fetchall()
        return [str(row["user_id"]) for row in rows]

    # ------------------------------------------------------------ 信号广播
    def put_broadcast(
        self, publish_id: str, *, trade_date: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """写入作者当日信号快照（一天一条，重发覆盖）。

        覆盖而不是追加：同一天多次重算属于修正，订阅者要看到的是最终那一份。
        历史留痕不在这张表——要审计「作者当时到底发了什么」，看 ledger 的候选记录。
        """
        now = self._now()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO signal_broadcasts(id, publish_id, trade_date, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(publish_id, trade_date) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (new_id("SIG"), publish_id, trade_date, dumps(dict(payload)), now),
            )
        return self.get_broadcast(publish_id, trade_date) or dict()

    def get_broadcast(self, publish_id: str, trade_date: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM signal_broadcasts WHERE publish_id = ? AND trade_date = ?",
            (publish_id, trade_date),
        ).fetchone()
        if row is None:
            return None
        return json_columns(row_to_dict(row), {"payload_json": ("payload", dict())})

    def latest_broadcast(self, publish_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM signal_broadcasts WHERE publish_id = ? ORDER BY trade_date DESC LIMIT 1",
            (publish_id,),
        ).fetchone()
        if row is None:
            return None
        return json_columns(row_to_dict(row), {"payload_json": ("payload", dict())})

    def list_broadcasts_for(
        self, publish_ids: list[str], *, trade_date: str = "", limit: int = 200
    ) -> list[dict[str, Any]]:
        """批量拉订阅者关心的那些发布物的信号（``trade_date`` 为空则取各自最新）。"""
        if not publish_ids:
            return []
        placeholders = ", ".join("?" for _ in publish_ids)
        params: list[Any] = list(publish_ids)
        if trade_date:
            sql = (
                f"SELECT * FROM signal_broadcasts WHERE publish_id IN ({placeholders})"
                " AND trade_date = ? ORDER BY publish_id ASC LIMIT ?"
            )
            params.extend([trade_date, int(limit)])
        else:
            sql = (
                f"SELECT b.* FROM signal_broadcasts b JOIN ("
                f"SELECT publish_id, MAX(trade_date) AS d FROM signal_broadcasts"
                f" WHERE publish_id IN ({placeholders}) GROUP BY publish_id"
                ") latest ON latest.publish_id = b.publish_id AND latest.d = b.trade_date"
                " ORDER BY b.publish_id ASC LIMIT ?"
            )
            params.append(int(limit))
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [
            json_columns(row_to_dict(row), {"payload_json": ("payload", dict())}) for row in rows
        ]


def _channels(raw: Any) -> list[str]:
    from src.community.infrastructure.store_helpers import loads

    value = loads(raw, [])
    return [str(item) for item in value] if isinstance(value, list) else []
