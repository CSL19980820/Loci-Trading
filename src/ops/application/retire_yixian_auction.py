"""“一线定乾坤·首板次日”退役清理。

这个策略曾作为可编辑 Screen Skill 安装到租户目录，并由启动自愈自动绑定
``screen:yixian-auction``。只删任务或只关推送都不够：包仍在时，下一次启动会把
任务重新确保回来。退役因此同时清理任务、任务回执、技能包、技能版本历史、纸面舱
及候选历史，并在目录层拒绝再次载入。
"""
from __future__ import annotations

import logging
from pathlib import Path
import shutil
from typing import Any

from src.ops.application.retired_slugs import (
    RETIRED_STRATEGY_SLUGS,
    canonical_strategy_slug,
    is_retired_strategy_slug,
)


RETIRED_SLUG = "yixian-auction"
RETIRED_JOB_NAMES = frozenset(
    {
        "screen:yixian-auction",
        "一线定乾坤·首板次日",
        "选股·一线定乾坤·首板次日",
    }
)

logger = logging.getLogger(__name__)


def _job_references_slug(job: dict[str, Any]) -> bool:
    name = str(job.get("name") or "").strip()
    if name in RETIRED_JOB_NAMES:
        return True
    config = job.get("config") if isinstance(job.get("config"), dict) else {}
    for key in ("strategy", "strategy_slug", "skill", "skill_slug", "slug", "rule_version"):
        if is_retired_strategy_slug(config.get(key)):
            return True
    return False


def _remove_jobs(store: Any) -> list[str]:
    removed: list[str] = []
    for job in store.list_jobs() or []:
        if not _job_references_slug(job):
            continue
        name = str(job.get("name") or RETIRED_SLUG)
        if store.delete_job(str(job.get("id") or "")):
            removed.append(name)
    return removed


def _remove_job_run_history(store: Any) -> int:
    """删除该策略的终态任务回执，保留仍在运行的记录以免破坏执行器。"""
    retired_job_ids = {
        str(job.get("id") or "")
        for job in (store.list_jobs() or [])
        if _job_references_slug(job)
    }
    try:
        rows = store.conn.execute(
            "SELECT id, job_id, job_name FROM job_runs WHERE status <> 'running'",
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — 旧库没有 job_runs 时仍可继续退役
        logger.warning("读取一线定乾坤任务回执失败：%s", exc)
        return 0
    ids = [
        str(row[0])
        for row in rows
        if (str(row[1] or "") in retired_job_ids or str(row[2] or "") in RETIRED_JOB_NAMES)
        and str(row[0] or "").strip()
    ]
    if not ids:
        return 0
    try:
        return int(store.delete_runs(ids))
    except Exception as exc:  # noqa: BLE001 — 运行中的并发状态不能阻断其余清理
        logger.warning("清理一线定乾坤任务回执失败：%s", exc)
        return 0


def _remove_skill() -> dict[str, bool]:
    try:
        from src.ops.application.skills import SkillError, uninstall_skill
        from src.shared.paths import skill_root
    except ImportError:
        return {"package": False, "history": False}

    root = Path(skill_root())
    removed_package = False
    try:
        removed_package = bool(uninstall_skill(RETIRED_SLUG))
    except SkillError as exc:
        logger.warning("卸载一线定乾坤技能包失败：%s", exc)

    history = root.parent / "skill-history" / RETIRED_SLUG
    removed_history = False
    if history.exists():
        try:
            shutil.rmtree(history)
            removed_history = not history.exists()
        except OSError as exc:
            logger.warning("清理一线定乾坤技能版本历史失败：%s", exc)
    return {"package": removed_package, "history": removed_history}


def _remove_candidate_history() -> int:
    try:
        from src.ledger import PalaceStore
        from src.shared.paths import palace_db
    except ImportError:
        return 0
    try:
        with PalaceStore(palace_db()) as palace:
            return int(palace.delete_candidates_for_strategy(RETIRED_SLUG))
    except Exception as exc:  # noqa: BLE001 —候选库失败不应阻断任务/技能退役
        logger.warning("清理一线定乾坤选股历史失败：%s", exc)
        return 0


def _refresh_catalog() -> None:
    try:
        from src.strategy.application.screen_skills import refresh_screen_strategy_catalog

        refresh_screen_strategy_catalog()
    except Exception as exc:  # noqa: BLE001 — 目录刷新失败由下一次访问自愈
        logger.warning("刷新退役后的 Screen Skill 目录失败：%s", exc)


def retire_yixian_auction(store: Any) -> dict[str, Any]:
    """幂等清除一线定乾坤的所有活动绑定与策略专属历史。"""
    removed_runs = _remove_job_run_history(store)
    removed_jobs = _remove_jobs(store)
    removed_skill = _remove_skill()
    removed_cabin = False
    try:
        removed_cabin = bool(store.delete_paper_cabin(RETIRED_SLUG))
    except Exception as exc:  # noqa: BLE001 — 旧库缺纸面表时仍继续清候选
        logger.warning("删除一线定乾坤纸面舱失败：%s", exc)
    removed_candidates = _remove_candidate_history()
    _refresh_catalog()
    return {
        "slug": RETIRED_SLUG,
        "removed_jobs": removed_jobs,
        "removed_job_runs": removed_runs,
        "removed_skill": removed_skill.get("package", False),
        "removed_skill_history": removed_skill.get("history", False),
        "removed_cabin": removed_cabin,
        "removed_candidates": removed_candidates,
        "retired_slugs": sorted(RETIRED_STRATEGY_SLUGS),
        "canonical_slug": canonical_strategy_slug(RETIRED_SLUG),
    }


__all__ = ["RETIRED_JOB_NAMES", "RETIRED_SLUG", "retire_yixian_auction"]
