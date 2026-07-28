"""OpsStore：定时任务、设置 KV、执行历史。"""
from __future__ import annotations

from typing import Any
import sqlite3

from src.ops.infrastructure.store_helpers import (
    JOB_KINDS,
    OpsError,
    RUN_STATUSES,
    dumps,
    loads,
    new_id,
)


class OpsJobsMixin:
    """任务 / meta 设置 / job_runs。依赖宿主提供 conn 与 _transaction。"""

    conn: sqlite3.Connection

    def create_job(
        self, *, name: str, kind: str, cron: str = "", config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> str:
        if kind not in JOB_KINDS:
            raise OpsError(f"未知任务类型：{kind}（可选 {list(JOB_KINDS)}）")
        job_id = new_id("JOB")
        with self._transaction() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO jobs(id, name, kind, cron, config_json, enabled,"
                    " created_at, updated_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (job_id, name, kind, cron, dumps(config or {}), 1 if enabled else 0),
                )
            except sqlite3.IntegrityError as exc:
                raise OpsError(f"任务名已存在：{name}") from exc
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"name", "cron", "config", "enabled"}
        unknown = set(fields) - allowed
        if unknown:
            raise OpsError(f"不可更新的字段：{sorted(unknown)}")
        assignments, params = [], []
        for key, value in fields.items():
            if key == "config":
                assignments.append("config_json = ?")
                params.append(dumps(value))
            elif key == "enabled":
                assignments.append("enabled = ?")
                params.append(1 if value else 0)
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        if not assignments:
            return
        assignments.append("updated_at = datetime('now')")
        params.append(job_id)
        with self._transaction() as cursor:
            cursor.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", params)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def get_job_by_name(self, name: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()
        return self._job_row(row) if row else None

    def list_jobs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name"
        return [self._job_row(row) for row in self.conn.execute(sql)]

    def delete_job(self, job_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return cursor.rowcount > 0

    def ensure_job(
        self,
        *,
        name: str,
        kind: str,
        cron: str = "",
        config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> str:
        """按名称创建或更新任务（托管同步任务用）。"""
        existing = self.get_job_by_name(name)
        if existing is None:
            return self.create_job(
                name=name, kind=kind, cron=cron, config=config, enabled=enabled
            )
        self.update_job(
            existing["id"],
            cron=cron,
            config=config if config is not None else existing.get("config") or {},
            enabled=enabled,
        )
        return existing["id"]

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["config"] = loads(data.pop("config_json", "{}"), {})
        data["enabled"] = bool(data.get("enabled"))
        return data

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return loads(row["value"], default)

    def set_setting(self, key: str, value: Any) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                (key, dumps(value)),
            )

    def delete_setting(self, key: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM meta WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def start_run(self, job: dict[str, Any], *, trigger: str = "manual") -> str:
        run_id = new_id("RUN")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO job_runs(id, job_id, job_name, kind, trigger, status, started_at)"
                " VALUES(?, ?, ?, ?, ?, 'running', datetime('now'))",
                (run_id, job.get("id", ""), job.get("name", ""), job.get("kind", ""), trigger),
            )
        return run_id

    def finish_run(
        self, run_id: str, *, status: str, result: Any = None, error: str = "",
        duration_ms: int = 0,
    ) -> None:
        if status not in RUN_STATUSES:
            raise OpsError(f"未知执行状态：{status}")
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET status = ?, finished_at = datetime('now'),"
                " duration_ms = ?, result_json = ?, error_text = ? WHERE id = ?",
                (status, int(duration_ms), dumps(result if result is not None else {}),
                 error[:4000], run_id),
            )
            row = cursor.execute(
                "SELECT job_id FROM job_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row and row["job_id"]:
                cursor.execute(
                    "UPDATE jobs SET last_run_at = datetime('now'), last_status = ?,"
                    " updated_at = datetime('now') WHERE id = ?",
                    (status, row["job_id"]),
                )

    def list_runs(
        self, *, job_id: str | None = None, limit: int = 50, status: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM job_runs WHERE 1=1"
        params: list[Any] = []
        if job_id:
            sql += " AND job_id = ?"
            params.append(job_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = []
        for row in self.conn.execute(sql, params):
            data = dict(row)
            data["result"] = loads(data.pop("result_json", "{}"), {})
            rows.append(data)
        return rows

    def prune_runs(self, keep_per_job: int = 200) -> int:
        """只保留每个任务最近 N 条执行记录。

        定时任务是每天跑的，不清理的话这张表会无限增长，最终把小小的
        运维库撑成几百 MB。
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM job_runs WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY job_id ORDER BY started_at DESC, id DESC
                        ) AS rn FROM job_runs
                    ) ranked WHERE rn > ?
                )
                """,
                (int(keep_per_job),),
            )
            return cursor.rowcount
