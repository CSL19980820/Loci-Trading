"""定时调度：把 jobs 表里的 cron 变成真的会自己跑起来的任务。

用 APScheduler 的进程内调度，不引入 Celery/Redis——单机单用户，多一个
broker 和 worker 进程只是多两个会挂的东西。

## 必须单 worker

APScheduler 是**进程内**单例。如果 uvicorn 起了多个 worker，同一条 cron
会被每个 worker 各触发一次：行情被重复抓、AI 简报生成两遍、token 烧双倍。
已实测服务器容器的启动命令没有 --workers（默认 1），本模块启动时会再
主动确认一次并在异常时告警，而不是默默地跑出重复任务。

## 多租户装载

``ops.db`` 随租户分库（``src/shared/tenancy.py``），调度器却只有一个。装载时
必须遍历活跃租户，否则子租户的任务永远不触发——UI 上还写着「下次触发 15:30」。

- 主租户装**全部**任务；其他活跃租户只装**非系统级**任务。行情同步 / 热库重建 /
  库体检 / 清理 / 盘中留存写的是全局共享的 ``market.db``，只该跑一份，
  判据见 ``src/ops/application/tenant_jobs.py`` 的 ``SYSTEM_JOB_KINDS``。
- APScheduler job id 带 ``t:<tenant>:`` 前缀，避免不同租户的 job id 撞名。
  主租户保持裸 job id 不变——``/api/jobs/schedule`` 按 id 匹配实况。
- 主租户的任务进 ``default`` 线程池（``LOCI_SYSTEM_JOB_CONCURRENCY``，默认 4），
  子租户的任务进 ``tenant`` 线程池（``LOCI_TENANT_JOB_CONCURRENCY``，默认 2）。
  **两个池物理隔离**：租户任务再多也挤不掉行情同步。APScheduler 默认只有一个
  10 条线程的池，50 个租户 15:30 同时到期就把它占满了，日终重刷排不上队。
- 拿不到租户槽位时**不阻塞**，落一条 ``skipped`` 留痕后返回；
  租户总数上限 ``LOCI_MAX_SCHEDULED_TENANTS``（默认 50）。
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.executors.pool import ThreadPoolExecutor as APThreadPool
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ops.application.jobs import JobContext, run_job
from src.ops.application.tenant_jobs import (
    active_tenant_roster,
    list_active_tenants,
    max_scheduled_tenants,
    record_tenant_job_skipped,
    run_tenant_job,
    system_job_concurrency,
    tenant_job_concurrency,
    tenant_job_rows,
)
from src.ops.application.trading_schedule import is_interval_run_allowed
from src.ops.infrastructure.store import OpsStore
from src.shared.tenancy import PRIMARY_TENANT, current_tenant, tenant_scope

logger = logging.getLogger(__name__)

#: 任务错过触发时间后，多久之内仍然补跑。超过就跳过——盘后同步晚 4 小时
#: 才跑起来没有意义，不如等下一个交易日。
MISFIRE_GRACE_SECONDS = 3600

#: 本仓历史 cron 用 Unix 习惯写 ``1-5`` 表示周一至周五；APScheduler 的
#: ``from_crontab`` 却是 0=周一…6=周日，``1-5`` 会变成周二至周六、整周跳过周一。
_UNIX_WEEKDAYS_MON_FRI = frozenset({"1-5", "1,2,3,4,5"})


class SchedulerError(RuntimeError):
    """调度配置错误。"""


def normalize_cron_weekdays(expression: str) -> str:
    """把 Unix 习惯的工作日字段改成 APScheduler 可识别的 ``mon-fri``。

    已是命名星期（mon/tue/…）或 ``*`` 的原样返回；只改常见的 ``1-5`` 写法，
    避免误伤已经按 APScheduler 编号写的 ``0-4``。
    支持多行或分号分隔的复合 cron 表达式，逐行处理。
    """
    lines = split_cron_expressions(expression)
    if not lines:
        return (expression or "").strip()
    normalized_lines: list[str] = []
    for line in lines:
        fields = line.split()
        if len(fields) == 5:
            dow = fields[4].strip().lower()
            if dow in _UNIX_WEEKDAYS_MON_FRI:
                fields[4] = "mon-fri"
                line = " ".join(fields)
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def split_cron_expressions(expression: str) -> list[str]:
    """拆分多行或分号分隔的多个 cron 表达式。"""
    if not expression or not expression.strip():
        return []
    lines: list[str] = []
    for raw in expression.replace(";", "\n").splitlines():
        cleaned = raw.strip()
        if cleaned and not cleaned.startswith("#"):
            lines.append(cleaned)
    return lines


def validate_cron(
    expression: str, *, timezone: str = "Asia/Shanghai"
) -> CronTrigger | list[CronTrigger]:
    """校验 cron 表达式。写错的 cron 必须当场报错，不能等到它不触发。

    支持单个 5 段表达式，也支持多行或分号分隔的多个表达式（如 14:50 与 15:30 各跑一次）。
    单条返回单个 ``CronTrigger``，多条返回 ``list[CronTrigger]``。
    """
    lines = split_cron_expressions(expression)
    if not lines:
        raise SchedulerError("cron 表达式为空")

    triggers: list[CronTrigger] = []
    for line in lines:
        fields = line.split()
        if len(fields) != 5:
            raise SchedulerError(
                f"cron 需要 5 个字段（分 时 日 月 周），实际 {len(fields)} 个：{line!r}。"
                " 例：'50 14 * * mon-fri' 或 '30 15 * * mon-fri'，多时点可用换行或分号分隔"
            )
        normalized = normalize_cron_weekdays(line)
        try:
            triggers.append(CronTrigger.from_crontab(normalized, timezone=timezone))
        except Exception as exc:
            raise SchedulerError(f"非法的 cron 表达式 {line!r}：{exc}") from exc

    return triggers[0] if len(triggers) == 1 else triggers

#: 非主租户能建的 cron 最小间隔（秒）。``* * * * *`` 现在语法完全合法，一个
#: 普通成员就能靠它每分钟拉起一轮选股，把租户池长期占满。5 分钟与托管的
#: 「价格提醒扫描」（``*/5 9-14``）同节奏——再密也会被规则冷却吃掉，没有收益。
MIN_TENANT_CRON_INTERVAL_SECONDS = 300


def cron_interval_seconds(
    expression: str,
    *,
    timezone: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> float | None:
    """cron 接下来两次触发之间隔多少秒；算不出来返回 ``None``。

    不做「解析 cron 语法推导周期」那套：字段组合的花样太多，自己推早晚会漏。
    直接让 ``CronTrigger`` 报两个时间点相减，它怎么理解表达式，闸门就怎么判。
    注意这只看**紧接着的那一档**间隔——足够拦住 ``* * * * *`` 这类持续高频，
    不承诺覆盖疏密不均的表达式。
    """
    raw_triggers = validate_cron(expression, timezone=timezone)
    triggers = raw_triggers if isinstance(raw_triggers, list) else [raw_triggers]
    clock = now or datetime.now(ZoneInfo(timezone))
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ZoneInfo(timezone))

    all_fires: list[datetime] = []
    for tr in triggers:
        f1 = tr.get_next_fire_time(previous_fire_time=None, now=clock)
        if f1 is not None:
            all_fires.append(f1)
            f2 = tr.get_next_fire_time(previous_fire_time=f1, now=f1)
            if f2 is not None:
                all_fires.append(f2)

    all_fires.sort()
    if len(all_fires) < 2:
        return None
    return (all_fires[1] - all_fires[0]).total_seconds()


def next_cron_fire_at(
    expression: str,
    *,
    timezone: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> str | None:
    """根据 cron 推算下次触发（ISO）。调度器未启动时供 UI 展示。"""
    raw_triggers = validate_cron(expression, timezone=timezone)
    triggers = raw_triggers if isinstance(raw_triggers, list) else [raw_triggers]
    clock = now or datetime.now(ZoneInfo(timezone))
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ZoneInfo(timezone))
    nxt_times: list[datetime] = []
    for tr in triggers:
        t = tr.get_next_fire_time(previous_fire_time=None, now=clock)
        if t is not None:
            nxt_times.append(t)
    if not nxt_times:
        return None
    nxt_times.sort()
    return nxt_times[0].isoformat()


def preview_upcoming_jobs(
    jobs: list[dict[str, Any]],
    *,
    timezone: str = "Asia/Shanghai",
    live: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """为启用任务填 next_run_at：优先调度器实况，否则按 cron 推算。"""
    live_map = live or {}
    rows: list[dict[str, Any]] = []
    for job in jobs:
        cron = str(job.get("cron") or "").strip()
        if not cron:
            continue
        hit = live_map.get(job["id"])
        next_at = hit.get("next_run_at") if hit else None
        if not next_at:
            try:
                next_at = next_cron_fire_at(cron, timezone=timezone)
            except SchedulerError:
                next_at = None
        rows.append(
            {
                "id": job["id"],
                "name": job.get("name") or "",
                "next_run_at": next_at,
            }
        )
    return rows


#: 租户任务的 APScheduler job id 前缀。主租户**不加前缀**：``/api/jobs/schedule``
#: 与行情同步设置页都按裸 job id 去 ``upcoming()`` 里查实况，加了就查不到了。
TENANT_JOB_ID_PREFIX = "t:"

#: APScheduler 的 executor 名。``default`` 是系统池（主租户任务），``tenant``
#: 是租户池。两个池物理隔离，见 ``JobScheduler.__init__`` 的注释。
SYSTEM_EXECUTOR = "default"
TENANT_EXECUTOR = "tenant"


def tenant_job_key(tenant_id: str, job_id: str) -> str:
    """租户任务在 APScheduler 里的唯一 id。"""
    if tenant_id == PRIMARY_TENANT:
        return str(job_id)
    return f"{TENANT_JOB_ID_PREFIX}{tenant_id}:{job_id}"


class JobScheduler:
    """jobs 表的调度器。表变了就调 reload 重新装载。

    多租户：主租户装全部任务，其他活跃租户只装非系统级任务（见模块头注释）。
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        context_factory=None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.db_path = db_path
        self.timezone = timezone
        self._context_factory = context_factory or (lambda: JobContext())
        #: 两个线程池，**物理隔离**，这是「租户任务挤不掉行情同步」的唯一保证。
        #:
        #: APScheduler 3.x 原生支持多 executor，本仓此前从未覆盖过默认配置——
        #: 默认只有一个 ``ThreadPoolExecutor(max_workers=10)``。50 个租户 15:30 同时
        #: 到期时，10 条线程全被租户任务占住，15:10 的日终重刷、盘中增量只能干等，
        #: 而调度器本身也就等于停摆了。拆成两个池之后：
        #:
        #: - ``default``（系统池，``LOCI_SYSTEM_JOB_CONCURRENCY``，默认 4）只跑主租户
        #:   的任务，行情同步永远有自己的线程；
        #: - ``tenant``（租户池，``LOCI_TENANT_JOB_CONCURRENCY``，默认 2）跑所有子租户
        #:   的任务，再多也只能把自己这个池占满。
        #:
        #: 池宽就是并发上限，所以不再需要「等 300 秒抢信号量」那套；``ThreadPoolExecutor``
        #: 的队列无界，排队不会丢任务，陈旧的那些由 ``max_instances=1`` +
        #: ``misfire_grace_time`` 收口。
        self._pool_sizes = {
            SYSTEM_EXECUTOR: system_job_concurrency(),
            TENANT_EXECUTOR: tenant_job_concurrency(),
        }
        self._scheduler = BackgroundScheduler(
            timezone=timezone,
            executors={
                SYSTEM_EXECUTOR: APThreadPool(
                    max_workers=self._pool_sizes[SYSTEM_EXECUTOR]
                ),
                TENANT_EXECUTOR: APThreadPool(
                    max_workers=self._pool_sizes[TENANT_EXECUTOR]
                ),
            },
            job_defaults={
                "coalesce": True,  # 错过多次只补跑一次
                "max_instances": 1,  # 同一任务不并发，防上一轮没跑完又起一轮
                "misfire_grace_time": MISFIRE_GRACE_SECONDS,
            },
        )
        self._lock = threading.Lock()
        self._started = False
        #: 租户池的**非阻塞**槽位。正常情况下它与池宽一样大，永远拿得到；只有在
        #: 运行期调小了 LOCI_TENANT_JOB_CONCURRENCY（reload 会重建闸门，但线程池宽度
        #: 是进程启动时定的）才会真的拦下来。拿不到就落 skipped 留痕，**绝不阻塞**：
        #: 堵在这里就是拿调度线程去等另一个调度线程。
        self._tenant_gate = threading.BoundedSemaphore(tenant_job_concurrency())
        #: APScheduler job id -> (租户, 原始 job id)。不靠拆字符串反推：任务名里
        #: 完全可能带冒号。
        self._job_index: dict[str, tuple[str, str]] = {}
        self._tenant_stats: dict[str, Any] = {
            "count": 1,
            "ids": [PRIMARY_TENANT],
            "jobs": 0,
            "total_active": 1,
            "truncated": False,
            "degraded": False,
        }

    # ---- 生命周期 -------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        _warn_if_multi_worker()
        self._scheduler.start()
        self._started = True
        self._ensure_tenant_managed_jobs()
        self.reload()
        try:
            with OpsStore(self.db_path) as store:
                n = store.reclaim_stale_runs()
                if n:
                    logger.warning("调度器启动时回收了 %s 条超时 running 记录", n)
        except Exception:
            logger.exception("调度器启动回收超时 running 失败")
        logger.info("调度器已启动（时区 %s）", self.timezone)

    def shutdown(self, *, wait: bool = False) -> None:
        if self._started:
            self._scheduler.shutdown(wait=wait)
            self._started = False

    # ---- 装载 -----------------------------------------------------

    def _ensure_tenant_managed_jobs(self) -> None:
        """给每个非主租户确保用户级托管任务。

        主租户由 ``src/app/main.py`` 启动时确保；子租户没人管——不在这里做一次，
        新用户的 ``ops.db`` 里 jobs 表永远是空的，装载了也没东西可跑。

        只在 ``start()`` 做一次，``reload()`` 不重复：确保会加载整个战法目录，
        而 reload 每次任务增删都会被调用。
        """
        if os.environ.get("LOCI_ENSURE_TENANT_JOBS", "1").strip().lower() in {
            "0",
            "false",
            "no",
        }:
            return
        try:
            from src.ops.application.ensure_managed_jobs import ensure_tenant_jobs

            for tenant_id in list_active_tenants():
                if tenant_id == PRIMARY_TENANT:
                    continue
                try:
                    with tenant_scope(tenant_id), OpsStore(None) as store:
                        ensure_tenant_jobs(store)
                except Exception:  # noqa: BLE001 — 一个租户失败不阻断其他租户
                    logger.warning(
                        "租户 %s 的托管任务确保失败", tenant_id, exc_info=True
                    )
        except Exception:  # noqa: BLE001 — 确保阶段失败不该拦住调度器启动
            logger.exception("租户托管任务确保阶段失败")

    def reload(self) -> dict[str, Any]:
        """按各租户的 jobs 表重建调度计划。

        返回装载结果：``loaded`` / ``rejected`` / ``count`` 与拆分前一致，新增
        ``tenants``（装了几个租户、其中租户级任务几条、是否被截断/降级）。
        """
        loaded: list[str] = []
        rejected: list[dict[str, str]] = []
        roster = active_tenant_roster()
        tenant_ids = list(roster["tenants"])
        index: dict[str, tuple[str, str]] = {}
        tenant_job_total = 0

        with self._lock:
            self._scheduler.remove_all_jobs()
            # 闸门在这里重建：改了 LOCI_TENANT_JOB_CONCURRENCY 后 reload 即生效，
            # 不用重启进程（线程池宽度仍是进程启动时那个，闸门只会更严不会更松）。
            self._tenant_gate = threading.BoundedSemaphore(tenant_job_concurrency())

            for tenant_id in tenant_ids:
                primary = tenant_id == PRIMARY_TENANT
                try:
                    jobs = tenant_job_rows(tenant_id, db_path=self.db_path)
                except Exception as exc:  # noqa: BLE001 — 一个租户的库坏了不该拖垮全局
                    logger.warning("读取租户 %s 的任务表失败，本轮不装载：%s", tenant_id, exc)
                    rejected.append(
                        {"name": f"[{tenant_id}] 全部任务", "reason": f"任务表读取失败：{exc}"}
                    )
                    continue

                for job in jobs:
                    if not job.get("cron"):
                        continue  # 没有 cron 的任务只能手动触发，不算错误
                    label = job["name"] if primary else f"[{tenant_id}] {job['name']}"
                    try:
                        raw_triggers = validate_cron(job["cron"], timezone=self.timezone)
                    except SchedulerError as exc:
                        # 一条写错的 cron 不该让其他任务也装不上。
                        rejected.append({"name": label, "reason": str(exc)})
                        logger.warning("任务 %s 的 cron 非法，已跳过：%s", label, exc)
                        continue
                    triggers = (
                        raw_triggers if isinstance(raw_triggers, list) else [raw_triggers]
                    )
                    for idx, trigger in enumerate(triggers):
                        key = tenant_job_key(tenant_id, job["id"])
                        if len(triggers) > 1:
                            key = f"{key}#{idx}"
                        self._scheduler.add_job(
                            self._run_tenant,
                            trigger=trigger,
                            args=[tenant_id, job["id"]],
                            id=key,
                            name=label,
                            replace_existing=True,
                            executor=SYSTEM_EXECUTOR if primary else TENANT_EXECUTOR,
                        )
                        index[key] = (tenant_id, str(job["id"]))
                    loaded.append(job["name"])
                    if not primary:
                        tenant_job_total += 1

            self._job_index = index
            self._tenant_stats = {
                "count": len(tenant_ids),
                "ids": tenant_ids,
                "jobs": tenant_job_total,
                "total_active": int(roster["total"]),
                "truncated": bool(roster["truncated"]),
                "degraded": bool(roster["degraded"]),
                "concurrency": tenant_job_concurrency(),
                "system_concurrency": system_job_concurrency(),
                "executors": dict(self._pool_sizes),
                "max_tenants": max_scheduled_tenants(),
            }

        return {
            "loaded": loaded,
            "rejected": rejected,
            "count": len(loaded),
            "tenants": dict(self._tenant_stats),
        }

    def _run_tenant(
        self, tenant_id: str, job_id: str, *, now: datetime | None = None
    ) -> None:
        """租户任务的调度入口。

        主租户走原来的 ``_run``（一个字都没改，行为与单租户时代一致）；子租户在
        ``tenant`` 线程池里执行，切到自己的 ``tenant_scope``。

        并发上限由**池宽**保证，不再阻塞等信号量：这里的 ``acquire`` 是非阻塞的，
        拿不到就落一条 ``skipped`` 记录后立刻返回。旧写法 ``acquire(timeout=300)``
        会让一条调度线程干等 5 分钟——池子一共才那么几条线程，等于自己把自己堵死。
        """
        if tenant_id == PRIMARY_TENANT:
            self._run(job_id, now=now)
            return
        gate = self._tenant_gate
        if not gate.acquire(blocking=False):
            reason = (
                "租户任务并发槽位已满（LOCI_TENANT_JOB_CONCURRENCY="
                f"{tenant_job_concurrency()}），本轮跳过，下一轮再跑"
            )
            logger.warning("租户 %s 的任务 %s %s", tenant_id, job_id, reason)
            record_tenant_job_skipped(
                tenant_id, job_id, reason=reason, db_path=self.db_path
            )
            return
        try:
            run_tenant_job(
                tenant_id,
                job_id,
                context=self._context_factory(),
                trigger="schedule",
                now=now,
                timezone=self.timezone,
            )
        finally:
            gate.release()

    def _run(self, job_id: str, *, now: datetime | None = None) -> None:
        """主租户的执行入口。异常必须吞在这里。

        APScheduler 的 job 抛异常只会打日志，但我们要的是留在 job_runs 里
        可查——run_job 已经做了完整记录，这里再兜一层防它自己炸掉。
        """
        try:
            with OpsStore(self.db_path) as store:
                job = store.get_job(job_id)
                if job is None:
                    logger.warning("调度任务 %s 已不存在，跳过本次触发", job_id)
                    return
                config = job.get("config")
                schedule = config.get("schedule") if isinstance(config, dict) else None
                clock = now or datetime.now(ZoneInfo(self.timezone))
                if not is_interval_run_allowed(schedule, now=clock):
                    logger.debug("任务 %s 当前不在 interval 执行窗口内，跳过", job.get("name"))
                    return
                run_job(store, job, context=self._context_factory(), trigger="schedule")
        except Exception:
            logger.exception("调度执行任务 %s 时发生未捕获异常", job_id)

    # ---- 观测 -----------------------------------------------------

    @property
    def tenants(self) -> dict[str, Any]:
        """最近一次 reload 的租户装载概况。"""
        return dict(self._tenant_stats)

    def upcoming(self) -> list[dict[str, Any]]:
        """下一次触发时间。用来回答"我的定时任务到底装上没有"。

        ``id`` 是 APScheduler 的 job id：主租户等于原始 job id（存量调用方按它
        匹配），子租户是带前缀的 key。``job_id`` / ``tenant`` 是新增的分解字段。
        """
        rows: list[dict[str, Any]] = []
        for job in self._scheduler.get_jobs():
            tenant_id, raw_id = self._job_index.get(job.id, (PRIMARY_TENANT, job.id))
            # 调度器还没 start 时 APScheduler 的 job 仍是 pending 状态，压根没有
            # next_run_time 属性——直接点出来会 AttributeError。
            nxt = getattr(job, "next_run_time", None)
            rows.append(
                {
                    "id": job.id,
                    "job_id": raw_id,
                    "tenant": tenant_id,
                    "name": job.name,
                    "next_run_at": nxt.isoformat() if nxt else None,
                }
            )
        return rows

    def upcoming_for_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """合并调度器实况与 cron 推算：未装载时仍给出下次触发。

        按**当前租户**过滤：两个租户的 jobs 表各自独立，job id 完全可能重合，
        不过滤就会把 A 的下次触发显示到 B 的任务上。
        """
        tenant = current_tenant()
        live = {
            item["job_id"]: item for item in self.upcoming() if item["tenant"] == tenant
        }
        return preview_upcoming_jobs(jobs, timezone=self.timezone, live=live)

    @property
    def running(self) -> bool:
        return self._started and self._scheduler.running


def _warn_if_multi_worker() -> None:
    """多 worker 下进程内调度会重复触发，必须显式告警。"""
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
    try:
        count = int(workers) if workers else 1
    except ValueError:
        count = 1
    if count > 1:
        logger.error(
            "检测到 %s 个 worker，但调度器是进程内单例：同一条 cron 会被每个 worker "
            "各触发一次，导致重复抓取行情、重复消耗 token。请改为单 worker，"
            "或把调度拆成独立进程。",
            count,
        )
