"""OpsStore:执行历史(job_runs)——占槽、回收、收尾、取消。

从 ``store_jobs.py`` 拆出来。同一个文件里原本混着两件事:**任务定义**
(cron / config / 托管确保)与**每次运行的生命周期**(claim → start → finish)。
前者是配置,后者是状态机,读的人和改的原因都不一样。

回收逻辑是这里最容易出事的部分:进程崩溃时不会执行 ``finish_run``,占槽会一直
挂着「正在执行」。优先按 ``owner_pid`` 探活立刻回收,时间窗只是兜底。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
import sqlite3

from src.ops.infrastructure.process_alive import current_pid, pid_is_alive
from src.ops.infrastructure.store_helpers import (
    OpsError,
    RUN_STATUSES,
    _now,
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
RESTARTED_PID_RUN_ERROR = "任务进程已重启（PID 复用），占槽已回收"
#: 本进程启动时刻。容器 Recreate 后 PID 经常还是 1，``pid_alive(1)`` 为真，
#: 上一世留下的 running 必须靠「started_at 早于本进程」立刻腾槽。
PROCESS_STARTED_AT = datetime.now().astimezone()
_PROCESS_START_SLACK = timedelta(seconds=2)


def _parse_run_started_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def started_before_this_process(started_at: str) -> bool:
    """``started_at`` 是否早于本进程启动（含 2 秒时钟余量）。解析失败当否。"""
    started = _parse_run_started_at(started_at)
    if started is None:
        return False
    return started < (PROCESS_STARTED_AT - _PROCESS_START_SLACK)
#: 升级前写入的 running 没有 owner_pid;超过该窗口一律腾槽,避免假「正在执行」。
LEGACY_NO_PID_STALE_SECONDS = 15 * 60
LEGACY_NO_PID_ERROR = "任务占槽无进程号（旧记录或异常中断），已回收"

#: 一条 run 的「最后活着的时刻」：有心跳用心跳，没有（刚起、旧记录）退回 started_at。
RUN_CLOCK_SQL = "COALESCE(NULLIF(heartbeat_at, ''), started_at)"

#: 回收窗判据。**不要退回字符串比较**：本表现在新旧两种时间戳并存——
#: 历史行是 ``datetime('now')`` 的 UTC ``"YYYY-MM-DD HH:MM:SS"``，新行是 ``_now()``
#: 的本地带偏移 ``"YYYY-MM-DDTHH:MM:SS.ffffff+08:00"``。拿字符串跟 UTC 基准比，
#: 东八区的新行看起来永远比真实时刻晚 8 小时：真死掉的任务要多等 8 小时才被收尸；
#: 反过来若基准换成本地而行是 UTC，则**刚启动的任务会被当场判死**。
#: ``julianday()`` 把两种写法都折算成同一条 UTC 时间轴（不带偏移的旧值按 UTC 解释，
#: 正是它当初的含义），比较因此与格式无关。
#:
#: 解析不了的脏值让 ``julianday()`` 返回 NULL，整个谓词为 NULL → 该行**不**被时间窗
#: 回收，与改动前字符串比较的表现一致（脏值排在时间串之后，同样不会被收）。宁可漏收
#: 一条也不能因为一次解析失败把全部在跑的任务批量判死；无 pid 的脏值另有兜底，
#: 见 ``_reclaim_legacy_no_pid_runs``。
RUN_STALE_SQL = f"julianday({RUN_CLOCK_SQL}) < julianday('now', ?)"

#: 排序键。同理不能按字符串排：'T' > ' '，新行会无条件排到同日旧行前面，
#: 而真实先后未必如此。NULL（脏值）沉底，再用原串做同秒内的兜底次序。
RUN_ORDER_SQL = "COALESCE(julianday(started_at), 0) DESC, started_at DESC, id DESC"


logger = logging.getLogger(__name__)


#: 心跳 SQL 唯一真相。只推进 heartbeat_at，且只认 ``running``——终态 run 不会
#: 被心跳重新打开（后台心跳线程和 finish_run 的竞速由这个 WHERE 兜住）。
HEARTBEAT_SQL = (
    "UPDATE job_runs SET heartbeat_at = ? "
    "WHERE id = ? AND status = 'running'"
)

#: 执行期心跳等 ops.db 写锁的上限（毫秒）。心跳只是一行 UPDATE，抢不到锁就跳过
#: 这一拍，下一拍还会再来；为了刷心跳把执行线程或收尾流程卡住是本末倒置。
HEARTBEAT_BUSY_TIMEOUT_MS = 2000


class RunHeartbeatWriter:
    """跨线程心跳写入器：自带一条连接，只发自动提交的单行 UPDATE。

    ``OpsStore`` 的连接是默认 ``check_same_thread=True`` 建的，后台心跳线程拿它
    去写会当场抛 ProgrammingError；就算关掉这个开关，也会和执行线程正在跑的事务
    共用一条连接（BEGIN 撞 BEGIN），把业务写坏。所以心跳线程自带连接。

    连接**懒开**：在真正跑心跳的那个线程里才 connect，close 也在同一线程，
    不留跨线程句柄，也不会给「一次任务多留一个 fd」。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path or "")
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=HEARTBEAT_BUSY_TIMEOUT_MS / 1000.0,
            #: 自动提交：一行 UPDATE 不值得开显式事务，也不该长时间攥着写锁。
            isolation_level=None,
        )
        conn.execute(f"PRAGMA busy_timeout={HEARTBEAT_BUSY_TIMEOUT_MS}")
        return conn

    def beat(self, run_id: str) -> bool:
        """推进一次心跳。返回 False 表示这条 run 已不是 running（或没得写）。"""
        run = str(run_id or "")
        if not run or not self._db_path:
            return False
        if self._conn is None:
            self._conn = self._connect()
        cursor = self._conn.execute(HEARTBEAT_SQL, (_now(), run))
        try:
            return int(cursor.rowcount or 0) == 1
        finally:
            cursor.close()

    def close(self) -> None:
        """幂等关连接。必须在开连接的那个线程调用。"""
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.close()
        except sqlite3.Error:
            logger.debug("心跳连接关闭失败", exc_info=True)


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
            ") VALUES(?, ?, ?, ?, ?, 'running', ?, ?, ?, 0, '')",
            (
                run_id,
                job.get("id", ""),
                job.get("name", ""),
                job.get("kind", ""),
                trigger,
                # started_at 必须与 heartbeat_at / finished_at / last_run_at 同一口径,
                # 否则任何跨字段的时间差都会凭空差出一个时区(8 小时)。
                _now(),
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
                "UPDATE job_runs SET status = 'failed', finished_at = ?, "
                "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
                "WHERE job_id = ? AND status = 'running' "
                f"AND {RUN_STALE_SQL}",
                (_now(), stale_msg, job_id, f"-{stale_seconds} seconds"),
            )
            active = cursor.execute(
                "SELECT id FROM job_runs WHERE job_id = ? AND status = 'running' "
                f"ORDER BY {RUN_ORDER_SQL} LIMIT 1",
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
            "SELECT id, owner_pid, started_at, heartbeat_at FROM job_runs "
            "WHERE status = 'running' AND owner_pid > 0"
        ).fetchall()
        dead_ids: list[str] = []
        restarted_ids: list[str] = []
        me = current_pid()
        for row in rows:
            pid = int(row["owner_pid"] or 0)
            last_clock = str(row["heartbeat_at"] or "").strip() or str(
                row["started_at"] or ""
            )
            if not pid_is_alive(pid):
                dead_ids.append(str(row["id"]))
            elif pid == me and started_before_this_process(last_clock):
                restarted_ids.append(str(row["id"]))
        total = 0
        if dead_ids:
            total += self._fail_running_ids(cursor, dead_ids, DEAD_PID_RUN_ERROR)
        if restarted_ids:
            total += self._fail_running_ids(
                cursor, restarted_ids, RESTARTED_PID_RUN_ERROR
            )
        return total

    @staticmethod
    def _fail_running_ids(
        cursor: sqlite3.Cursor, run_ids: list[str], error: str
    ) -> int:
        placeholders = ",".join("?" for _ in run_ids)
        cursor.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = ?, "
            "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
            f"WHERE id IN ({placeholders}) AND status = 'running'",
            (_now(), error, *run_ids),
        )
        return int(cursor.rowcount or 0)

    def _reclaim_legacy_no_pid_runs(self, cursor: sqlite3.Cursor) -> int:
        cursor.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = ?, "
            "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
            "WHERE status = 'running' AND owner_pid = 0 "
            # 无 pid 的行一定不是本版代码写的（``_insert_run`` 永远写入 os.getpid() > 0）,
            # 所以这一支顺带兜住「时间戳根本解析不了」的脏行：它们既没有进程可探活,
            # 也永远过不了时间窗，不在这里收就会把任务槽永久卡在假「正在执行」。
            f"AND ({RUN_STALE_SQL} OR julianday({RUN_CLOCK_SQL}) IS NULL)",
            (_now(), LEGACY_NO_PID_ERROR, f"-{LEGACY_NO_PID_STALE_SECONDS} seconds"),
        )
        return int(cursor.rowcount or 0)

    def _reclaim_stale_runs(self, cursor: sqlite3.Cursor) -> int:
        total = self._reclaim_dead_pid_runs(cursor)
        total += self._reclaim_legacy_no_pid_runs(cursor)
        for kind, seconds in STALE_RUN_SECONDS_BY_KIND.items():
            msg = f"{STALE_RUN_ERROR}（{kind}>{max(1, seconds // 60)}分钟）"
            cursor.execute(
                "UPDATE job_runs SET status = 'failed', finished_at = ?, "
                "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
                "WHERE kind = ? AND status = 'running' "
                f"AND {RUN_STALE_SQL}",
                (_now(), msg, kind, f"-{seconds} seconds"),
            )
            total += int(cursor.rowcount or 0)
        cursor.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = ?, "
            "error_text = CASE WHEN error_text = '' THEN ? ELSE error_text END "
            "WHERE status = 'running' "
            "AND kind NOT IN (" + ",".join("?" for _ in STALE_RUN_SECONDS_BY_KIND) + ") "
            f"AND {RUN_STALE_SQL}",
            (
                _now(),
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
            cursor.execute(HEARTBEAT_SQL, (_now(), run_id))
            return cursor.rowcount == 1

    def run_heartbeat_writer(self) -> RunHeartbeatWriter:
        """给后台心跳线程用的写入器（独立连接，见 ``RunHeartbeatWriter``）。

        ``JobContext``/``HeartbeatPump`` 只认这个鸭子接口（``beat`` + ``close``）：
        拿不到就回落到主线程 ``heartbeat_run``，旧 store / 测试替身不会因此报错。
        """
        return RunHeartbeatWriter(str(getattr(self, "db_path", "")))

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
        # BEGIN IMMEDIATE 而不是 deferred：下面是「先 SELECT 状态、再 UPDATE 终态」。
        # WAL 下 deferred 事务读了快照之后，若别的连接（比如本 run 自己的心跳线程）
        # 已提交过写入，升级写锁会立刻拿到 SQLITE_BUSY_SNAPSHOT——busy_timeout 对
        # 这种冲突不生效，收尾会平白失败。开局就拿写锁则只会正常排队。
        with self._transaction(immediate=True) as cursor:
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
            # 一次收尾只取一次时钟：finished_at 与 heartbeat_at 写成同一个值,
            # 免得两次 _now() 之间跨秒，读的人以为「收尾之后还跳了一次心跳」。
            ended_at = _now()
            cursor.execute(
                "UPDATE job_runs SET status = ?, finished_at = ?,"
                " heartbeat_at = ?, duration_ms = ?, result_json = ?,"
                " error_text = ? WHERE id = ? AND status = 'running'",
                (status, ended_at, ended_at, int(duration_ms),
                 dumps(result if result is not None else {}),
                 error[:4000], run_id),
            )
            if cursor.rowcount != 1:
                raise OpsError("任务运行已进入终态")
            if current["job_id"]:
                cursor.execute(
                    "UPDATE jobs SET last_run_at = ?, last_status = ?,"
                    " updated_at = ? WHERE id = ?",
                    (ended_at, status, ended_at, current["job_id"]),
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
        sql += f" ORDER BY {RUN_ORDER_SQL} LIMIT ?"
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
                f"""
                DELETE FROM job_runs WHERE status <> 'running' AND id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY job_id ORDER BY {RUN_ORDER_SQL}
                        ) AS rn FROM job_runs
                    ) ranked WHERE rn > ?
                )
                """,
                (max(1, int(keep_per_job)),),
            )
            return cursor.rowcount
