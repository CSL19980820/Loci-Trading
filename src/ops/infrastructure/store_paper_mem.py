"""ops.db 战法记忆知识图（nodes/edges），语义对齐 codegraph：可 explore 子图。"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import dumps, loads, new_id


class OpsPaperMemMixin:
    def upsert_paper_mem_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        slug = str(payload.get("slug") or "").strip()
        kind = str(payload.get("kind") or "").strip()
        key = str(payload.get("key") or "").strip()
        if not slug or not kind or not key:
            from src.ops.infrastructure.store import OpsError

            raise OpsError("记忆节点需要 slug/kind/key")
        now = self._now()  # type: ignore[attr-defined]
        node_id = str(payload.get("id") or "").strip() or new_id("PMN")
        existing = self.get_paper_mem_node_by_key(slug, kind, key)
        if existing:
            node_id = existing["id"]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO paper_mem_nodes(
                    id, slug, kind, key, title, body, props_json,
                    weight, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug, kind, key) DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    props_json = excluded.props_json,
                    weight = excluded.weight,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    node_id,
                    slug,
                    kind,
                    key,
                    str(payload.get("title") or key),
                    str(payload.get("body") or ""),
                    dumps(payload.get("props") or {}),
                    float(payload.get("weight") or 1.0),
                    1 if payload.get("active", True) else 0,
                    existing["created_at"] if existing else now,
                    now,
                ),
            )
        return self.get_paper_mem_node(node_id) or {}

    def get_paper_mem_node(self, node_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_mem_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return self._mem_node_row(row) if row else None

    def get_paper_mem_node_by_key(self, slug: str, kind: str, key: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_mem_nodes WHERE slug = ? AND kind = ? AND key = ?",
            (slug, kind, key),
        ).fetchone()
        return self._mem_node_row(row) if row else None

    def list_paper_mem_nodes(
        self,
        slug: str,
        *,
        kind: str | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM paper_mem_nodes WHERE slug = ?"
        params: list[Any] = [slug]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY weight DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()  # type: ignore[attr-defined]
        return [self._mem_node_row(r) for r in rows]

    def upsert_paper_mem_edge(self, payload: dict[str, Any]) -> dict[str, Any]:
        slug = str(payload.get("slug") or "").strip()
        src = str(payload.get("src_id") or "").strip()
        dst = str(payload.get("dst_id") or "").strip()
        rel = str(payload.get("rel") or "").strip()
        if not slug or not src or not dst or not rel:
            from src.ops.infrastructure.store import OpsError

            raise OpsError("记忆边需要 slug/src_id/dst_id/rel")
        # 同三元组幂等：先查
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT id FROM paper_mem_edges WHERE slug = ? AND src_id = ? AND dst_id = ? AND rel = ?",
            (slug, src, dst, rel),
        ).fetchone()
        edge_id = str(row["id"]) if row else (str(payload.get("id") or "").strip() or new_id("PME"))
        now = self._now()  # type: ignore[attr-defined]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            if row:
                cursor.execute(
                    """
                    UPDATE paper_mem_edges
                    SET weight = ?, props_json = ?
                    WHERE id = ?
                    """,
                    (
                        float(payload.get("weight") or 1.0),
                        dumps(payload.get("props") or {}),
                        edge_id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO paper_mem_edges(
                        id, slug, src_id, dst_id, rel, weight, props_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_id,
                        slug,
                        src,
                        dst,
                        rel,
                        float(payload.get("weight") or 1.0),
                        dumps(payload.get("props") or {}),
                        now,
                    ),
                )
        return {
            "id": edge_id,
            "slug": slug,
            "src_id": src,
            "dst_id": dst,
            "rel": rel,
            "weight": float(payload.get("weight") or 1.0),
            "props": payload.get("props") or {},
        }

    def list_paper_mem_edges(
        self,
        slug: str,
        *,
        node_ids: list[str] | None = None,
        limit: int = 400,
    ) -> list[dict[str, Any]]:
        if node_ids:
            ids = [str(x) for x in node_ids if str(x).strip()]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            rows = self.conn.execute(  # type: ignore[attr-defined]
                f"""
                SELECT * FROM paper_mem_edges
                WHERE slug = ? AND (src_id IN ({placeholders}) OR dst_id IN ({placeholders}))
                ORDER BY weight DESC LIMIT ?
                """,
                (slug, *ids, *ids, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(  # type: ignore[attr-defined]
                "SELECT * FROM paper_mem_edges WHERE slug = ? ORDER BY created_at DESC LIMIT ?",
                (slug, limit),
            ).fetchall()
        return [self._mem_edge_row(r) for r in rows]

    def search_paper_mem_nodes(self, slug: str, query: str, *, limit: int = 24) -> list[dict[str, Any]]:
        q = str(query or "").strip().lower()
        rows = self.list_paper_mem_nodes(slug, limit=300)
        if not q:
            return rows[:limit]
        tokens = [t for t in q.replace(",", " ").split() if t]
        scored: list[tuple[float, dict[str, Any]]] = []
        for node in rows:
            hay = " ".join(
                [
                    str(node.get("kind") or ""),
                    str(node.get("key") or ""),
                    str(node.get("title") or ""),
                    str(node.get("body") or ""),
                    str(node.get("props") or ""),
                ]
            ).lower()
            hits = sum(1 for t in tokens if t in hay)
            if hits:
                scored.append((hits * float(node.get("weight") or 1.0), node))
        scored.sort(key=lambda x: (-x[0], -float(x[1].get("weight") or 0)))
        return [n for _, n in scored[:limit]]

    def _mem_node_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "slug": row["slug"],
            "kind": row["kind"],
            "key": row["key"],
            "title": row["title"],
            "body": row["body"],
            "props": loads(row["props_json"]) or {},
            "weight": float(row["weight"] or 0),
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _mem_edge_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "slug": row["slug"],
            "src_id": row["src_id"],
            "dst_id": row["dst_id"],
            "rel": row["rel"],
            "weight": float(row["weight"] or 0),
            "props": loads(row["props_json"]) or {},
            "created_at": row["created_at"],
        }
