"""启动时补跑错过的盘后定点任务。

桌面端常在 15:30 之后才打开：APScheduler 的 ``misfire_grace_time`` 仅 1 小时，
超过即永久跳过，导致 ``screen:*`` 整日空白、首页「今日选股」无入库。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.infrastructure.scheduler import split_cron_expressions

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
#: 仅补跑这些 kind，避免把盘中增量同步在周末狂刷一遍。
_CATCHUP_KINDS = frozenset({"screen", "sync", "outcome"})
#: ``jobs_due_for_eod_catchup`` 附在返回项上的键：本次要补的那个触发点。
CATCHUP_SLOT_KEY = "catchup_slot"


def parse_once_cron(cron: str) -> tuple[int, int] | None:
    """解析单行 ``M H * * 1-5`` 形态；其它（间隔/复杂）返回 None。"""
    parts = str(cron or "").strip().split()
    if len(parts) != 5:
        return None
    minute_s, hour_s, dom, month, dow = parts
    if dom != "*" or month != "*":
        return None
    if dow not in {"1-5", "MON-FRI", "mon-fri"}:
        return None
    if not minute_s.isdigit() or not hour_s.isdigit():
        return None
    minute, hour = int(minute_s), int(hour_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def parse_once_slots(cron: str) -> list[tuple[int, int]]:
    """多时点 cron（换行 / 分号分隔，与 ``validate_cron`` 同口径）逐行解析成定点。

    解析不出的行（间隔等）忽略；全部解析不出返回空列表，任务不参与补跑。
    """
    slots: list[tuple[int, int]] = []
    for line in split_cron_expressions(cron):
        parsed = parse_once_cron(line)
        if parsed is not None:
            slots.append(parsed)
    return slots


def slot_for_day(day: str, hour: int, minute: int) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hour, minute, tzinfo=_TZ)


def last_run_covers_slot(last_run_at: str, slot: datetime) -> bool:
    """``last_run_at`` 是否已覆盖该触发点（同日或更晚）。

    ``finish_run`` 现在写的是 ``store_helpers._now()``——本地时区**带偏移**，
    走下面 ``raw.tzinfo is not None`` 那一支：换算成上海时间后精确比较，不再有
    任何猜测成分。

    无时区那一支**必须留着**：库里还躺着改造前用 SQLite ``datetime('now')`` 写的
    UTC naive 值（生产 ``jobs`` 表 14 行全是），而个别环境的旧值又可能是本地钟。
    分不清就 **UTC / 上海本地两种解释任一覆盖即视为已跑**：宁可漏补一次，也不要
    在启动时把当天已经跑过的日终任务再跑一遍。新写入的行不会再走到这一支。
    """
    from datetime import timezone

    text = str(last_run_at or "").strip()
    if not text:
        return False
    try:
        raw = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if raw.tzinfo is not None:
        return raw.astimezone(_TZ) >= slot
    as_utc = raw.replace(tzinfo=timezone.utc).astimezone(_TZ)
    as_local = raw.replace(tzinfo=_TZ)
    return as_utc >= slot or as_local >= slot


def job_succeeded_on_trading_day(
    store: Any, *, job_id: str, day: str, slot: datetime | None = None
) -> bool:
    """该任务是否已有覆盖 ``day`` 的成功记录（按 result.trade_date 或完成日）。

    传 ``slot`` 时进一步要求成功记录的 ``started_at`` 不早于该触发点：多时点任务
    早一档跑成功，不能替晚一档失败的那次顶账。
    """
    from src.ops.application.wecom_push_mark import (
        resolve_push_day,
        shanghai_date_of_timestamp,
    )

    day = str(day or "").strip()[:10]
    job_id = str(job_id or "").strip()
    if not day or not job_id:
        return False
    runs = store.list_runs(job_id=job_id, status="success", limit=40)
    for run in runs:
        result = run.get("result")
        finished = str(run.get("finished_at") or run.get("started_at") or "")
        on_day = (
            isinstance(result, dict) and resolve_push_day(result) == day
        ) or (bool(finished) and shanghai_date_of_timestamp(finished) == day)
        if not on_day:
            continue
        if slot is None:
            return True
        started = str(run.get("started_at") or run.get("finished_at") or "")
        if last_run_covers_slot(started, slot):
            return True
    return False


def jobs_due_for_eod_catchup(
    jobs: list[dict[str, Any]],
    *,
    last_trading_day: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """选出应对 ``last_trading_day`` 已触发却尚未跑过的定点任务。

    返回项是任务的浅拷贝，附带 ``CATCHUP_SLOT_KEY``：该任务最晚一个「已到点、
    ``last_run_at`` 未覆盖」的触发点。多时点任务只要有一个时点漏跑就进名单。
    """
    day = str(last_trading_day or "").strip()[:10]
    if not day:
        return []
    cursor = now or datetime.now(_TZ)
    if cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=_TZ)
    else:
        cursor = cursor.astimezone(_TZ)

    due: list[dict[str, Any]] = []
    for job in jobs:
        if not job.get("enabled", True):
            continue
        config = job.get("config")
        if isinstance(config, dict) and config.get("catch_up") is False:
            continue
        kind = str(job.get("kind") or "")
        if kind not in _CATCHUP_KINDS:
            continue
        last_run_at = str(job.get("last_run_at") or "")
        missed = [
            slot
            for slot in (
                slot_for_day(day, hour, minute)
                for hour, minute in parse_once_slots(str(job.get("cron") or ""))
            )
            if cursor >= slot and not last_run_covers_slot(last_run_at, slot)
        ]
        if not missed:
            continue
        due.append({**job, CATCHUP_SLOT_KEY: max(missed)})
    # 先日终同步，再选股，最后兑现——避免用未刷当日的日 K 选股。
    kind_rank = {"sync": 0, "screen": 1, "outcome": 2}
    due.sort(
        key=lambda j: (
            kind_rank.get(str(j.get("kind") or ""), 9),
            j[CATCHUP_SLOT_KEY],
            str(j.get("name") or ""),
        )
    )
    return due


def run_eod_catchup(
    *,
    ops_store_factory: Any,
    context_factory: Any,
    last_trading_day: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """同步补跑到期任务；供调度器启动后后台线程调用。"""
    from src.ops.application.jobs import run_job

    with ops_store_factory() as store:
        jobs = store.list_jobs(enabled_only=True)
        due = jobs_due_for_eod_catchup(
            jobs, last_trading_day=last_trading_day, now=now
        )
        ran: list[str] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []
        for job in due:
            name = str(job.get("name") or job.get("id") or "")
            job_id = str(job.get("id") or "")
            try:
                if job_id and job_succeeded_on_trading_day(
                    store,
                    job_id=job_id,
                    day=last_trading_day,
                    slot=job.get(CATCHUP_SLOT_KEY),
                ):
                    skipped.append(name)
                    logger.info(
                        "盘后补跑跳过（当日已成功）：%s @%s", name, last_trading_day
                    )
                    continue
                catchup_job = dict(job)
                if job.get("kind") == "screen":
                    catchup_job["config"] = {**(job.get("config") or {}), "date": last_trading_day}
                outcome = run_job(
                    store,
                    catchup_job,
                    context=context_factory(),
                    trigger="catchup",
                )
                if outcome.get("status") == "skipped":
                    skipped.append(name)
                    continue
                if outcome.get("status") != "success":
                    raise RuntimeError(str(outcome.get("error") or "补跑任务未成功"))
                ran.append(name)
                logger.info("盘后补跑完成：%s @%s", name, last_trading_day)
            except Exception as exc:  # noqa: BLE001 — 单任务失败不挡其余
                errors.append({"name": name, "reason": str(exc)})
                logger.warning("盘后补跑失败 %s：%s", name, exc)
        return {
            "last_trading_day": last_trading_day,
            "due": [str(j.get("name") or "") for j in due],
            "ran": ran,
            "skipped": skipped,
            "errors": errors,
        }
