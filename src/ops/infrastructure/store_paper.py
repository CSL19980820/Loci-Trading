"""ops.db 纸面量化舱 / 次日预案 / 盯盘运行。"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import dumps, loads, new_id


class OpsPaperMixin:
    def ensure_paper_cabin(
        self,
        slug: str,
        *,
        name: str = "",
        max_layers: float = 4.0,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            from src.ops.infrastructure.store import OpsError

            raise OpsError("纸面舱需要 slug")
        existing = self.get_paper_cabin(slug)
        if existing:
            return existing
        cabin_id = new_id("CAB")
        now = self._now()  # type: ignore[attr-defined]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO paper_cabins(
                    id, slug, name, max_layers, max_layers_per_name,
                    config_json, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, 1, ?, ?)
                """,
                (
                    cabin_id,
                    slug,
                    name or slug,
                    float(max_layers),
                    dumps(config or {}),
                    now,
                    now,
                ),
            )
        return self.get_paper_cabin(slug) or {}

    def get_paper_cabin(self, slug: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_cabins WHERE slug = ?", (slug,)
        ).fetchone()
        return self._cabin_row(row) if row else None

    def delete_paper_cabin(self, slug: str) -> bool:
        """删除纸面舱及按 slug 挂着的预案/盯盘/记忆；持仓与成交流水随舱走。"""
        key = str(slug or "").strip()
        if not key:
            return False
        cabin = self.get_paper_cabin(key)
        self.clear_paper_cabin_memory(key)
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            if cabin:
                cabin_id = str(cabin["id"])
                cursor.execute("DELETE FROM paper_positions WHERE cabin_id = ?", (cabin_id,))
                cursor.execute("DELETE FROM paper_fills WHERE cabin_id = ?", (cabin_id,))
                cursor.execute("DELETE FROM paper_rejects WHERE cabin_id = ?", (cabin_id,))
                cursor.execute("DELETE FROM paper_cabins WHERE id = ?", (cabin_id,))
            cursor.execute("DELETE FROM nextday_plans WHERE slug = ?", (key,))
            cursor.execute("DELETE FROM monitor_runs WHERE slug = ?", (key,))
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_decisions'"
            )
            if cursor.fetchone():
                cursor.execute("DELETE FROM ai_decisions WHERE slug = ?", (key,))
        return cabin is not None

    def get_paper_cabin_by_id(self, cabin_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_cabins WHERE id = ?", (cabin_id,)
        ).fetchone()
        return self._cabin_row(row) if row else None

    def update_paper_cabin_config(self, slug: str, config: dict[str, Any]) -> dict[str, Any]:
        cabin = self.ensure_paper_cabin(slug)
        merged = dict(cabin.get("config") or {})
        merged.update(config or {})
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "UPDATE paper_cabins SET config_json = ?, updated_at = ? WHERE id = ?",
                (dumps(merged), self._now(), cabin["id"]),  # type: ignore[attr-defined]
            )
        return self.get_paper_cabin(slug) or {}

    def update_paper_cabin_limits(
        self,
        slug: str,
        *,
        max_layers: float,
    ) -> dict[str, Any]:
        cabin = self.ensure_paper_cabin(slug, max_layers=max_layers)
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "UPDATE paper_cabins SET max_layers = ?, updated_at = ? WHERE id = ?",
                (float(max_layers), self._now(), cabin["id"]),  # type: ignore[attr-defined]
            )
        return self.get_paper_cabin(slug) or {}

    def list_paper_positions(self, cabin_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_positions WHERE cabin_id = ? ORDER BY code",
            (cabin_id,),
        ).fetchall()
        return [
            {
                "cabin_id": row["cabin_id"],
                "code": row["code"],
                "name": row["name"],
                "layers": float(row["layers"] or 0),
                "mark_cost": float(row["mark_cost"] or 0),
                "updated_at": row["updated_at"],
            }
            for row in rows
            if float(row["layers"] or 0) > 0
        ]

    def _write_paper_position(
        self,
        cursor: Any,
        *,
        cabin_id: str,
        code: str,
        name: str,
        layers: float,
        mark_cost: float,
    ) -> None:
        if layers <= 0:
            cursor.execute(
                "DELETE FROM paper_positions WHERE cabin_id = ? AND code = ?",
                (cabin_id, code),
            )
            return
        cursor.execute(
            """
            INSERT INTO paper_positions(cabin_id, code, name, layers, mark_cost, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cabin_id, code) DO UPDATE SET
                name=excluded.name,
                layers=excluded.layers,
                mark_cost=excluded.mark_cost,
                updated_at=excluded.updated_at
            """,
            (
                cabin_id,
                code,
                name,
                float(layers),
                float(mark_cost),
                self._now(),  # type: ignore[attr-defined]
            ),
        )

    def _write_paper_fill(self, cursor: Any, payload: dict[str, Any]) -> str:
        fill_id = new_id("PFL")
        cursor.execute(
            """
            INSERT INTO paper_fills(
                id, cabin_id, code, action, layers, mark_price, source, reason, decided_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_id,
                str(payload.get("cabin_id") or ""),
                str(payload.get("code") or ""),
                str(payload.get("action") or ""),
                float(payload.get("layers") or 0),
                float(payload.get("mark_price") or 0),
                str(payload.get("source") or ""),
                str(payload.get("reason") or ""),
                str(payload.get("decided_by") or ""),
                str(payload.get("created_at") or self._now()),  # type: ignore[attr-defined]
            ),
        )
        return fill_id

    def upsert_paper_position(
        self,
        cabin_id: str,
        *,
        code: str,
        name: str,
        layers: float,
        mark_cost: float,
    ) -> None:
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            self._write_paper_position(
                cursor,
                cabin_id=cabin_id,
                code=code,
                name=name,
                layers=layers,
                mark_cost=mark_cost,
            )

    def apply_paper_fill(
        self,
        payload: dict[str, Any],
        *,
        code: str,
        name: str,
        layers: float,
        mark_cost: float,
    ) -> str:
        """成交与仓位快照同事务落库。

        分两次事务写会留下「有成交、仓位还是旧的」的半条记录：成交流水与仓位
        快照互为对方的校验，二者不一致时无法判断哪个才是真的。
        """
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            fill_id = self._write_paper_fill(cursor, payload)
            self._write_paper_position(
                cursor,
                cabin_id=str(payload.get("cabin_id") or ""),
                code=code,
                name=name,
                layers=layers,
                mark_cost=mark_cost,
            )
        return fill_id

    def insert_paper_reject(self, payload: dict[str, Any]) -> str:
        reject_id = new_id("PRJ")
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO paper_rejects(
                    id, cabin_id, code, action, layers, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reject_id,
                    str(payload.get("cabin_id") or ""),
                    str(payload.get("code") or ""),
                    str(payload.get("action") or ""),
                    float(payload.get("layers") or 0),
                    str(payload.get("reason") or ""),
                    str(payload.get("created_at") or self._now()),  # type: ignore[attr-defined]
                ),
            )
        return reject_id

    def list_paper_fills(self, cabin_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_fills WHERE cabin_id = ? ORDER BY created_at DESC LIMIT ?",
            (cabin_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_nextday_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(payload.get("id") or "").strip() or new_id("NDP")
        now = self._now()  # type: ignore[attr-defined]
        slug = str(payload.get("slug") or "")
        plan_date = str(payload.get("plan_date") or "")
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO nextday_plans(
                    id, slug, plan_date, body_text, items_json,
                    config_snapshot_json, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug, plan_date) DO UPDATE SET
                    body_text=excluded.body_text,
                    items_json=excluded.items_json,
                    config_snapshot_json=excluded.config_snapshot_json,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    plan_id,
                    slug,
                    plan_date,
                    str(payload.get("body_text") or ""),
                    dumps(payload.get("items") or []),
                    dumps(payload.get("config_snapshot") or {}),
                    str(payload.get("source") or ""),
                    now,
                    now,
                ),
            )
        return self.get_nextday_plan(slug, plan_date) or {}

    def get_nextday_plan(self, slug: str, plan_date: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM nextday_plans WHERE slug = ? AND plan_date = ?",
            (slug, plan_date),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "slug": row["slug"],
            "plan_date": row["plan_date"],
            "body_text": row["body_text"],
            "items": loads(row["items_json"]) or [],
            "config_snapshot": loads(row["config_snapshot_json"]) or {},
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def insert_monitor_run(self, payload: dict[str, Any]) -> str:
        run_id = str(payload.get("id") or "").strip() or new_id("MON")
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO monitor_runs(
                    id, slug, status, trigger_source, snapshot_json, orders_json,
                    fills_json, rejects_json, notes, follow_pushed,
                    started_at, finished_at, duration_ms, error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(payload.get("slug") or ""),
                    str(payload.get("status") or ""),
                    str(payload.get("trigger_source") or ""),
                    dumps(payload.get("snapshot") or {}),
                    dumps(payload.get("orders") or []),
                    dumps(payload.get("fills") or []),
                    dumps(payload.get("rejects") or []),
                    str(payload.get("notes") or ""),
                    1 if payload.get("follow_pushed") else 0,
                    str(payload.get("started_at") or self._now()),  # type: ignore[attr-defined]
                    str(payload.get("finished_at") or ""),
                    int(payload.get("duration_ms") or 0),
                    str(payload.get("error_text") or ""),
                ),
            )
        return run_id

    def list_monitor_runs(self, slug: str, *, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM monitor_runs WHERE slug = ? ORDER BY started_at DESC LIMIT ?",
            (slug, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "slug": row["slug"],
                    "status": row["status"],
                    "trigger_source": row["trigger_source"],
                    "snapshot": loads(row["snapshot_json"]) or {},
                    "orders": loads(row["orders_json"]) or [],
                    "fills": loads(row["fills_json"]) or [],
                    "rejects": loads(row["rejects_json"]) or [],
                    "notes": row["notes"],
                    "follow_pushed": bool(row["follow_pushed"]),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "duration_ms": row["duration_ms"],
                    "error_text": row["error_text"],
                }
            )
        return out

    def get_paper_style(self, slug: str) -> dict[str, Any]:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_style_profiles WHERE slug = ?", (slug,)
        ).fetchone()
        if not row:
            return {
                "slug": slug,
                "style_md": "",
                "watch_hints": [],
                "buy_rules": {},
                "revision": 0,
                "updated_at": "",
            }
        return {
            "slug": row["slug"],
            "style_md": row["style_md"] or "",
            "watch_hints": loads(row["watch_hints_json"]) or [],
            "buy_rules": loads(row["buy_rules_json"]) or {},
            "revision": int(row["revision"] or 0),
            "updated_at": row["updated_at"],
        }

    def upsert_paper_style(
        self,
        slug: str,
        *,
        style_md: str | None = None,
        watch_hints: list[Any] | None = None,
        buy_rules: dict[str, Any] | None = None,
        bump_revision: bool = True,
    ) -> dict[str, Any]:
        current = self.get_paper_style(slug)
        next_md = current["style_md"] if style_md is None else str(style_md)
        next_hints = current["watch_hints"] if watch_hints is None else list(watch_hints)
        next_rules = current["buy_rules"] if buy_rules is None else dict(buy_rules)
        revision = int(current.get("revision") or 0)
        if bump_revision:
            revision += 1
        now = self._now()  # type: ignore[attr-defined]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO paper_style_profiles(
                    slug, style_md, watch_hints_json, buy_rules_json, revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    style_md = excluded.style_md,
                    watch_hints_json = excluded.watch_hints_json,
                    buy_rules_json = excluded.buy_rules_json,
                    revision = excluded.revision,
                    updated_at = excluded.updated_at
                """,
                (slug, next_md, dumps(next_hints), dumps(next_rules), revision, now),
            )
        return self.get_paper_style(slug)

    def add_paper_lesson(self, payload: dict[str, Any]) -> dict[str, Any]:
        lesson_id = str(payload.get("id") or "").strip() or new_id("LES")
        now = self._now()  # type: ignore[attr-defined]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO paper_lessons(
                    id, slug, trade_date, kind, title, content,
                    evidence_json, absorbed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson_id,
                    str(payload.get("slug") or ""),
                    str(payload.get("trade_date") or ""),
                    str(payload.get("kind") or "note"),
                    str(payload.get("title") or ""),
                    str(payload.get("content") or ""),
                    dumps(payload.get("evidence") or {}),
                    1 if payload.get("absorbed") else 0,
                    now,
                ),
            )
        return self.get_paper_lesson(lesson_id) or {"id": lesson_id}

    def get_paper_lesson(self, lesson_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM paper_lessons WHERE id = ?", (lesson_id,)
        ).fetchone()
        return self._lesson_row(row) if row else None

    def list_paper_lessons(
        self,
        slug: str,
        *,
        limit: int = 50,
        unabsorbed_only: bool = False,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM paper_lessons WHERE slug = ?"
        params: list[Any] = [slug]
        if unabsorbed_only:
            sql += " AND absorbed = 0"
        sql += " ORDER BY trade_date DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()  # type: ignore[attr-defined]
        return [self._lesson_row(row) for row in rows]

    def mark_paper_lessons_absorbed(self, lesson_ids: list[str]) -> int:
        ids = [str(x) for x in lesson_ids if str(x).strip()]
        if not ids:
            return 0
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.executemany(
                "UPDATE paper_lessons SET absorbed = 1 WHERE id = ?",
                [(i,) for i in ids],
            )
        return len(ids)

    def clear_paper_cabin_memory(self, slug: str) -> dict[str, int]:
        """清空该战法舱的风格人设 / 教训 / 记忆图（不动持仓与成交）。"""
        key = str(slug or "").strip()
        if not key:
            return {"lessons": 0, "style": 0, "nodes": 0, "edges": 0}
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            edges = cursor.execute(
                "DELETE FROM paper_mem_edges WHERE slug = ?", (key,)
            ).rowcount
            nodes = cursor.execute(
                "DELETE FROM paper_mem_nodes WHERE slug = ?", (key,)
            ).rowcount
            lessons = cursor.execute(
                "DELETE FROM paper_lessons WHERE slug = ?", (key,)
            ).rowcount
            style = cursor.execute(
                "DELETE FROM paper_style_profiles WHERE slug = ?", (key,)
            ).rowcount
        return {
            "lessons": int(lessons or 0),
            "style": int(style or 0),
            "nodes": int(nodes or 0),
            "edges": int(edges or 0),
        }

    def _lesson_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "slug": row["slug"],
            "trade_date": row["trade_date"],
            "kind": row["kind"],
            "title": row["title"],
            "content": row["content"],
            "evidence": loads(row["evidence_json"]) or {},
            "absorbed": bool(row["absorbed"]),
            "created_at": row["created_at"],
        }

    def _cabin_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "slug": row["slug"],
            "name": row["name"],
            "max_layers": float(row["max_layers"] or 0),
            "max_layers_per_name": float(row["max_layers_per_name"] or 0),
            "config": loads(row["config_json"]) or {},
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
