"""OpsStore：战法档案与策略版本历史。"""
from __future__ import annotations

import datetime as _dt
from typing import Any
import sqlite3

from src.ops.infrastructure.store_helpers import OpsError, dumps, loads, new_id


class OpsStrategyMixin:
    """strategy_docs / strategy_versions。依赖宿主提供 conn 与 _transaction。"""

    conn: sqlite3.Connection

    def upsert_strategy_doc(self, slug: str, **fields: Any) -> str:
        """写入或更新战法档案。只更新传入的字段，未传的保持原值。"""
        allowed = {"name", "source_text", "source_type", "assumptions",
                   "market_cond", "failure_modes", "entry_timing", "exit_rules", "version"}
        updates = {k: str(v) for k, v in fields.items() if k in allowed}
        slug = slug.strip()
        if not slug:
            raise OpsError("战法档案 slug 不能为空")
        existing = self.conn.execute(
            "SELECT * FROM strategy_docs WHERE slug = ?", (slug,)
        ).fetchone()
        now_str = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        with self._transaction() as cursor:
            if existing is None:
                row = {
                    "slug": slug,
                    "name": "",
                    "source_text": "",
                    "source_type": "",
                    "assumptions": "",
                    "market_cond": "",
                    "failure_modes": "",
                    "entry_timing": "",
                    "exit_rules": "",
                    "version": "1",
                    "created_at": now_str,
                    "updated_at": now_str,
                }
                row.update(updates)
                cursor.execute(
                    "INSERT INTO strategy_docs(slug, name, source_text, source_type, assumptions,"
                    " market_cond, failure_modes, entry_timing, exit_rules, version,"
                    " created_at, updated_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["slug"], row["name"], row["source_text"], row["source_type"],
                     row["assumptions"], row["market_cond"], row["failure_modes"],
                     row["entry_timing"], row["exit_rules"], row["version"],
                     row["created_at"], row["updated_at"]),
                )
            else:
                set_parts = ", ".join(f"{k} = ?" for k in updates)
                set_parts += ", updated_at = ?"
                vals = list(updates.values()) + [now_str, slug]
                cursor.execute(
                    f"UPDATE strategy_docs SET {set_parts} WHERE slug = ?", vals
                )
        return slug

    def get_strategy_doc(self, slug: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM strategy_docs WHERE slug = ?", (slug.strip(),)
        ).fetchone()
        return dict(row) if row else None

    def list_strategy_docs(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM strategy_docs ORDER BY slug"
        ).fetchall()
        return [dict(row) for row in rows]

    def save_strategy_version(
        self, slug: str, code: str, file_path: str = "", issues: list | None = None
    ) -> int:
        """保存新版本，激活它，旧版本失活，超出10个就清理最旧的未引用版本。"""
        version_id = new_id("SV")
        with self._transaction() as cursor:
            # 取当前最大版本号
            row = cursor.execute(
                "SELECT MAX(version) AS mv FROM strategy_versions WHERE slug = ?", (slug,)
            ).fetchone()
            next_ver = int(row["mv"] or 0) + 1
            # 新版本入库
            cursor.execute(
                "INSERT INTO strategy_versions(id, slug, version, code, file_path, issues, created_at, is_active)"
                " VALUES(?, ?, ?, ?, ?, ?, datetime('now'), 1)",
                (version_id, slug, next_ver, code, file_path, dumps(issues or [])),
            )
            # 旧版本失活
            cursor.execute(
                "UPDATE strategy_versions SET is_active=0 WHERE slug=? AND id!=?",
                (slug, version_id),
            )
        # 清理：超过10个且未被任务引用的最旧版本
        self._prune_strategy_versions(slug)
        return next_ver

    def _prune_strategy_versions(self, slug: str, keep: int = 10) -> None:
        rows = self.conn.execute(
            "SELECT id, version FROM strategy_versions WHERE slug=? ORDER BY version DESC",
            (slug,),
        ).fetchall()
        if len(rows) <= keep:
            return
        # 哪些 slug 被任务引用了（在 config_json 里出现过）
        all_configs = self.conn.execute("SELECT config_json FROM jobs").fetchall()
        referenced_ids: set[str] = set()
        for cfg_row in all_configs:
            cfg = loads(cfg_row["config_json"], {})
            if str(cfg.get("strategy", "")) == slug:
                # 任务引用了这个 slug 的某版本，保护 active 版本
                act = self.conn.execute(
                    "SELECT id FROM strategy_versions WHERE slug=? AND is_active=1", (slug,)
                ).fetchone()
                if act:
                    referenced_ids.add(act["id"])
        to_delete = [r["id"] for r in rows[keep:] if r["id"] not in referenced_ids]
        if to_delete:
            with self._transaction() as cursor:
                cursor.executemany(
                    "DELETE FROM strategy_versions WHERE id=?", [(vid,) for vid in to_delete]
                )

    def list_strategy_versions(self, slug: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, slug, version, file_path, issues, created_at, is_active"
            " FROM strategy_versions WHERE slug=? ORDER BY version DESC",
            (slug,),
        ).fetchall()
        return [
            {
                "id": row["id"], "slug": row["slug"], "version": row["version"],
                "file_path": row["file_path"], "issues": loads(row["issues"], []),
                "created_at": row["created_at"], "is_active": bool(row["is_active"]),
            }
            for row in rows
        ]

    def get_strategy_version(self, slug: str, version: int | None = None) -> dict[str, Any] | None:
        if version is None:
            row = self.conn.execute(
                "SELECT * FROM strategy_versions WHERE slug=? AND is_active=1", (slug,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM strategy_versions WHERE slug=? AND version=?", (slug, version)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["issues"] = loads(d.get("issues", "[]"), [])
        d["is_active"] = bool(d.get("is_active"))
        return d
