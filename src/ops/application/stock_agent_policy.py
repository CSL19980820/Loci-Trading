"""新智能体独立数量约束；复用撮合费用算法但不改变自主交易员。"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

from src.ledger import guardian_available_quantity, mark_guardian_account
from src.ops.application.guardian_decision import GuardianDecision, TRADE_ACTIONS, simulate
from src.ops.application.guardian_contract import ExecutionTerms
from src.ops.application.guardian_decision import GuardianOrder
from src.ops.application.session_clock import session_clock


def simulate_stock_agent(state: dict[str, Any], decision: GuardianDecision, quotes: dict,
                         now: datetime, config: dict, *, analysis_only: bool = False) -> tuple[dict, list, list]:
    """整篮预检失败则整篮回滚；日内已入选集合不可由取消观察绕过。"""
    current = copy.deepcopy(state)
    day = now.date().isoformat()
    selected = current.get("selected_today", {})
    chosen = set(selected.get("codes", [])) if selected.get("date") == day else set()
    watched = {item["code"] for item in current.get("watchlist", [])}
    positions = {item["code"]: item["quantity"] for item in current["positions"]}
    held = set(positions)
    errors: list[dict] = []
    accepted = []
    if len(decision.orders) > 30:
        raise ValueError("单轮最多30条决策，避免重复或无界操作")
    for order in decision.orders:
        if order.action in TRADE_ACTIONS and (analysis_only or session_clock(now).phase != "regular"):
            errors.append({"code": order.code, "action": order.action, "reason": "本时段只研究和观察，不执行模拟成交；开市后重新核价研判"})
            continue
        if order.action in {"watch", "buy", "add"} and order.code not in held:
            chosen.add(order.code)
        if order.action == "watch":
            watched.add(order.code)
        elif order.action == "unwatch":
            watched.discard(order.code)
        elif order.action in {"buy", "add"}:
            positions[order.code] = positions.get(order.code, 0) + order.quantity
        elif order.action in {"sell", "reduce", "take_profit", "stop_loss"}:
            positions[order.code] = max(0, positions.get(order.code, 0) - order.quantity)
            if not positions[order.code]:
                positions.pop(order.code)
        if len(chosen) > config["daily_selection_limit"] or len(watched) > config["watch_limit"]:
            raise ValueError("超过每日累计入选或当前观察上限；取消观察不会重置当天名额")
        if len(positions) > config["temporary_position_limit"]:
            raise ValueError("超过临时持仓上限，先减仓再换股")
        accepted.append(order)
    filtered = decision.model_copy(update={"orders": accepted})
    projected, fills, rejected = simulate(current, filtered, [], quotes, now, require_execution_terms=True)
    projected["selected_today"] = {"date": day, "codes": sorted(chosen)}
    normal = config["position_limit"]
    close_time = now.strftime("%H:%M") >= "14:50"
    locked = {p["code"] for p in projected["positions"] if guardian_available_quantity(p, day) < p["quantity"]}
    if len(locked) > normal:
        raise ValueError("当日新买锁仓数量超过常态上限，T+1下无法按时收敛")
    if len(projected["positions"]) > normal:
        chosen_keep = decision.close_keep_codes if decision.close_keep_codes is not None else current.get("agent_close_keep_codes")
        keep = set(chosen_keep or [])
        actual = {p["code"] for p in projected["positions"]}
        if chosen_keep is None or len(keep) > normal or not keep <= actual or not locked <= keep:
            raise ValueError("临时超配必须指定不超过常态上限的收盘留仓名单，并覆盖全部T+1锁仓")
        projected["agent_close_keep_codes"] = sorted(keep)
        projected["agent_close_plan_date"] = day
        if close_time and any(o.action in {"buy", "add"} for o in accepted):
            raise ValueError("14:50后禁止新增临时超配，只允许收敛持仓")
    else:
        projected["agent_close_keep_codes"] = []
    bought = {fill["code"] for fill in fills if fill.get("action") in {"buy", "add"} or fill.get("side") == "buy"}
    bought |= {order.code for order in accepted if order.action in {"buy", "add"}}
    for position in projected["positions"]:
        if position["code"] in bought and position["market_value_cents"] * 100 > projected["equity_cents"] * config["max_position_pct"]:
            raise ValueError("买入后单股仓位超过智能体配置上限")
    return projected, fills, [*errors, *rejected]


def closing_stock_agent_decision(state: dict, now: datetime, config: dict) -> GuardianDecision | None:
    """只执行此前确认的收盘名单，程序不自行挑选赢家或替换股票。"""
    if now.strftime("%H:%M") < "14:50" or len(state["positions"]) <= config["position_limit"]:
        return None
    keep = state.get("agent_close_keep_codes")
    held = {p["code"] for p in state["positions"]}
    locked = {p["code"] for p in state["positions"] if guardian_available_quantity(p, now.date().isoformat()) < p["quantity"]}
    if keep is None or len(keep) > config["position_limit"] or not set(keep) <= held or not locked <= set(keep):
        raise ValueError("临时持仓缺少可执行的收盘名单，禁止凭空替换或伪造卖出")
    return GuardianDecision(summary="按已保存的留仓名单执行尾盘收敛，不调用模型重新选股。", close_keep_codes=keep,
        orders=[GuardianOrder(code=p["code"], name=p["name"], action="sell", quantity=p["quantity"],
            reason="退出已确认收盘名单之外的临时持仓",
            execution=ExecutionTerms(kind="market", valid_until=(now+timedelta(minutes=3)).isoformat()))
            for p in state["positions"] if p["code"] not in keep])


def empty_mark(state: dict, now: datetime) -> dict:
    return mark_guardian_account(state, {}, now)
