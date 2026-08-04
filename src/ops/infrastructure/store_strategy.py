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
                   "market_cond", "failure_modes", "entry_timing", "entry_instructions",
                   "exit_rules", "version"}
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
                    "entry_instructions": "",
                    "exit_rules": "",
                    "version": "1",
                    "created_at": now_str,
                    "updated_at": now_str,
                }
                row.update(updates)
                cursor.execute(
                    "INSERT INTO strategy_docs(slug, name, source_text, source_type, assumptions,"
                    " market_cond, failure_modes, entry_timing, entry_instructions, exit_rules, version,"
                    " created_at, updated_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["slug"], row["name"], row["source_text"], row["source_type"],
                     row["assumptions"], row["market_cond"], row["failure_modes"],
                     row["entry_timing"], row["entry_instructions"], row["exit_rules"], row["version"],
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

    def ensure_strategy_entry_instructions(self, strategies: list[dict[str, Any]]) -> None:
        """把内置战法的默认买入简述补进档案库，不覆盖已有人工内容。"""
        for strategy in strategies:
            slug = str(strategy.get("slug") or "").strip()
            instructions = str(strategy.get("entry_instructions") or "").strip()
            if not slug or not instructions:
                continue
            existing = self.get_strategy_doc(slug)
            if existing and str(existing.get("entry_instructions") or "").strip():
                continue
            self.upsert_strategy_doc(
                slug,
                name=str(strategy.get("name") or ""),
                source_type=str(strategy.get("source_kind") or ""),
                entry_timing=str(strategy.get("entry_timing") or ""),
                entry_instructions=instructions,
                version=str(strategy.get("version") or "1"),
            )

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
        """保存并激活代码版本；相同内容复用既有版本，不制造重复历史。"""
        slug = slug.strip()
        if not slug or not code:
            raise OpsError("策略版本的 slug 和代码不能为空")
        with self._transaction(immediate=True) as cursor:
            identical = cursor.execute(
                "SELECT id, version FROM strategy_versions WHERE slug=? AND code=? "
                "ORDER BY is_active DESC, version DESC LIMIT 1",
                (slug, code),
            ).fetchone()
            if identical is not None:
                cursor.execute("UPDATE strategy_versions SET is_active=0 WHERE slug=?", (slug,))
                cursor.execute(
                    "UPDATE strategy_versions SET is_active=1 WHERE id=?", (identical["id"],)
                )
                return int(identical["version"])
            row = cursor.execute(
                "SELECT MAX(version) AS mv FROM strategy_versions WHERE slug = ?", (slug,)
            ).fetchone()
            next_ver = int(row["mv"] or 0) + 1
            cursor.execute("UPDATE strategy_versions SET is_active=0 WHERE slug=?", (slug,))
            cursor.execute(
                "INSERT INTO strategy_versions(id, slug, version, code, file_path, issues, created_at, is_active)"
                " VALUES(?, ?, ?, ?, ?, ?, datetime('now'), 1)",
                (new_id("SV"), slug, next_ver, code, file_path, dumps(issues or [])),
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
        versions: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "id": row["id"], "slug": row["slug"], "version": row["version"],
                "file_path": row["file_path"], "issues": loads(row["issues"], []),
                "created_at": row["created_at"], "is_active": bool(row["is_active"]),
            }
            backtest = self.get_strategy_backtest(slug, str(row["version"]))
            item["backtest_metrics"] = backtest["metrics"] if backtest else None
            item["backtest_config"] = backtest["config"] if backtest else None
            versions.append(item)
        return versions

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

    def rollback_strategy_version(self, slug: str, version: int) -> dict[str, Any]:
        """原子切换 active 标记，原 active 记录继续作为历史保留。"""
        with self._transaction(immediate=True) as cursor:
            target = cursor.execute(
                "SELECT id FROM strategy_versions WHERE slug=? AND version=?",
                (slug, version),
            ).fetchone()
            if target is None:
                raise OpsError(f"策略 {slug} 不存在版本 {version}")
            cursor.execute("UPDATE strategy_versions SET is_active=0 WHERE slug=?", (slug,))
            cursor.execute("UPDATE strategy_versions SET is_active=1 WHERE id=?", (target["id"],))
        restored = self.get_strategy_version(slug, version)
        if restored is None:
            raise OpsError(f"策略 {slug} 版本 {version} 回滚后无法读取")
        return restored

    def delete_strategy_version(self, slug: str, version: int) -> bool:
        """拒绝删除 active 版本，避免留下没有 active 的策略。"""
        with self._transaction(immediate=True) as cursor:
            row = cursor.execute(
                "SELECT id, is_active FROM strategy_versions WHERE slug=? AND version=?",
                (slug, version),
            ).fetchone()
            if row is None:
                return False
            if bool(row["is_active"]):
                raise OpsError("不能删除当前 active 版本；请先回滚到其他版本")
            cursor.execute("DELETE FROM strategy_versions WHERE id=?", (row["id"],))
        return True

    def upsert_strategy_backtest(
        self,
        slug: str,
        version: str,
        *,
        metrics: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """按 slug + 版本幂等更新回测元数据。"""
        slug, version = slug.strip(), str(version).strip()
        if not slug or not version:
            raise OpsError("回测元数据的策略 slug 和版本不能为空")
        if not isinstance(metrics, dict) or not isinstance(config, dict):
            raise OpsError("回测元数据必须是对象")
        now_str = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "INSERT INTO strategy_backtests(slug, version, metrics_json, config_json, updated_at) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(slug, version) DO UPDATE SET "
                "metrics_json=excluded.metrics_json, config_json=excluded.config_json, "
                "updated_at=excluded.updated_at",
                (slug, version, dumps(metrics), dumps(config), now_str),
            )
        return {
            "slug": slug,
            "version": version,
            "metrics": metrics,
            "config": config,
            "updated_at": now_str,
        }

    def get_strategy_backtest(self, slug: str, version: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT slug, version, metrics_json, config_json, updated_at "
            "FROM strategy_backtests WHERE slug=? AND version=?",
            (slug.strip(), str(version).strip()),
        ).fetchone()
        if row is None:
            return None
        return {
            "slug": row["slug"],
            "version": row["version"],
            "metrics": loads(row["metrics_json"], {}),
            "config": loads(row["config_json"], {}),
            "updated_at": row["updated_at"],
        }

    def strategy_catalog_metadata(
        self, strategies: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """合并档案库买入简述与可持久化策略的版本回测数据。"""
        metadata: dict[str, dict[str, Any]] = {}
        for strategy in strategies:
            slug = str(strategy["slug"])
            item: dict[str, Any] = {}
            doc = self.get_strategy_doc(slug)
            instructions = str((doc or {}).get("entry_instructions") or "").strip()
            if instructions:
                item["entry_instructions"] = instructions
            if str(strategy.get("source_kind") or "") != "builtin":
                version = str(strategy["version"])
                backtest = self.get_strategy_backtest(slug, version)
                item.update({
                    "version": version,
                    "version_history": self.list_strategy_versions(slug),
                    "backtest_metrics": backtest["metrics"] if backtest else None,
                    "backtest_config": backtest["config"] if backtest else None,
                })
            metadata[slug] = item
        return metadata
