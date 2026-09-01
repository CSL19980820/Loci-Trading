"""community.db：收藏、克隆留痕、评论、关注、动态流。

计数列（``stars`` / ``clones`` / ``comments_count``）是**缓存**，真相在明细表：
每次增减都在同一个事务里更新，出现漂移时 ``recount`` 能整行重算回来。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.community.domain.models import ConflictError, NotFoundError
from src.community.infrastructure.store_helpers import new_id, row_to_dict


class CommunitySocialMixin:
    # ---------------------------------------------------------------- 收藏
    def add_star(self, publish_id: str, user_id: str) -> bool:
        """收藏。已收藏过返回 False（幂等，不报错——用户只是点快了两下）。"""
        with self._transaction(immediate=True) as cursor:
            try:
                cursor.execute(
                    "INSERT INTO strategy_stars(publish_id, user_id, created_at) VALUES (?, ?, ?)",
                    (publish_id, user_id, self._now()),
                )
            except sqlite3.IntegrityError:
                return False
            cursor.execute(
                "UPDATE published_strategies SET stars = stars + 1 WHERE publish_id = ?",
                (publish_id,),
            )
        return True

    def remove_star(self, publish_id: str, user_id: str) -> bool:
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "DELETE FROM strategy_stars WHERE publish_id = ? AND user_id = ?",
                (publish_id, user_id),
            )
            if cursor.rowcount == 0:
                return False
            cursor.execute(
                "UPDATE published_strategies SET stars = MAX(0, stars - 1) WHERE publish_id = ?",
                (publish_id,),
            )
        return True

    def has_starred(self, publish_id: str, user_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM strategy_stars WHERE publish_id = ? AND user_id = ?",
            (publish_id, user_id),
        ).fetchone()
        return row is not None

    def list_starred(self, user_id: str, *, limit: int = 100) -> list[str]:
        rows = self.conn.execute(
            "SELECT publish_id FROM strategy_stars WHERE user_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
        return [str(row["publish_id"]) for row in rows]

    # ---------------------------------------------------------------- 克隆
    def record_clone(self, publish_id: str, *, version: int, user_id: str) -> dict[str, Any]:
        """记一次克隆并加计数。

        **只记留痕，不写对方的租户库。** 社区不知道也不该知道别人 palace.db 在哪；
        api 把 bundle 返回给客户端，导入是对方自己那边的事。
        """
        clone_id = new_id("CLN")
        now = self._now()
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "INSERT INTO strategy_clones(id, publish_id, version, user_id, cloned_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (clone_id, publish_id, int(version), user_id, now),
            )
            cursor.execute(
                "UPDATE published_strategies SET clones = clones + 1 WHERE publish_id = ?",
                (publish_id,),
            )
        return {"id": clone_id, "publish_id": publish_id, "version": int(version), "cloned_at": now}

    def count_clones(self, publish_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_clones WHERE publish_id = ?", (publish_id,)
        ).fetchone()
        return int(row["n"]) if row else 0

    # ---------------------------------------------------------------- 评论
    def add_comment(
        self, publish_id: str, *, user_id: str, user_name: str, body: str, parent_id: str = ""
    ) -> dict[str, Any]:
        if parent_id:
            parent = self.conn.execute(
                "SELECT publish_id FROM strategy_comments WHERE id = ?", (parent_id,)
            ).fetchone()
            if parent is None:
                raise NotFoundError(f"父评论不存在：{parent_id}")
            if str(parent["publish_id"]) != publish_id:
                raise ConflictError("父评论不属于这个发布物")
        comment_id = new_id("CMT")
        now = self._now()
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                """
                INSERT INTO strategy_comments(
                    id, publish_id, user_id, user_name, body, parent_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (comment_id, publish_id, user_id, user_name, body, parent_id, now),
            )
            cursor.execute(
                "UPDATE published_strategies SET comments_count = comments_count + 1"
                " WHERE publish_id = ?",
                (publish_id,),
            )
        return self.get_comment(comment_id) or dict()

    def get_comment(self, comment_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM strategy_comments WHERE id = ?", (comment_id,)
        ).fetchone()
        return row_to_dict(row) if row else None

    def list_comments(
        self, publish_id: str, *, include_deleted: bool = True, limit: int = 200
    ) -> list[dict[str, Any]]:
        """按时间正序（楼层）。软删的行默认仍返回，由上层决定怎么渲染占位。"""
        sql = "SELECT * FROM strategy_comments WHERE publish_id = ?"
        if not include_deleted:
            sql += " AND deleted_at = ''"
        sql += " ORDER BY created_at ASC, id ASC LIMIT ?"
        rows = self.conn.execute(sql, (publish_id, int(limit))).fetchall()
        return [row_to_dict(row) for row in rows]

    def soft_delete_comment(self, comment_id: str) -> dict[str, Any]:
        """软删：正文留在库里但对外只回占位，楼层与父子关系不塌。"""
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "UPDATE strategy_comments SET deleted_at = ? WHERE id = ? AND deleted_at = ''",
                (self._now(), comment_id),
            )
            changed = cursor.rowcount
            if changed:
                cursor.execute(
                    "UPDATE published_strategies SET comments_count = MAX(0, comments_count - 1)"
                    " WHERE publish_id = (SELECT publish_id FROM strategy_comments WHERE id = ?)",
                    (comment_id,),
                )
        found = self.get_comment(comment_id)
        if found is None:
            raise NotFoundError(f"评论不存在：{comment_id}")
        return found

    # ---------------------------------------------------------------- 关注
    def follow(self, follower_id: str, followee_id: str) -> bool:
        if follower_id == followee_id:
            raise ConflictError("不能关注自己")
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "INSERT INTO follows(follower_id, followee_id, created_at) VALUES (?, ?, ?)",
                    (follower_id, followee_id, self._now()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def unfollow(self, follower_id: str, followee_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
                (follower_id, followee_id),
            )
            return cursor.rowcount > 0

    def list_following(self, follower_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT followee_id FROM follows WHERE follower_id = ? ORDER BY created_at DESC",
            (follower_id,),
        ).fetchall()
        return [str(row["followee_id"]) for row in rows]

    def count_followers(self, user_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM follows WHERE followee_id = ?", (user_id,)
        ).fetchone()
        return int(row["n"]) if row else 0

    def is_following(self, follower_id: str, followee_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
            (follower_id, followee_id),
        ).fetchone()
        return row is not None

    # ---------------------------------------------------------------- 动态流
    def add_feed_item(
        self,
        *,
        actor_id: str,
        actor_name: str = "",
        verb: str,
        object_type: str = "",
        object_id: str = "",
        object_title: str = "",
    ) -> dict[str, Any]:
        item_id = new_id("ACT")
        now = self._now()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO activity_feed(
                    id, actor_id, actor_name, verb, object_type, object_id, object_title, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, actor_id, actor_name, verb, object_type, object_id, object_title, now),
            )
        return {
            "id": item_id,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "verb": verb,
            "object_type": object_type,
            "object_id": object_id,
            "object_title": object_title,
            "created_at": now,
        }

    def list_feed(
        self, *, actor_ids: list[str] | None = None, limit: int = 50, before: str = ""
    ) -> list[dict[str, Any]]:
        """动态流。``actor_ids`` 给「只看我关注的人」，为空则是全站广场动态。"""
        clauses: list[str] = []
        params: list[Any] = []
        if actor_ids is not None:
            if not actor_ids:
                return []
            placeholders = ", ".join("?" for _ in actor_ids)
            clauses.append(f"actor_id IN ({placeholders})")
            params.extend(actor_ids)
        if before:
            clauses.append("created_at < ?")
            params.append(before)
        sql = "SELECT * FROM activity_feed"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [row_to_dict(row) for row in rows]

    # ---------------------------------------------------------------- 计数校准
    def recount_engagement(self, publish_id: str) -> dict[str, int]:
        """用明细表重算三个计数列。计数是缓存，明细才是真相。"""
        stars = self.conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_stars WHERE publish_id = ?", (publish_id,)
        ).fetchone()["n"]
        clones = self.conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_clones WHERE publish_id = ?", (publish_id,)
        ).fetchone()["n"]
        comments = self.conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_comments WHERE publish_id = ? AND deleted_at = ''",
            (publish_id,),
        ).fetchone()["n"]
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE published_strategies SET stars = ?, clones = ?, comments_count = ?"
                " WHERE publish_id = ?",
                (int(stars), int(clones), int(comments), publish_id),
            )
        return {"stars": int(stars), "clones": int(clones), "comments_count": int(comments)}
