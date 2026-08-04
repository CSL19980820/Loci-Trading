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


# 进程崩溃时不会执行 finish_run。超过一天的 running 记录不再占用执行槽，
# 避免一次异常重启后让同一任务永久无法再次执行。
STALE_RUN_SECONDS = 24 * 60 * 60
STALE_RUN_ERROR = "任务运行超过 24 小时，已按中断回收"


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

        已有任务：只补配置，不强行改 enabled（与行情托管语义一致，尊重运维页开关）。
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
        self.update_job(existing["id"], config=config)
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

    @staticmethod
    def _insert_run(
        cursor: sqlite3.Cursor,
        *,
        run_id: str,
        job: dict[str, Any],
        trigger: str,
    ) -> None:
        cursor.execute(
            "INSERT INTO job_runs(id, job_id, job_name, kind, trigger, status, started_at)"
            " VALUES(?, ?, ?, ?, ?, 'running', datetime('now'))",
            (run_id, job.get("id", ""), job.get("name", ""), job.get("kind", ""), trigger),
        )

    def claim_run(self, job: dict[str, Any], *, trigger: str = "manual") -> tuple[str, bool]:
        """原子认领一个任务的执行槽。

        ``False`` 表示该任务已有运行中的记录，返回其 ``run_id``；调用方不得再次
        执行副作用。即时分析先创建独立 run 再传给 ``run_job``，因此仍可并行。
        """
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            raise OpsError("任务缺少 id，无法认领执行槽")

        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "UPDATE job_runs SET status = 'failed', finished_at = datetime('now'), "
                "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
                "WHERE job_id = ? AND status = 'running' "
                "AND started_at < datetime('now', ?)",
                (STALE_RUN_ERROR, job_id, f"-{STALE_RUN_SECONDS} seconds"),
            )
            active = cursor.execute(
                "SELECT id FROM job_runs WHERE job_id = ? AND status = 'running' "
                "ORDER BY started_at DESC, id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if active is not None:
                return str(active["id"]), False

            run_id = new_id("RUN")
            self._insert_run(cursor, run_id=run_id, job=job, trigger=trigger)
            return run_id, True

    def start_run(self, job: dict[str, Any], *, trigger: str = "manual") -> str:
        """直接创建执行记录；即时分析等已分配独立运行槽的路径使用。"""
        run_id = new_id("RUN")
        with self._transaction() as cursor:
            self._insert_run(cursor, run_id=run_id, job=job, trigger=trigger)
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
            if cursor.rowcount != 1:
                raise OpsError("任务运行不存在或已被删除")
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
        self,
        *,
        job_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM job_runs WHERE 1=1"
        params: list[Any] = []
        if run_id:
            sql += " AND id = ?"
            params.append(run_id)
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

    def delete_runs(self, ids: list[str]) -> int:
        """按 id 批量删除执行历史。空列表直接返回 0。"""
        cleaned = [str(item).strip() for item in ids if str(item).strip()]
        if not cleaned:
            return 0
        # 去重，避免同一 id 重复占位
        unique = list(dict.fromkeys(cleaned))
        placeholders = ",".join("?" * len(unique))
        with self._transaction() as cursor:
            running = cursor.execute(
                f"SELECT id FROM job_runs WHERE id IN ({placeholders}) AND status = 'running' LIMIT 1",
                unique,
            ).fetchone()
            if running is not None:
                raise OpsError("运行中的任务记录不可删除")
            cursor.execute(
                f"DELETE FROM job_runs WHERE id IN ({placeholders})",
                unique,
            )
            return int(cursor.rowcount)

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
