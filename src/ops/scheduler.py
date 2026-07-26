"""定时调度：把 jobs 表里的 cron 变成真的会自己跑起来的任务。

用 APScheduler 的进程内调度，不引入 Celery/Redis——单机单用户，多一个
broker 和 worker 进程只是多两个会挂的东西。

## 必须单 worker

APScheduler 是**进程内**单例。如果 uvicorn 起了多个 worker，同一条 cron
会被每个 worker 各触发一次：行情被重复抓、AI 简报生成两遍、token 烧双倍。
已实测服务器容器的启动命令没有 --workers（默认 1），本模块启动时会再
主动确认一次并在异常时告警，而不是默默地跑出重复任务。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.ops.jobs import JobContext, run_job
from src.ops.store import OpsStore

logger = logging.getLogger(__name__)

#: 同一个任务的两次触发之间的最小间隔（秒）。防止 cron 写错成每秒一次。
MIN_INTERVAL_SECONDS = 30

#: 任务错过触发时间后，多久之内仍然补跑。超过就跳过——盘后同步晚 4 小时
#: 才跑起来没有意义，不如等下一个交易日。
MISFIRE_GRACE_SECONDS = 3600


class SchedulerError(RuntimeError):
    """调度配置错误。"""


def validate_cron(expression: str) -> CronTrigger:
    """校验 cron 表达式。写错的 cron 必须当场报错，不能等到它不触发。"""
    text = (expression or "").strip()
    if not text:
        raise SchedulerError("cron 表达式为空")
    fields = text.split()
    if len(fields) != 5:
        raise SchedulerError(
            f"cron 需要 5 个字段（分 时 日 月 周），实际 {len(fields)} 个：{text!r}。"
            " 例：'35 15 * * 1-5' 表示工作日 15:35"
        )
    try:
        return CronTrigger.from_crontab(text)
    except Exception as exc:
        raise SchedulerError(f"非法的 cron 表达式 {text!r}：{exc}") from exc


class JobScheduler:
    """jobs 表的调度器。表变了就调 reload 重新装载。"""

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
        self._scheduler = BackgroundScheduler(
            timezone=timezone,
            job_defaults={
                "coalesce": True,          # 错过多次只补跑一次
                "max_instances": 1,        # 同一任务不并发，防上一轮没跑完又起一轮
                "misfire_grace_time": MISFIRE_GRACE_SECONDS,
            },
        )
        self._lock = threading.Lock()
        self._started = False

    # ---- 生命周期 -------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        _warn_if_multi_worker()
        self._scheduler.start()
        self._started = True
        self.reload()
        logger.info("调度器已启动（时区 %s）", self.timezone)

    def shutdown(self, *, wait: bool = False) -> None:
        if self._started:
            self._scheduler.shutdown(wait=wait)
            self._started = False

    # ---- 装载 -----------------------------------------------------

    def reload(self) -> dict[str, Any]:
        """按 jobs 表重建调度计划。返回装载结果，含被拒绝的任务与原因。"""
        loaded: list[str] = []
        rejected: list[dict[str, str]] = []

        with self._lock:
            self._scheduler.remove_all_jobs()
            with OpsStore(self.db_path) as store:
                jobs = store.list_jobs(enabled_only=True)

            for job in jobs:
                if not job.get("cron"):
                    continue  # 没有 cron 的任务只能手动触发，不算错误
                try:
                    trigger = validate_cron(job["cron"])
                except SchedulerError as exc:
                    # 一条写错的 cron 不该让其他任务也装不上。
                    rejected.append({"name": job["name"], "reason": str(exc)})
                    logger.warning("任务 %s 的 cron 非法，已跳过：%s", job["name"], exc)
                    continue
                self._scheduler.add_job(
                    self._run,
                    trigger=trigger,
                    args=[job["id"]],
                    id=job["id"],
                    name=job["name"],
                    replace_existing=True,
                )
                loaded.append(job["name"])

        return {"loaded": loaded, "rejected": rejected, "count": len(loaded)}

    def _run(self, job_id: str) -> None:
        """调度线程里的执行入口。异常必须吞在这里。

        APScheduler 的 job 抛异常只会打日志，但我们要的是留在 job_runs 里
        可查——run_job 已经做了完整记录，这里再兜一层防它自己炸掉。
        """
        try:
            with OpsStore(self.db_path) as store:
                run_job(store, job_id, context=self._context_factory(), trigger="schedule")
        except Exception:
            logger.exception("调度执行任务 %s 时发生未捕获异常", job_id)

    # ---- 观测 -----------------------------------------------------

    def upcoming(self) -> list[dict[str, Any]]:
        """下一次触发时间。用来回答"我的定时任务到底装上没有"。"""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_at": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self._scheduler.get_jobs()
        ]

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
