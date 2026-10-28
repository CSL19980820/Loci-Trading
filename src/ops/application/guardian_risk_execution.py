"""风险执行轮的决策和回执；不访问模型、候选池或交易接口。"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_risk import consume_risk_plans, evaluate_risk_plans, resize_remaining_stops

# 旧引用兼容，风险合同方法随通用操作手册维护。
from src.ops.application.trading_operations_skill import load_trading_operations_skill

RISK_RULES = load_trading_operations_skill()[0]



def risk_decision(orders: list[dict[str, Any]], events: list[dict[str, Any]]) -> GuardianDecision | None:
    if not orders:
        return None
    return GuardianDecision.model_validate({"summary": "执行已确认并触发的持仓风险合同。", "orders": orders})


def risk_rejections(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    codes = {"quote_unavailable": "risk_quote_unavailable"}
    return [{"code": event["code"], "quantity": event.get("quantity") or 0,
             "action": event.get("action"), "plan_id": event.get("plan_id"),
             "reason": "持仓风险监测缺少有效报价：" + event.get("reason", "行情不可用"),
             "reject_code": codes[event["status"]]}
            for event in events if event.get("status") in codes]


def reauthorize_risk_events(
    events: list[dict[str, Any]], decision: GuardianDecision,
) -> list[dict[str, Any]]:
    """关联已校验的本轮模型新授权，保留原合同与首次触发证据。"""
    updated = copy.deepcopy(events)
    orders = {(order.code, order.action): order.model_dump(mode="json")
              for order in decision.orders
              if order.action in {"stop_loss", "take_profit"} and order.quantity > 0}
    for event in updated:
        if event.get("status") != "triggered":
            continue
        original = event.get("order") or {}
        order = orders.get((original.get("code"), original.get("action")))
        if order is None:
            event.update(status="withdrawn", reason="模型重新研判后撤回本轮风险执行，原合同保留")
        elif any(order.get(key) != original.get(key) for key in ("quantity", "reason", "execution")):
            event.setdefault("original_order", copy.deepcopy(original))
            event.update(order=order, reauthorized=True)
    return updated


def finish_risk_execution(
    state: dict[str, Any], events: list[dict[str, Any]], fills: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]], now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # 保留初始事件供提交失败路径使用，不把未落账成交报告为已执行。
    saved_events = copy.deepcopy(events)
    consume_risk_plans(state, saved_events, fills)
    saved_events.extend(resize_remaining_stops(state, fills, now))
    updated, _, endings = evaluate_risk_plans(state, quotes, now)
    # 只保存最终时点的失效变化；新触发须到下一轮完整经过二次取价。
    saved_events.extend(event for event in endings if event["status"] in ("expired", "invalidated"))
    return updated, saved_events
