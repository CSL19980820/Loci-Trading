"""Keep blocked intents distinct from voluntary waiting."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.ops.application.guardian_decision import GuardianDecision, TRADE_ACTIONS
from src.ops.application.session_clock import session_clock


def execution_window(start: datetime, current: datetime, elapsed: float) -> bool:
    return (session_clock(start).phase == "regular"
            and session_clock(current).phase == "regular"
            and 0 <= (current - start).total_seconds() < 300
            and 0 <= elapsed < 300)


def withdrawn_orders(original: GuardianDecision, corrected: GuardianDecision,
                     rejects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = {(o.code, o.action) for o in corrected.orders if o.action in TRADE_ACTIONS and o.quantity > 0}
    reasons = {(r.get("code"), r.get("action")): r["reason"] for r in rejects}
    return [{**o.model_dump(mode="json"), "reject_code": "withdrawn",
             "reason": "预检修正后撤回，未成交：" + reasons.get((o.code, o.action), "模型撤回原交易意图")}
            for o in original.orders if o.action in TRADE_ACTIONS and o.quantity > 0
            and (o.code, o.action) not in remaining]


def missed_orders(deferred: list[dict[str, Any]], start: datetime) -> list[dict[str, Any]]:
    if session_clock(start).phase != "regular":
        return []
    return [{**order, "reject_code": "execution_window",
             "reason": "研判或核价后已超过成交窗口，本轮未成交；下一轮须重新核验"}
            for order in deferred]
