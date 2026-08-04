"""全局助手账本工具的批量写入辅助。"""
from __future__ import annotations

from typing import Any


def commit_qianlong_candidates(
    *,
    palace_db: str | None,
    rows: list[dict[str, Any]],
    day: str,
    pool_id: str,
    idempotency_key: str,
) -> list[str]:
    """把整池裁决作为同一账本事务提交。"""
    candidates: list[dict[str, Any]] = []
    for row in rows:
        evidence = dict(row.get("evidence") or {})
        evidence.update(
            {
                "source": "ai_assistant",
                "invalidation": str(row.get("invalidation") or ""),
                "idempotency_key": idempotency_key,
            }
        )
        candidates.append(
            {
                "code": row["code"], "name": str(row.get("name") or ""),
                "decision": row["decision"], "reason": row["reason"],
                "occurred_on": day, "pool_id": pool_id, "score": row.get("score"),
                "timing": str(row.get("timing") or ""), "rule_version": "潜龙",
                "evidence": evidence,
                "tier": {"精选": "selected", "观察": "watch", "落选": "reject"}[row["decision"]],
                "source": "ai_assistant",
            }
        )
    from src.ledger import PalaceStore

    with PalaceStore(palace_db) as store:
        return store.record_candidates(candidates)
