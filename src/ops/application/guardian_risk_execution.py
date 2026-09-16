"""风险执行轮的决策和回执；不访问模型、候选池或交易接口。"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_risk import consume_risk_plans, evaluate_risk_plans

RISK_RULES = """【持仓风险合同】
hold或买卖动作可附risk_plans，最多16项，按该动作实际完成后的持仓安装。
null或省略表示保留原合同，[]明确撤回全部；watch/unwatch不能使用此字段。
每项必须给action=stop_loss或take_profit、quantity整数股数、trigger_price、reason和execution。
止损在新鲜报价<=trigger_price、止盈在>=trigger_price时触发；每股每轮最多一笔，止损优先。
execution含kind、带时区的valid_until及limit的min_price/max_price；明确授权未来风险触发的有效期，
该风险有效期可以跨轮次，不受本轮execution_deadline限制；本轮直接买卖仍受本轮期限限制。
首次触发严格使用trigger_price，不提前触发。触发价不等于成交价；触发后的最终成交允许固定授权基准2%波动，不反复扩宽，仍检查有效期、股数、T+1和交易窗口。
合同绑定实际持仓数量和开仓批次；基准变化须重新确认，重复合同不会重置基准或重新激活已消费合同。
只有实际成交才消费合同，缺价、T+1或价格回弹拒单后仍可在有效期内重试。
holding_plan/take_profit_plan/stop_loss_plan等旧自然语言仅供研究，不自动解释为挂单或风险合同。
"""


def risk_decision(orders: list[dict[str, Any]], events: list[dict[str, Any]]) -> GuardianDecision | None:
    if not events or (not orders and all(event.get("status") == "quote_unavailable" for event in events)):
        return None
    summary = "执行已确认的持仓风险合同。" if orders else "持仓风险合同受阻或已失效，详见风险回执。"
    return GuardianDecision.model_validate({"summary": summary, "orders": orders})


def risk_rejections(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    codes = {"quote_unavailable": "risk_quote_unavailable", "expired": "risk_expired",
             "invalidated": "risk_invalidated"}
    return [{"code": event["code"], "quantity": event.get("quantity") or 0,
             "action": event.get("action"), "plan_id": event.get("plan_id"),
             "reason": "持仓风险合同未执行：" + event.get("reason", "风险合同无效"),
             "reject_code": codes[event["status"]]}
            for event in events if event.get("status") in codes]


def finish_risk_execution(
    state: dict[str, Any], events: list[dict[str, Any]], fills: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]], now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # 保留初始事件供提交失败路径使用，不把未落账成交报告为已执行。
    saved_events = copy.deepcopy(events)
    consume_risk_plans(state, saved_events, fills)
    updated, _, endings = evaluate_risk_plans(state, quotes, now)
    # 只保存最终时点的失效变化；新触发须到下一轮完整经过二次取价。
    saved_events.extend(event for event in endings if event["status"] in ("expired", "invalidated"))
    return updated, saved_events
