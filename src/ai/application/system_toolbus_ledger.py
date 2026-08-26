"""全局助手账本工具（候选池 / 预案 / 复盘）。

持仓、成交、现金、账户快照能力已随实盘账本一并下线；这里只剩候选裁决、交易预案
与复盘记录，落在 `candidate_reviews` / `plans` / `reviews` 上。
"""
from __future__ import annotations

from typing import Any

from src.ai.application.system_tool_result import ToolResult, ok as _ok
from src.ai.domain.assistant import AssistantError


def ledger_upsert_candidate(owner: Any, args: dict[str, Any]) -> ToolResult:
    values = {
        "code": str(args["code"]),
        "name": str(args.get("name") or ""),
        "decision": str(args["decision"]),
        "reason": str(args["reason"]),
    }
    for key in ("occurred_on", "pool_id", "timing"):
        if args.get(key) is not None and str(args[key]).strip():
            values[key] = str(args[key]).strip()
    if args.get("score") is not None:
        values["score"] = float(args["score"])
    invalidation = str(args.get("invalidation") or "").strip()
    if invalidation:
        values["evidence"] = {"invalidation": invalidation}
    values["tier"] = {"精选": "selected", "观察": "watch", "落选": "reject"}[values["decision"]]
    grant = owner._grant("ledger.upsert_candidate", values["code"], values)
    from src.ledger import PalaceStore

    with PalaceStore(owner.palace_db) as store:
        candidate_id = store.record_candidate(
            **values,
            rule_version="潜龙" if "潜龙" in values.get("reason", "") else "manual",
            source="ai_assistant",
        )
    owner._artifact("candidate_verdict", "候选裁决", {"candidates": [{**values, "id": candidate_id}]})
    return _ok({"id": candidate_id, **values, "idempotency_key": grant})

def ledger_delete_candidate(owner: Any, args: dict[str, Any]) -> ToolResult:
    candidate_id = str(args["candidate_id"]).strip()
    grant = owner._grant("ledger.delete_candidate", candidate_id, {"candidate_id": candidate_id})
    from src.ledger import PalaceStore

    with PalaceStore(owner.palace_db) as store:
        removed = store.delete_candidate(candidate_id)
    if not removed:
        raise AssistantError("候选不存在")
    return _ok({"candidate_id": candidate_id, "removed": True, "idempotency_key": grant})

def ledger_delete_candidate_pool(owner: Any, args: dict[str, Any]) -> ToolResult:
    values = {"occurred_on": str(args["occurred_on"]), "pool_id": str(args["pool_id"])}
    grant = owner._grant("ledger.delete_candidate_pool", values["pool_id"], values)
    from src.ledger import PalaceStore

    with PalaceStore(owner.palace_db) as store:
        removed = store.delete_candidates_for_pool(**values)
    return _ok({**values, "removed": removed, "idempotency_key": grant})

def ledger_record_plan(owner: Any, args: dict[str, Any]) -> ToolResult:
    values = {key: str(args[key]).strip() for key in ("code", "title", "scenario")}
    for key in ("occurred_on", "entry_zone", "invalidation", "note"):
        if args.get(key) is not None and str(args[key]).strip():
            values[key] = str(args[key]).strip()
    for key in ("stop_price", "target_price", "layers"):
        if args.get(key) is not None:
            values[key] = float(args[key])
    grant = owner._grant("ledger.record_plan", values["code"], values)
    from src.ledger import PalaceStore

    with PalaceStore(owner.palace_db) as store:
        plan_id = store.record_plan(**values, source="ai_assistant")
    return _ok({"id": plan_id, **values, "idempotency_key": grant})

def ledger_record_review(owner: Any, args: dict[str, Any]) -> ToolResult:
    values = {key: str(args[key]).strip() for key in ("entity_type", "entity_id", "outcome")}
    for key in ("reviewed_on", "strategy_tag", "lesson", "next_rule"):
        if args.get(key) is not None and str(args[key]).strip():
            values[key] = str(args[key]).strip()
    for key in ("return_pct", "max_favorable_pct", "max_adverse_pct"):
        if args.get(key) is not None:
            values[key] = float(args[key])
    grant = owner._grant("ledger.record_review", values["entity_id"], values)
    from src.ledger import PalaceStore

    with PalaceStore(owner.palace_db) as store:
        review_id = store.record_review(**values, source="ai_assistant")
    return _ok({"id": review_id, **values, "idempotency_key": grant})


def build_ledger_tool_specs(owner: Any) -> dict[str, Any]:
    """延迟导入，避免与 SystemToolBus 的 ToolSpec 形成循环。"""
    from src.ai.application.system_toolbus import ToolSpec, _object

    write = True
    return {
        "ledger_upsert_candidate": ToolSpec(
            "ledger_upsert_candidate",
            "新增或更新一条候选裁决。",
            _object(
                {
                    "code": {"type": "string", "pattern": r"^\d{6}$"},
                    "name": {"type": "string"},
                    "decision": {"type": "string", "enum": ["精选", "观察", "落选"]},
                    "reason": {"type": "string", "minLength": 1},
                    "occurred_on": {"type": "string"},
                    "pool_id": {"type": "string"},
                    "score": {"type": "number"},
                    "timing": {"type": "string"},
                    "invalidation": {"type": "string"},
                },
                ["code", "decision", "reason"],
            ),
            write,
            lambda args: ledger_upsert_candidate(owner, args),
        ),
        "ledger_delete_candidate": ToolSpec(
            "ledger_delete_candidate",
            "删除一条候选裁决。",
            _object({"candidate_id": {"type": "string", "minLength": 1}}, ["candidate_id"]),
            write,
            lambda args: ledger_delete_candidate(owner, args),
        ),
        "ledger_delete_candidate_pool": ToolSpec(
            "ledger_delete_candidate_pool",
            "删除指定日期和候选池的全部候选。",
            _object(
                {"occurred_on": {"type": "string"}, "pool_id": {"type": "string", "minLength": 1}},
                ["occurred_on", "pool_id"],
            ),
            write,
            lambda args: ledger_delete_candidate_pool(owner, args),
        ),
        "ledger_record_plan": ToolSpec(
            "ledger_record_plan",
            "新增一条交易预案。",
            _object(
                {
                    "code": {"type": "string", "pattern": r"^\d{6}$"},
                    "title": {"type": "string", "minLength": 1},
                    "scenario": {"type": "string", "minLength": 1},
                    "occurred_on": {"type": "string"},
                    "entry_zone": {"type": "string"},
                    "stop_price": {"type": "number"},
                    "target_price": {"type": "number"},
                    "layers": {"type": "number", "exclusiveMinimum": 0},
                    "invalidation": {"type": "string"},
                    "note": {"type": "string"},
                },
                ["code", "title", "scenario"],
            ),
            write,
            lambda args: ledger_record_plan(owner, args),
        ),
        "ledger_record_review": ToolSpec(
            "ledger_record_review",
            "新增一条候选或预案复盘。",
            _object(
                {
                    "entity_type": {"type": "string", "enum": ["candidate", "plan"]},
                    "entity_id": {"type": "string", "minLength": 1},
                    "outcome": {"type": "string", "minLength": 1},
                    "reviewed_on": {"type": "string"},
                    "strategy_tag": {"type": "string"},
                    "return_pct": {"type": "number"},
                    "max_favorable_pct": {"type": "number"},
                    "max_adverse_pct": {"type": "number"},
                    "lesson": {"type": "string"},
                    "next_rule": {"type": "string"},
                },
                ["entity_type", "entity_id", "outcome"],
            ),
            write,
            lambda args: ledger_record_review(owner, args),
        )
    }
