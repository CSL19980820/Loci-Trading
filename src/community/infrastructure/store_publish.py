"""community.db：发布物与冻结版本的读写。"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from src.community.domain.models import ConflictError, FrozenVersionError, NotFoundError
from src.community.infrastructure.store_helpers import (
    content_hash,
    dumps,
    json_columns,
    new_id,
    row_to_dict,
)

#: 允许被 ``update_publish`` 改写的列。白名单挡住「顺手改 owner / 改计数」。
_MUTABLE_COLUMNS = ("title", "summary", "kind", "tags_json", "visibility", "owner_name")


class CommunityPublishMixin:
    def _publish_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = row_to_dict(row)
        return json_columns(data, {"tags_json": ("tags", [])})

    def _version_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = row_to_dict(row)
        return json_columns(
            data, {"params_json": ("params", dict()), "manifest_json": ("manifest", dict())}
        )

    def create_publish(
        self,
        *,
        owner_user_id: str,
        owner_name: str,
        slug: str,
        title: str,
        summary: str = "",
        kind: str = "screen",
        entry_timing: str,
        visibility: str = "public",
        tags: list[str] | None = None,
        source_text: str = "",
        params: Mapping[str, Any] | None = None,
        manifest: Mapping[str, Any] | None = None,
        release_notes: str = "",
    ) -> dict[str, Any]:
        """建发布物 + 冻结第 1 版，**一个事务**里完成。

        分两个事务写过一次就会有「有发布物但没有版本」的孤儿：广场卡片点进去 404，
        而作者以为发成功了。
        """
        now = self._now()
        publish_id = new_id("PUB")
        version_id = new_id("PVR")
        row = {
            "publish_id": publish_id,
            "owner_user_id": owner_user_id,
            "owner_name": owner_name,
            "slug": slug,
            "title": title,
            "summary": summary,
            "kind": kind,
            "entry_timing": entry_timing,
            "visibility": visibility,
            "status": "listed",
            "current_version": 1,
            "tags_json": dumps(list(tags or [])),
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        }
        try:
            with self._transaction(immediate=True) as cursor:
                cursor.execute(
                    """
                    INSERT INTO published_strategies(
                        publish_id, owner_user_id, owner_name, slug, title, summary, kind,
                        entry_timing, visibility, status, current_version, tags_json,
                        created_at, updated_at, published_at
                    ) VALUES (
                        :publish_id, :owner_user_id, :owner_name, :slug, :title, :summary, :kind,
                        :entry_timing, :visibility, :status, :current_version, :tags_json,
                        :created_at, :updated_at, :published_at
                    )
                    """,
                    row,
                )
                cursor.execute(
                    """
                    INSERT INTO published_versions(
                        id, publish_id, version, source_text, params_json, manifest_json,
                        release_notes, content_sha256, created_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        publish_id,
                        source_text,
                        dumps(dict(params or {})),
                        dumps(dict(manifest or {})),
                        release_notes,
                        content_hash(source_text, params),
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "idx_pub_owner_slug" in str(exc) or "UNIQUE" in str(exc):
                raise ConflictError(f"你已经发布过 slug={slug} 的策略，改个名或发新版") from exc
            raise
        return self.get_publish(publish_id) or dict()

    def add_version(
        self,
        publish_id: str,
        *,
        source_text: str = "",
        params: Mapping[str, Any] | None = None,
        manifest: Mapping[str, Any] | None = None,
        release_notes: str = "",
    ) -> dict[str, Any]:
        """追加一个冻结版本，并把 ``current_version`` 推到它。

        版本号在 ``BEGIN IMMEDIATE`` 里读+写，避免两个并发发版拿到同一个号
        （唯一索引会挡住，但报的错会很难看）。
        """
        with self._transaction(immediate=True) as cursor:
            current = cursor.execute(
                "SELECT current_version FROM published_strategies WHERE publish_id = ?",
                (publish_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError(f"发布物不存在：{publish_id}")
            version = int(current["current_version"]) + 1
            now = self._now()
            cursor.execute(
                """
                INSERT INTO published_versions(
                    id, publish_id, version, source_text, params_json, manifest_json,
                    release_notes, content_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("PVR"),
                    publish_id,
                    version,
                    source_text,
                    dumps(dict(params or {})),
                    dumps(dict(manifest or {})),
                    release_notes,
                    content_hash(source_text, params),
                    now,
                ),
            )
            cursor.execute(
                "UPDATE published_strategies SET current_version = ?, updated_at = ? WHERE publish_id = ?",
                (version, now, publish_id),
            )
        return self.get_version(publish_id, version) or dict()

    def get_publish(self, publish_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM published_strategies WHERE publish_id = ?", (publish_id,)
        ).fetchone()
        return self._publish_row(row)

    def require_publish(self, publish_id: str) -> dict[str, Any]:
        found = self.get_publish(publish_id)
        if not found:
            raise NotFoundError(f"发布物不存在：{publish_id}")
        return found

    def find_publish_by_slug(self, owner_user_id: str, slug: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM published_strategies WHERE owner_user_id = ? AND slug = ?",
            (owner_user_id, slug),
        ).fetchone()
        return self._publish_row(row)

    def update_publish(self, publish_id: str, **fields: Any) -> dict[str, Any] | None:
        """改可变字段（标题 / 摘要 / 标签 / 可见性…）。未知列直接抛，不静默丢弃。"""
        if "tags" in fields:
            fields["tags_json"] = dumps(list(fields.pop("tags") or []))
        unknown = [key for key in fields if key not in _MUTABLE_COLUMNS]
        if unknown:
            raise ConflictError(f"不允许修改的字段：{', '.join(sorted(unknown))}")
        if not fields:
            return self.get_publish(publish_id)
        assignments = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["publish_id"] = publish_id
        params["updated_at"] = self._now()
        with self._transaction() as cursor:
            cursor.execute(
                f"UPDATE published_strategies SET {assignments}, updated_at = :updated_at"
                " WHERE publish_id = :publish_id",
                params,
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"发布物不存在：{publish_id}")
        return self.get_publish(publish_id)

    def set_status(self, publish_id: str, status: str) -> dict[str, Any]:
        """上架 / 下架。下架不删数据：已克隆的人还要能对账。"""
        now = self._now()
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE published_strategies SET status = ?, updated_at = ?,"
                " delisted_at = CASE WHEN ? = 'delisted' THEN ? ELSE '' END"
                " WHERE publish_id = ?",
                (status, now, status, now, publish_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"发布物不存在：{publish_id}")
        # 动态流由 application 写：store 只管一张表，别在这里替上层决定「要不要发动态」。
        return self.get_publish(publish_id) or dict()

    def bump_views(self, publish_id: str, *, delta: int = 1) -> int:
        """浏览计数。**不精确也无所谓**：它只用来排热度，不进任何账。"""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE published_strategies SET views = views + ? WHERE publish_id = ?",
                (int(delta), publish_id),
            )
        row = self.conn.execute(
            "SELECT views FROM published_strategies WHERE publish_id = ?", (publish_id,)
        ).fetchone()
        return int(row["views"]) if row else 0

    def list_versions(self, publish_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM published_versions WHERE publish_id = ? ORDER BY version DESC",
            (publish_id,),
        ).fetchall()
        return [item for item in (self._version_row(row) for row in rows) if item]

    def get_version(self, publish_id: str, version: int | None = None) -> dict[str, Any] | None:
        """取指定版本；``version=None`` 取当前版本。"""
        if version is None:
            row = self.conn.execute(
                "SELECT * FROM published_versions WHERE publish_id = ?"
                " ORDER BY version DESC LIMIT 1",
                (publish_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM published_versions WHERE publish_id = ? AND version = ?",
                (publish_id, int(version)),
            ).fetchone()
        return self._version_row(row)

    def list_owner_publishes(
        self, owner_user_id: str, *, include_hidden: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM published_strategies WHERE owner_user_id = ?"
        if not include_hidden:
            sql += " AND status = 'listed' AND visibility = 'public'"
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = self.conn.execute(sql, (owner_user_id, int(limit))).fetchall()
        return [item for item in (self._publish_row(row) for row in rows) if item]

    def freeze_probe(self, publish_id: str) -> None:
        """自检：确认冻结触发器还在（DDL 被人改坏时尽早炸，而不是默默允许改版本）。"""
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            " AND name = 'trg_published_versions_frozen_update'"
        ).fetchone()
        if row is None:
            raise FrozenVersionError("published_versions 的冻结触发器丢失，拒绝继续写入")
