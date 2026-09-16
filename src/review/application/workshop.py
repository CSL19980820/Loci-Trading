"""Join cached historical statistics with the current tenant's workshop directory."""
from collections.abc import Mapping, Sequence
from typing import Any


def enabled_workshop_catalog(
    catalog: Sequence[Mapping[str, Any]], jobs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """当前租户的真实目录与已启用选股/监测任务取交集，孤儿任务不是战法。"""
    active: set[str] = set()
    for job in jobs:
        if not job.get("enabled") or job.get("kind") not in {
            "screen", "skill", "skill_watch", "strategy_monitor",
        }:
            continue
        config = job.get("config") or {}
        slug = config.get("strategy") or config.get("skill") or config.get("slug")
        if isinstance(slug, str) and slug:
            active.add(slug)
    return [dict(item) for item in catalog if item.get("slug") in active
            and item.get("enabled", True) is not False]


def workshop_winrates(
    rows: Sequence[Mapping[str, Any]], catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join after caching: rename/delete/create need no market update or cache expiry.

    Deleted strategies stay in the ledger, not in the current workshop view. New
    strategies have no settled samples, not a 0% success rate.
    """
    by_tag = {row["strategy_tag"]: row for row in rows}
    result = []
    for item in catalog:
        slug = str(item["slug"])
        result.append({
            "total": 0, "wins": 0, "win_rate": None, "avg_return": None,
            "last_reviewed": "", "source": "candidates", "horizons": {},
            "best_horizon": None, "best_sample": None, "worst_sample": None,
            "observing": 0, "sample_all": 0, "primary_horizon": 5,
            "sample_confidence": "low",
            **by_tag.get(slug, {}),
            "strategy_tag": slug,
            "strategy_name": str(item.get("name") or "未命名战法"),
        })
    return result
