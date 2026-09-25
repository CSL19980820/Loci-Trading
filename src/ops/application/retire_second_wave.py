"""二波监测退役清理：删任务、卸技能包、清快照与留痕表。

**为什么需要这段代码，而不是把源码删干净就完事**：`监测·二波监测` 是**系统托管**
任务——历次启动都会把它写进用户的 `ops.db`。只删源码的话，调度器照样按
`*/5 9-14 * * mon-fri` 触发那条任务，执行器找不到技能/引擎就每 5 分钟推一条失败，
比不删更吵（龙池退役踩过同一个坑）。所以退役必须落到数据上：

- `监测·二波监测` / `监测·dragon-second-wave` 任务行
- `data/skills/dragon-second-wave/` 技能包
- 首页快照键 `second_wave_latest`、调参键 `watch_tuning:dragon-second-wave`、
  该 slug 自己的统一池快照，以及别的池子里由它供给的候选（`candidate_feed`）
- 只追加留痕表 `second_wave_signals` 由 `_MIGRATIONS` 里的 `DROP TABLE` 收走

退役理由：2026-08 用户停用。逐笔口径的实测分档留在
`docs/research/2026-08-dragon-second-wave-live-alert-spec.md`（已移除，见提交 d05e02d），想重做同类战法先复现那份。

所有安装都启动过一次之后，这个模块可以整体删除。
"""
from __future__ import annotations

import logging
from typing import Any

RETIRED_SLUG = "dragon-second-wave"
RETIRED_JOB_NAME = "监测·二波监测"
RETIRED_FEED = f"skill_watch:{RETIRED_SLUG}"
#: 首页快照 + 调参 + 该 slug 自己的统一池快照。前两个没人再写，最后一个
#: `drop_candidate_feed` 摘不到（它只摘别的池子里的候选），留着就是孤儿名单。
RETIRED_SETTING_KEYS = (
    "second_wave_latest",
    f"watch_tuning:{RETIRED_SLUG}",
    f"unified_monitor_pool:{RETIRED_SLUG}",
)

logger = logging.getLogger(__name__)


def _remove_jobs(store: Any) -> list[str]:
    """按 config.skill / config.slug / 托管任务名删掉二波的定时任务。"""
    removed: list[str] = []
    names = {RETIRED_JOB_NAME, f"监测·{RETIRED_SLUG}", f"skill:{RETIRED_SLUG}"}
    for job in store.list_jobs() or []:
        cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
        slug = str(cfg.get("skill") or cfg.get("slug") or "").strip()
        name = str(job.get("name") or "").strip()
        if slug != RETIRED_SLUG and name not in names:
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
        logger.warning("卸载二波技能包失败：%s", exc)
        return False


def _clear_settings(store: Any) -> list[str]:
    cleared: list[str] = []
    for key in RETIRED_SETTING_KEYS:
        try:
            if store.delete_setting(key):
                cleared.append(key)
        except Exception as exc:  # noqa: BLE001 — 清残留失败不该拦住启动
            logger.warning("清理二波状态键 %s 失败：%s", key, exc)
    return cleared


def retire_second_wave(store: Any) -> dict[str, Any]:
    """幂等退役：任务、技能包、状态键、别的池子里的二波候选一并清掉。"""
    removed_jobs = _remove_jobs(store)
    removed_skill = _remove_skill()
    cleared = _clear_settings(store)
    dropped = 0
    try:
        from src.ops.application.unified_monitor_pool import (
            DRAGON_SLUG,
            drop_candidate_feed,
        )

        dropped = drop_candidate_feed(store, slug=DRAGON_SLUG, feed=RETIRED_FEED)
    except Exception as exc:  # noqa: BLE001 — 候选清理失败不该拦住启动
        logger.warning("清理二波候选失败：%s", exc)
    return {
        "slug": RETIRED_SLUG,
        "removed_jobs": removed_jobs,
        "removed_skill": removed_skill,
        "cleared_settings": cleared,
        "dropped_candidates": dropped,
    }


__all__ = [
    "RETIRED_FEED",
    "RETIRED_JOB_NAME",
    "RETIRED_SETTING_KEYS",
    "RETIRED_SLUG",
    "retire_second_wave",
]
