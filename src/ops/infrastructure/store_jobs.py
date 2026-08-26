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

    def update_job(
        self,
        job_id: str,
        *,
        expected_name: str | None = None,
        allowed_kinds: set[str] | None = None,
        **fields: Any,
    ) -> bool:
        """更新任务；可将目标名和任务类别作为同一 SQL 条件绑定。"""
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
            return False
        assignments.append("updated_at = datetime('now')")
        where = ["id = ?"]
        where_params: list[Any] = [job_id]
        if expected_name is not None:
            where.append("name = ?")
            where_params.append(expected_name)
        if allowed_kinds is not None:
            kinds = tuple(sorted(allowed_kinds))
            if not kinds:
                return False
            where.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            where_params.extend(kinds)
        with self._transaction() as cursor:
            cursor.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE {' AND '.join(where)}",
                [*params, *where_params],
            )
            return cursor.rowcount > 0

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

    def delete_job(
        self,
        job_id: str,
        *,
        expected_name: str | None = None,
        allowed_kinds: set[str] | None = None,
    ) -> bool:
        """删除任务；可防止授权期间目标被替换为另一类任务。"""
        where = ["id = ?"]
        params: list[Any] = [job_id]
        if expected_name is not None:
            where.append("name = ?")
            params.append(expected_name)
        if allowed_kinds is not None:
            kinds = tuple(sorted(allowed_kinds))
            if not kinds:
                return False
            where.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            params.extend(kinds)
        with self._transaction() as cursor:
            cursor.execute(f"DELETE FROM jobs WHERE {' AND '.join(where)}", params)
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
        # 托管任务可由多个进程在启动时同时确保。先查再建会让其中一方撞上
        # jobs.name 的唯一约束，因而必须把决策收敛为单条 upsert。
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO jobs(id, name, kind, cron, config_json, enabled, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    cron = excluded.cron,
                    config_json = CASE WHEN ? THEN excluded.config_json ELSE jobs.config_json END,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    new_id("JOB"),
                    name,
                    kind,
                    cron,
                    dumps(config or {}),
                    1 if enabled else 0,
                    1 if config is not None else 0,
                ),
            )
            row = cursor.execute("SELECT id FROM jobs WHERE name = ?", (name,)).fetchone()
        if row is None:  # pragma: no cover - SQLite upsert 后不应发生
            raise OpsError(f"确保任务失败：{name}")
        return str(row["id"])

    def ensure_managed_outcome_job(self, *, enabled: bool = True) -> str:
        """确保「候选T+N跟踪」托管任务存在（工作日 15:45）。

        已有任务：只补齐缺失的配置键，不改 enabled / cron，也不还原用户调过的
        参数（与行情托管语义一致，尊重运维页开关）。
        """
        from src.ops.infrastructure.store_helpers import (
            MANAGED_OUTCOME_CRON,
            MANAGED_OUTCOME_TRACK,
        )

        config = {
            "limit": 2000,
            "max_age_trading_days": 5,
            "benchmark": "000300",
        }
        existing = self.get_job_by_name(MANAGED_OUTCOME_TRACK)
        if existing is None:
            return self.ensure_job(
                name=MANAGED_OUTCOME_TRACK,
                kind="outcome",
                cron=MANAGED_OUTCOME_CRON,
                config=config,
                enabled=enabled,
            )
        prev = existing.get("config") if isinstance(existing.get("config"), dict) else {}
        self.update_job(existing["id"], config={**config, **prev})
        return existing["id"]

    def ensure_managed_screen_jobs(self) -> dict:
        """确保全部引擎战法绑定工作日 15:30 盘后选股。"""
        from src.ops.application.ensure_screen_jobs import ensure_managed_screen_jobs

        return ensure_managed_screen_jobs(self)

    def ensure_managed_market_sync_jobs(self) -> dict:
        """确保行情盘中增量 + 日终重刷托管任务（首次默认开启）。"""
        from src.ops.application.ensure_market_sync_jobs import (
            ensure_managed_market_sync_jobs,
        )

        return ensure_managed_market_sync_jobs(self)

    def ensure_managed_hot_rebuild_job(self) -> dict:
        """确保「行情热库重建」托管任务（首次默认开启）。"""
        from src.ops.application.ensure_hot_rebuild_job import (
            ensure_managed_hot_rebuild_job,
        )

        return ensure_managed_hot_rebuild_job(self)

    def ensure_managed_market_quality_job(self) -> dict:
        """确保「行情库体检」托管任务（首次默认开启）。"""
        from src.ops.application.ensure_market_quality_job import (
          ensure_managed_market_quality_job,
        )

        return ensure_managed_market_quality_job(self)

    def ensure_managed_prune_job(self) -> dict:
        """确保「运维清理」托管任务（首次默认开启）。"""
        from src.ops.application.ensure_managed_prune_job import (
            ensure_managed_prune_job,
        )

        return ensure_managed_prune_job(self)

    def ensure_managed_intel_jobs(self, *, enabled: bool = True) -> dict:
        from src.ops.application.ensure_intel_jobs import ensure_managed_intel_jobs

        return ensure_managed_intel_jobs(self, enabled=enabled)

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
