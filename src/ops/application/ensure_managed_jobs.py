"""应用启动时统一确保运维托管任务。"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.ops.application.ensure_second_wave_job import ensure_second_wave_watch_job
from src.ops.application.retire_dragon_pool import retire_dragon_pool
from src.ops.application.retire_dragon_return import retire_dragon_return

logger = logging.getLogger(__name__)


def _ensure_step(label: str, ensure: Callable[[], dict[str, Any]]) -> None:
    try:
        plan = ensure()
        logger.info("%s已确保：%s", label, plan)
    except Exception as exc:  # noqa: BLE001 — 单条托管任务失败不能阻断其他任务
        logger.warning("%s确保失败：%s", label, exc)


def ensure_all_managed_jobs(store: Any) -> None:
    """确保常规托管任务，并幂等退役已撤的龙池 / 龙回头纸面舱。"""
    store.ensure_managed_outcome_job()
    for label, ensure in (
        ("托管行情同步", store.ensure_managed_market_sync_jobs),
        ("托管行情热库重建", store.ensure_managed_hot_rebuild_job),
                ("托管行情库体检", store.ensure_managed_market_quality_job),
        ("托管运维清理", store.ensure_managed_prune_job),
        ("托管盘后选股", store.ensure_managed_screen_jobs),
        ("托管情报采集", store.ensure_managed_intel_jobs),
    ):
        _ensure_step(label, ensure)

    # 先退役龙池，再退役龙回头纸面舱。后者以前会在这里被 reconcile 重新挂上
    # 监测/日终任务，删舱等于白删。
    try:
        pool_plan = retire_dragon_pool(store)
        if pool_plan.get("removed_jobs") or pool_plan.get("removed_skill"):
            logger.info("龙池已退役：%s", pool_plan)
    except Exception as exc:  # noqa: BLE001 — 清理失败也不该拦住启动
        logger.warning("龙池退役清理失败：%s", exc)

    try:
        paper_plan = retire_dragon_return(store)
        if (
            paper_plan.get("removed_jobs")
            or paper_plan.get("removed_skill")
            or paper_plan.get("removed_cabin")
        ):
            logger.info("龙回头纸面舱已退役：%s", paper_plan)
    except Exception as exc:  # noqa: BLE001 — 清理失败不阻断应用启动
        logger.warning("龙回头纸面舱退役失败：%s", exc)

    _ensure_step("托管二波监测", lambda: ensure_second_wave_watch_job(store))
