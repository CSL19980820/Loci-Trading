"""OpsStore:执行历史(job_runs)——占槽、回收、收尾、取消。

从 ``store_jobs.py`` 拆出来。同一个文件里原本混着两件事:**任务定义**
(cron / config / 托管确保)与**每次运行的生命周期**(claim → start → finish)。
前者是配置,后者是状态机,读的人和改的原因都不一样。

回收逻辑是这里最容易出事的部分:进程崩溃时不会执行 ``finish_run``,占槽会一直
挂着「正在执行」。优先按 ``owner_pid`` 探活立刻回收,时间窗只是兜底。
"""
from __future__ import annotations

import logging
from typing import Any
import sqlite3

from src.ops.infrastructure.process_alive import current_pid, pid_is_alive
from src.ops.infrastructure.store_helpers import (
    OpsError,
    RUN_STATUSES,
    dumps,
  loads,
    new_id,
)

# 进程崩溃时不会执行 finish_run。优先按 owner_pid 探活立刻回收;
# 时间窗是兜底(sync/screen 45 分钟;其它 24h)。
STALE_RUN_SECONDS = 24 * 60 * 60
STALE_RUN_SECONDS_BY_KIND = {
    "sync": 45 * 60,
"screen": 45 * 60,
    # 日终本身应数分钟内结束;被 market.db 抢锁挂死时不能等满 24h
    "paper_eod": 45 * 60,
}
STALE_RUN_ERROR = "任务运行超时，已按中断回收"
DEAD_PID_RUN_ERROR = "任务进程已退出，占槽已回收"
#: 升级前写入的 running 没有 owner_pid;超过该窗口一律腾槽,避免假「正在执行」。
LEGACY_NO_PID_STALE_SECONDS = 15 * 60
LEGACY_NO_PID_ERROR = "任务占槽无进程号（旧记录或异常中断），已回收"


logger = logging.getLogger(__name__)


