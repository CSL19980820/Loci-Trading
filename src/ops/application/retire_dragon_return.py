"""龙回头纸面舱退役：删舱、卸技能、清任务，并禁止启动时再挂回来。

盘面 GET ``/paper-cabins/dragon-return`` 会 ``ensure`` 出舱，启动时
``reconcile_dragon_return_jobs`` 再按舱把监测/日终任务拉起来——所以只在库里
删一行，重启或打开首页就会复活。退役必须落到数据，并且调用方不再隐式建舱。
"""
from __future__ import annotations

import logging
from typing import Any

RETIRED_SLUG = "dragon-return"
RETIRED_JOB_NAME = "监测·龙回头"
RETIRED_FEED = f"skill_watch:{RETIRED_SLUG}"
RETIRED_SETTING_KEYS = (
    f"unified_monitor_pool:{RETIRED_SLUG}",
    f"paper_live_pool:{RETIRED_SLUG}",
    f"paper_follow_hold:{RETIRED_SLUG}",
    f"paper_eod_manual_push_receipt:{RETIRED_SLUG}",
    f"watch_tuning:{RETIRED_SLUG}",
)

logger = logging.getLogger(__name__)


def is_retired_paper_cabin(slug: str) -> bool:
    key = str(slug or "").strip()
    return key in {RETIRED_SLUG, "dragon-pool"}


def load_paper_cabin(store: Any, slug: str) -> dict[str, Any]:
    """Job / 执行路径取舱。退役 slug 只读已有行，绝不 INSERT。"""
    key = str(slug or "").strip()
    if not key:
        return {}
    if is_retired_paper_cabin(key):
        cabin = store.get_paper_cabin(key)
        return cabin if isinstance(cabin, dict) else {}
    return store.ensure_paper_cabin(key)


def remove_jobs_for_slug(store: Any, slug: str) -> list[str]:
    """按 config.skill / config.slug / 监测中文名删掉该战法的定时任务。"""
    key = str(slug or "").strip()
    if not key:
        return []
    removed: list[str] = []
    # 只精确匹配纸面舱任务名。禁止用「龙回头」子串——同族战法的任务名都带这三个字。
    watch_names = (
        {
            RETIRED_JOB_NAME,
            f"监测·{key}",
            f"skill:{key}",
            "盘后复盘·龙回头",
            f"盘后复盘·{key}",
            "纸面盯盘·龙回头",
            f"纸面盯盘·{key}",
        }
        if key == RETIRED_SLUG
        else {f"监测·{key}", f"skill:{key}"}
    )
    for job in store.list_jobs() or []:
        cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
        job_slug = str(cfg.get("skill") or cfg.get("slug") or "").strip()
        name = str(job.get("name") or "").strip()
        hit = job_slug == key or name in watch_names
        if not hit:
            continue
        if store.delete_job(str(job.get("id") or "")):
            removed.append(name or key)
    return removed


def _remove_skill() -> bool:
    try:
        from src.ops.application.skills import SkillError, uninstall_skill
    except ImportError:
        return False
    try:
        return bool(uninstall_skill(RETIRED_SLUG))
    except SkillError as exc:
        logger.warning("卸载龙回头技能包失败：%s", exc)
        return False


def _clear_settings(store: Any) -> list[str]:
    cleared: list[str] = []
    for key in RETIRED_SETTING_KEYS:
        try:
            if store.delete_setting(key):
                cleared.append(key)
        except Exception as exc:  # noqa: BLE001 — 清残留失败不该拦住启动
            logger.warning("清理龙回头状态键 %s 失败：%s", key, exc)
    return cleared


def retire_dragon_return(store: Any) -> dict[str, Any]:
    """幂等退役：任务、技能包、纸面舱、统一池快照一并清掉。"""
    removed_jobs = remove_jobs_for_slug(store, RETIRED_SLUG)
    removed_skill = _remove_skill()
    cleared = _clear_settings(store)
    removed_cabin = False
    try:
        removed_cabin = bool(store.delete_paper_cabin(RETIRED_SLUG))
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除龙回头纸面舱失败：%s", exc)
    return {
        "slug": RETIRED_SLUG,
        "removed_jobs": removed_jobs,
        "removed_skill": removed_skill,
        "cleared_settings": cleared,
        "removed_cabin": removed_cabin,
    }


__all__ = [
    "RETIRED_FEED",
    "RETIRED_JOB_NAME",
    "RETIRED_SETTING_KEYS",
    "RETIRED_SLUG",
    "is_retired_paper_cabin",
    "load_paper_cabin",
    "remove_jobs_for_slug",
    "retire_dragon_return",
]
