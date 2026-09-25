
"""应用启动时统一确保运维托管任务。

## 系统级 vs 用户级（多租户）

``ops.db`` 随租户分库，但**行情库是全局共享的一份**。因此托管任务拆成两组：

- ``ensure_system_jobs`` —— 行情同步 / 热库重建 / 库体检 / 运维清理 / 盘中留存。
  只在**主租户**确保。这些任务写的是全局 ``market.db``（``prune`` 另外还清
  identity.db / community.db 这两个跨租户全局库），每个租户挂一份等于 N 个
  线程抢同一个 SQLite 写锁、N 份请求把上游打成 403。
- ``ensure_tenant_jobs`` —— 候选跟踪 / 选股 / 情报 / 价格提醒 / **租户库清理**
  + 三条退役清理。在**当前租户**确保。它们本来就读写 ``OpsStore(None)``
  （= 当前租户的库），调用方只要包在 ``tenant_scope(uid)`` 里就是对的。

``ensure_all_managed_jobs`` 保留为「两组都做」的兼容别名：``src/app/main.py``
在主租户上下文里调它，语义与拆分前完全一致。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.ops.application.ensure_alert_scan_job import ensure_managed_alert_scan_job
from src.ops.application.ensure_intraday_capture_job import (
    ensure_managed_intraday_capture_job,
)
from src.ops.application.ensure_prune_tenant_job import ensure_prune_tenant_job
from src.ops.application.ensure_guardian_review_jobs import ensure_guardian_review_jobs, ensure_exchange_calendar_job
from src.ops.application.jobs.guardian_delivery import ensure_guardian_delivery_job
from src.ops.application.stock_agent_service import ensure_stock_agent_jobs
from src.ops.application.retire_dragon_pool import retire_dragon_pool
from src.ops.application.retire_dragon_return import retire_dragon_return
from src.ops.application.retire_second_wave import retire_second_wave
from src.ops.application.retire_yixian_auction import retire_yixian_auction

logger = logging.getLogger(__name__)


def _ensure_step(label: str, ensure: Callable[[], Any]) -> None:
    try:
        plan = ensure()
        logger.info("%s已确保：%s", label, plan)
    except Exception as exc:  # noqa: BLE001 — 单条托管任务失败不能阻断其他任务
        logger.warning("%s确保失败：%s", label, exc)


def ensure_system_jobs(store: Any) -> None:
    """只在主租户确保的系统级托管任务（全部围绕全局行情库）。

    每一步各自 try/except：一条确保失败（库锁、目录加载炸了）不能把后面的带走。
    """
    for label, ensure in (
        ("交易所休市日历", lambda: ensure_exchange_calendar_job(store)),
        ("托管行情同步", store.ensure_managed_market_sync_jobs),
        ("托管行情热库重建", store.ensure_managed_hot_rebuild_job),
        ("托管行情库体检", store.ensure_managed_market_quality_job),
        ("托管运维清理", store.ensure_managed_prune_job),
        # 上游没有历史：漏一天永久缺一天，必须托管（ADR-014）。
        ("托管盘中留存采集", lambda: ensure_managed_intraday_capture_job(store)),
    ):
        _ensure_step(label, ensure)


def ensure_tenant_jobs(store: Any) -> None:
    """在**当前租户**确保用户级托管任务，并幂等退役已撤的三个玩法。

    ``store`` 必须是当前租户的 ``OpsStore``——调用方负责 ``tenant_scope``。
    """
    for label, ensure in (
        # 候选跟踪原先裸调在循环外，不在 _ensure_step 的保护里：它一抛异常，
        # 后面全部托管任务 + 龙池/龙回头退役清理都不会执行，而调用方只看到
        # 一行「托管任务确保失败」。
        ("托管候选T+N跟踪", store.ensure_managed_outcome_job),
        ("托管盘后选股", store.ensure_managed_screen_jobs),
        ("托管情报采集", store.ensure_managed_intel_jobs),
        # 简报推送：四档，各比悟道出稿晚 10 分钟。没配悟道/企微、或这一档还没出稿都是
        # skipped，所以「默认挂上」不会给没用这个功能的安装制造噪音。
        ("托管简报推送", store.ensure_managed_intel_brief_jobs),
        # 价格提醒扫描：用户已经建了启用中的规则才挂，避免给没用这个功能的
        # 安装每天塞 48 条空 run（见 ensure_alert_scan_job 模块注释）。
        ("托管价格提醒扫描", lambda: ensure_managed_alert_scan_job(store)),
        ("天才交易员复盘与计划", lambda: ensure_guardian_review_jobs(store)),
        ("天才交易员通知补发", lambda: ensure_guardian_delivery_job(store)),
        ("股票智能体日程", lambda: ensure_stock_agent_jobs(store)),
    # 租户库清理。系统级 prune 在 SYSTEM_JOB_KINDS 里，子租户一条都不装载，
        # 于是子租户的 ops.db 从建库那天起没人清过（job_runs 粗算 580 MB/年/人，
    # 外加从不清理的八张 ai_* 表）。这一步就是 tenant_jobs.py 模块头点名的
        # 「把 prune 拆成 system 段与 tenant 段」里的后者。
     ("托管租户库清理", lambda: ensure_prune_tenant_job(store)),
    ):
        _ensure_step(label, ensure)

    _retire_removed_playbooks(store)


def _retire_removed_playbooks(store: Any) -> None:
    """退役已撤玩法。按租户执行：任务行在各自的 ops.db 里。"""
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

    # 二波监测 2026-08 退役。它曾是**系统托管**任务：只删源码的话，用户 ops.db 里
    # 那条 `*/5 9-14` 的任务照样触发，执行器找不到技能就每 5 分钟推一条失败。
    try:
        wave_plan = retire_second_wave(store)
        if wave_plan.get("removed_jobs") or wave_plan.get("removed_skill"):
            logger.info("二波监测已退役：%s", wave_plan)
    except Exception as exc:  # noqa: BLE001 — 清理失败不阻断应用启动
        logger.warning("二波监测退役清理失败：%s", exc)

    try:
        yixian_plan = retire_yixian_auction(store)
        if any(
            yixian_plan.get(key)
            for key in (
                "removed_jobs",
                "removed_job_runs",
                "removed_skill",
                "removed_skill_history",
                "removed_cabin",
                "removed_candidates",
            )
        ):
            logger.info("一线定乾坤已退役：%s", yixian_plan)
    except Exception as exc:  # noqa: BLE001 — 清理失败不阻断应用启动
        logger.warning("一线定乾坤退役清理失败：%s", exc)


def ensure_all_managed_jobs(store: Any) -> None:
    """系统级 + 用户级都确保。

    **兼容入口，签名不变**：``src/app/main.py`` 在主租户上下文里调用它，行为与
    多租户拆分前完全一致。新代码请按语义直接调 ``ensure_system_jobs`` /
    ``ensure_tenant_jobs``。
    """
    ensure_system_jobs(store)
    ensure_tenant_jobs(store)
