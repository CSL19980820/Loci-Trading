"""龙池退役清理：删任务、卸技能包、清残留状态。

**为什么需要这段代码，而不是把龙池源码删干净就完事**：用户机器上的 `ops.db` 里
已经落着「监测·龙池」任务行、生命周期状态键，和并进龙回头统一池的候选。只删源码
的话，调度器照样按 cron 触发那条任务，执行器找不到引擎就每 5 分钟推一条失败——
比不删更吵。所以退役必须落到数据上。

退役依据（2026-08）：300 个交易日 199 笔成交样本，扣费后相对同日全市场等权基准的
配对超额 T+3 仅 +0.53%（t=1.00，95% 区间 [-0.50%, +1.56%] 跨 0）、超额胜率 43.7%，
入池分数按三等分无区分度；要把该超额证成显著约需 764 笔 ≈ 46 个月。
详见 `docs/research/2026-08-dragon-pool-forward-validation.md`。

所有安装都启动过一次之后，这个模块可以整体删除。
"""
from __future__ import annotations

import logging
from typing import Any

RETIRED_SLUG = "dragon-pool"
RETIRED_JOB_NAME = "监测·龙池"
RETIRED_FEED = f"skill_watch:{RETIRED_SLUG}"
#: 生命周期状态与当日全景销账键；随引擎一起作废。
#: 龙池自己那份统一池快照也要清：`drop_candidate_feed` 只摘龙回头池里的龙池候选，
#: 摘不到 `unified_monitor_pool:dragon-pool`，留着就是一份没人再消费的孤儿名单。
RETIRED_SETTING_KEYS = (
    f"dragon_pool_state:{RETIRED_SLUG}",
    f"dragon_pool_state_undo:{RETIRED_SLUG}",
    f"unified_monitor_pool:{RETIRED_SLUG}",
    "watch_daily_brief",
)

logger = logging.getLogger(__name__)


def _remove_jobs(store: Any) -> list[str]:
    removed: list[str] = []
    for job in store.list_jobs() or []:
        cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
        slug = str(cfg.get("skill") or cfg.get("slug") or "").strip()
        name = str(job.get("name") or "").strip()
        hit = slug == RETIRED_SLUG or (
            name == RETIRED_JOB_NAME and str(job.get("kind") or "") == "skill_watch"
        )
        if not hit:
            continue
        if store.delete_job(str(job.get("id") or "")):
            removed.append(name or slug)
    return removed


def _remove_skill() -> bool:
    try:
        from src.ops.application.skills import SkillError, uninstall_skill
    except ImportError:  # 精简部署可能不带技能子系统
        return False
    try:
        return bool(uninstall_skill(RETIRED_SLUG))
    except SkillError as exc:
        logger.warning("卸载龙池技能包失败：%s", exc)
        return False


def _clear_settings(store: Any) -> list[str]:
    cleared: list[str] = []
    for key in RETIRED_SETTING_KEYS:
        try:
            if store.delete_setting(key):
                cleared.append(key)
        except Exception as exc:  # noqa: BLE001 — 清残留失败不该拦住启动
            logger.warning("清理龙池状态键 %s 失败：%s", key, exc)
    return cleared


def retire_dragon_pool(store: Any) -> dict[str, Any]:
    """幂等退役：任务、技能包、状态键、统一池里的龙池候选一并清掉。"""
    removed_jobs = _remove_jobs(store)
    removed_skill = _remove_skill()
    cleared = _clear_settings(store)
    dropped = 0
    removed_cabin = False
    try:
        from src.ops.application.unified_monitor_pool import (
            DRAGON_SLUG,
            drop_candidate_feed,
        )

        dropped = drop_candidate_feed(store, slug=DRAGON_SLUG, feed=RETIRED_FEED)
    except Exception as exc:  # noqa: BLE001 — 候选清理失败不该拦住启动
        logger.warning("清理龙池候选失败：%s", exc)
    try:
        removed_cabin = bool(store.delete_paper_cabin(RETIRED_SLUG))
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除龙池纸面舱失败：%s", exc)
    return {
        "slug": RETIRED_SLUG,
        "removed_jobs": removed_jobs,
        "removed_skill": removed_skill,
        "cleared_settings": cleared,
        "dropped_candidates": dropped,
        "removed_cabin": removed_cabin,
    }


__all__ = [
    "RETIRED_FEED",
    "RETIRED_JOB_NAME",
    "RETIRED_SETTING_KEYS",
    "RETIRED_SLUG",
    "retire_dragon_pool",
]