class OpsRunsMixin:
    """job_runs 生命周期。依赖宿主提供 conn 与 _transaction。"""

    @staticmethod
    def _insert_run(
        cursor: sqlite3.Cursor,
        *,
        run_id: str,
        job: dict[str, Any],
        trigger: str,
        idempotency_key: str = "",
    ) -> None:
        cursor.execute(
            "INSERT INTO job_runs("
            "id, job_id, job_name, kind, trigger, status, started_at, owner_pid,"
            "idempotency_key, cancel_requested, heartbeat_at"
            ") VALUES(?, ?, ?, ?, ?, 'running', datetime('now'), ?, ?, 0, '')",
            (
                run_id,
                job.get("id", ""),
                job.get("name", ""),
                job.get("kind", ""),
                trigger,
                current_pid(),
                idempotency_key,
            ),
        )

    def claim_run(
        self,
        job: dict[str, Any],
        *,
        trigger: str = "manual",
        idempotency_key: str | None = None,
    ) -> tuple[str, bool]:
        """原子认领一个任务的执行槽。

        ``False`` 表示该任务已有运行中的记录，返回其 ``run_id``；调用方不得再次
        执行副作用。即时分析先创建独立 run 再传给 ``run_job``，因此仍可并行。
        """
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            raise OpsError("任务缺少 id，无法认领执行槽")

        kind = str(job.get("kind") or "")
        key = str(idempotency_key or "").strip()[:160]
        stale_seconds = int(STALE_RUN_SECONDS_BY_KIND.get(kind, STALE_RUN_SECONDS))
        stale_msg = (
            f"{STALE_RUN_ERROR}（{kind or 'job'}>{max(1, stale_seconds // 60)}分钟）"
        )

        with self._transaction(immediate=True) as cursor:
            # 死进程立刻腾槽；超时是兜底。
            self._reclaim_stale_runs(cursor)
            if key:
                existing = cursor.execute(
                    "SELECT id FROM job_runs WHERE idempotency_key = ? LIMIT 1",
                    (key,),
                ).fetchone()
                if existing is not None:
                    return str(existing["id"]), False
            cursor.execute(
                "UPDATE job_runs SET status = 'failed', finished_at = datetime('now'), "
                "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
                "WHERE job_id = ? AND status = 'running' "
                "AND COALESCE(NULLIF(heartbeat_at, ''), started_at) < datetime('now', ?)",
                (stale_msg, job_id, f"-{stale_seconds} seconds"),
            )
            active = cursor.execute(
                "SELECT id FROM job_runs WHERE job_id = ? AND status = 'running' "
                "ORDER BY started_at DESC, id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if active is not None:
                return str(active["id"]), False

            run_id = new_id("RUN")
            try:
                self._insert_run(
                    cursor,
                    run_id=run_id,
                    job=job,
                    trigger=trigger,
                    idempotency_key=key,
                )
            except sqlite3.IntegrityError:
                if not key:
                    raise
                existing = cursor.execute(
                    "SELECT id FROM job_runs WHERE idempotency_key = ? LIMIT 1",
                    (key,),
                ).fetchone()
                if existing is None:
                    raise
                return str(existing["id"]), False
            return run_id, True

    def reclaim_stale_runs(self) -> int:
        """回收死进程 / 超时 running；调度器启动或 claim 时调用。"""
        with self._transaction(immediate=True) as cursor:
            return self._reclaim_stale_runs(cursor)

    def _reclaim_dead_pid_runs(self, cursor: sqlite3.Cursor) -> int:
        rows = cursor.execute(
            "SELECT id, owner_pid FROM job_runs WHERE status = 'running' AND owner_pid > 0"
        ).fetchall()
        dead_ids = [
            str(row["id"])
            for row in rows
            if not pid_is_alive(int(row["owner_pid"] or 0))
        ]
        if not dead_ids:
            return 0
        placeholders = ",".join("?" for _ in dead_ids)
        cursor.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = datetime('now'), "
            "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
            f"WHERE id IN ({placeholders})",
            (DEAD_PID_RUN_ERROR, *dead_ids),
        )
        return int(cursor.rowcount or 0)

    def _reclaim_legacy_no_pid_runs(self, cursor: sqlite3.Cursor) -> int:
        cursor.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = datetime('now'), "
            "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
            "WHERE status = 'running' AND owner_pid = 0 "
            "AND COALESCE(NULLIF(heartbeat_at, ''), started_at) < datetime('now', ?)",
            (LEGACY_NO_PID_ERROR, f"-{LEGACY_NO_PID_STALE_SECONDS} seconds"),
        )
        return int(cursor.rowcount or 0)

    def _reclaim_stale_runs(self, cursor: sqlite3.Cursor) -> int:
        total = self._reclaim_dead_pid_runs(cursor)
        total += self._reclaim_legacy_no_pid_runs(cursor)
        for kind, seconds in STALE_RUN_SECONDS_BY_KIND.items():
            msg = f"{STALE_RUN_ERROR}（{kind}>{max(1, seconds // 60)}分钟）"
            cursor.execute(
                "UPDATE job_runs SET status = 'failed', finished_at = datetime('now'), "
                "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
                "WHERE kind = ? AND status = 'running' "
                "AND COALESCE(NULLIF(heartbeat_at, ''), started_at) < datetime('now', ?)",
                (msg, kind, f"-{seconds} seconds"),
            )
            total += int(cursor.rowcount or 0)
        cursor.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = datetime('now'), "
            "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
            "WHERE status = 'running' "
            "AND kind NOT IN (" + ",".join("?" for _ in STALE_RUN_SECONDS_BY_KIND) + ") "
            "AND COALESCE(NULLIF(heartbeat_at, ''), started_at) < datetime('now', ?)",
            (
                f"{STALE_RUN_ERROR}（>{STALE_RUN_SECONDS // 3600}h）",
                *STALE_RUN_SECONDS_BY_KIND.keys(),
                f"-{STALE_RUN_SECONDS} seconds",
            ),
        )
        total += int(cursor.rowcount or 0)
        return total

    def start_run(
        self,
        job: dict[str, Any],
        *,
        trigger: str = "manual",
        idempotency_key: str | None = None,
    ) -> str:
        """直接创建执行记录；即时分析等已分配独立运行槽的路径使用。"""
        return self.start_run_idempotent(
            job,
            trigger=trigger,
            idempotency_key=idempotency_key,
        )

    def start_run_idempotent(
        self,
        job: dict[str, Any],
        *,
        trigger: str = "manual",
        idempotency_key: str | None = None,
    ) -> str:
        """创建运行记录；同一非空 key 永远复用第一次运行。"""
        run_id = new_id("RUN")
        key = str(idempotency_key or "").strip()[:160]
        with self._transaction(immediate=True) as cursor:
            if key:
                existing = cursor.execute(
                    "SELECT id FROM job_runs WHERE idempotency_key = ? LIMIT 1",
                    (key,),
                ).fetchone()
                if existing is not None:
                    return str(existing["id"])
            self._insert_run(
                cursor,
                run_id=run_id,
                job=job,
                trigger=trigger,
                idempotency_key=key,
            )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM job_runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def get_run_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        row = self.conn.execute(
            "SELECT * FROM job_runs WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        return self._run_row(row) if row else None

    def request_cancel(self, run_id: str, *, reason: str = "用户请求取消") -> bool:
        """只标记 running；实际执行器在安全检查点收敛到 cancelled。"""
        message = str(reason or "用户请求取消")[:4000]
        with self._transaction(immediate=True) as cursor:
            cursor.execute(
                "UPDATE job_runs SET cancel_requested = 1, error_text = "
                "CASE WHEN error_text = '' THEN ? ELSE error_text END "
                "WHERE id = ? AND status = 'running'",
                (message, run_id),
            )
            return cursor.rowcount == 1


    def is_cancel_requested(self, run_id: str) -> bool:
        row = self.conn.execute(
            "SELECT cancel_requested FROM job_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return bool(row and row["cancel_requested"])

    def heartbeat_run(self, run_id: str) -> bool:
        """刷新 running 心跳；终态运行不会被重新打开。"""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET heartbeat_at = datetime('now') "
                "WHERE id = ? AND status = 'running'",
                (run_id,),
            )
            return cursor.rowcount == 1

    def finish_run(
        self, run_id: str, *, status: str, result: Any = None, error: str = "",
        duration_ms: int = 0,
    ) -> None:
        if status not in RUN_STATUSES:
            raise OpsError(f"未知执行状态：{status}")
        if status == "running":
            raise OpsError("finish_run 只能写入终态")
        # 逐票证据在这里收口:全库证据扫描能产出十几万条回执(实测单条 257 MB),
        # 权威副本本来就在 market.db.source_route_receipts,运维库不该再存一份。
        # 放在写库唯一入口而不是各个执行器里——不指望每个作业作者都记得。
        try:
            from src.ops.application.jobs.evidence import compact_job_result

            compact_job_result(result)
        except Exception as exc:  # noqa: BLE001 — 瘦身失败也必须让运行正常收尾
            logger.warning("作业结果瘦身失败,按原样写入:%s", exc)
        with self._transaction() as cursor:
            current = cursor.execute(
                "SELECT status, job_id FROM job_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if current is None:
                raise OpsError("任务运行不存在或已被删除")
            if current["status"] != "running":
                if current["status"] == status:
                    return
                raise OpsError(f"任务运行已进入终态：{current['status']}")
            cursor.execute(
                "UPDATE job_runs SET status = ?, finished_at = datetime('now'),"
                " heartbeat_at = datetime('now'), duration_ms = ?, result_json = ?,"
                " error_text = ? WHERE id = ? AND status = 'running'",
                (status, int(duration_ms), dumps(result if result is not None else {}),
                 error[:4000], run_id),
            )
            if cursor.rowcount != 1:
                raise OpsError("任务运行已进入终态")
            if current["job_id"]:
                cursor.execute(
                    "UPDATE jobs SET last_run_at = datetime('now'), last_status = ?,"
                    " updated_at = datetime('now') WHERE id = ?",
                    (status, current["job_id"]),
                )

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["result"] = loads(data.pop("result_json", "{}"), {})
        data["cancel_requested"] = bool(data.get("cancel_requested"))
        return data

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
            rows.append(self._run_row(row))
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
        """只保留每个任务最近 N 条执行记录；``running`` 不占保留名额也永不删。

        不清理这张表会无限增长，最终把运维库撑成几百 MB；但清掉执行中的
        运行槽会让 ``finish_run`` 当场报「任务运行不存在」，正在跑的任务直接炸。
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM job_runs WHERE status <> 'running' AND id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY job_id ORDER BY started_at DESC, id DESC
                        ) AS rn FROM job_runs
                    ) ranked WHERE rn > ?
                )
                """,
                (max(1, int(keep_per_job)),),
            )
            return cursor.rowcount
