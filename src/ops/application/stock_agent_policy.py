"""新智能体独立数量约束；复用撮合费用算法但不改变天才交易员。"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

from src.ledger import guardian_available_quantity, mark_guardian_account
from src.ledger.domain.stock_agent_account import pending_watchlist
from src.ops.application.guardian_decision import GuardianDecision, TRADE_ACTIONS, simulate
from src.ops.application.guardian_contract import ExecutionTerms
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.guardian_decision import GuardianOrder
from src.ops.application.session_clock import session_clock


def leader_watch_only(config: dict, phase: str | None) -> bool:
    return config.get("kind") == "leader" and phase not in {"premarket", "review"}


def leader_holdings_only(config: dict, phase: str | None) -> bool:
    return config.get("kind") == "leader" and phase not in {"premarket", "review", "auction"}


def leader_research_codes(state: dict, config: dict, phase: str | None) -> set[str] | None:
    if not leader_watch_only(config, phase):
        return None
    held = {p["code"] for p in state.get("positions", []) if p.get("quantity", 0) > 0}
    if leader_holdings_only(config, phase):
        return held
    return held | {w["code"] for w in pending_watchlist(state)}


def simulate_stock_agent(state: dict[str, Any], decision: GuardianDecision, quotes: dict,
                         now: datetime, config: dict, *, analysis_only: bool = False,
                         phase: str | None = None) -> tuple[dict, list, list]:
    """整篮预检失败则整篮回滚；日内已入选集合不可由取消观察绕过。"""
    current = copy.deepcopy(state)
    is_leader = config.get("kind") == "leader"
    if is_leader:
        current["watchlist"] = pending_watchlist(current)
    day = now.date().isoformat()
    selected = current.get("selected_today", {})
    chosen = set(selected.get("codes", [])) if selected.get("date") == day else set()
    watched = {item["code"] for item in current.get("watchlist", [])}
    positions = {item["code"]: item["quantity"] for item in current["positions"]}
    held = set(positions)
    errors: list[dict] = []
    accepted = []
    for order in decision.orders:
        scope_problem = ""
        if leader_watch_only(config, phase) and order.action == "watch" and order.code not in watched:
            scope_problem = "龙头选手盘中不得新增或替换观察股；原观察股不合适就放弃，不临时另选"
        if config.get("kind") == "leader" and order.action in {"buy", "add"}:
            if state.get("leader_watch_date") != day:
                scope_problem = "今天尚未确认盘前观察池，本轮不新增买入"
            elif order.code not in watched:
                scope_problem = "不在本轮开始前已确认且未放弃的观察池，龙头选手不得买入或加仓"
        if is_leader and order.action == "watch" and order.code in held:
            scope_problem = "已持仓不进入观察池、不占观察名额；请使用hold更新持仓计划"
        if leader_holdings_only(config, phase) and (
                order.code not in held or order.action in {"watch", "unwatch", "buy", "add"}):
            scope_problem = "龙头选手盘中只管理当前持仓，不查询未持仓观察股、不调整观察池、不新开仓或加仓"
        if scope_problem:
            errors.append({**order.model_dump(mode="json"), "reason": scope_problem, "reject_code": "leader_watch_scope"})
            continue
        if order.action in TRADE_ACTIONS and (analysis_only or session_clock(now).phase != "regular"):
            errors.append({"code": order.code, "action": order.action, "reason": "本时段只研究和观察，不执行模拟成交；开市后重新核价研判"})
            continue
        book = quotes.get(order.code, {}).get("order_book")
        if order.action in TRADE_ACTIONS and isinstance(book, dict):
            side = "ask" if order.action in {"buy", "add"} else "bid"
            try:
                no_depth = float(book.get(side + "_price") or 0) <= 0 or float(book.get(side + "_quantity") or 0) <= 0
            except (TypeError, ValueError):
                no_depth = True
            if no_depth:
                errors.append({**order.model_dump(mode="json"), "reject_code": "missing_executable_depth",
                               "reason": "当前报价没有可成交的对手盘，不按最新价虚构模拟成交"})
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
        if ((config["daily_selection_limit"] and len(chosen) > config["daily_selection_limit"])
                or (not is_leader and config["watch_limit"] and len(watched) > config["watch_limit"])):
            raise ValueError("超过每日累计入选或当前观察上限；取消观察不会重置当天名额")
        if config["temporary_position_limit"] and len(positions) > config["temporary_position_limit"]:
            raise ValueError("超过临时持仓上限，先减仓再换股")
        accepted.append(order)
    filtered = decision.model_copy(update={"orders": accepted})
    projected, fills, rejected = simulate(current, filtered, [], quotes, now,
                                          require_execution_terms=True, guardian_policy=False)
    if is_leader:
        # 先按真实成交剔除持仓，再校验整轮最终名单；盘后/盘前换股不受动作排列影响。
        projected["watchlist"] = pending_watchlist(projected)
        if config["watch_limit"] and len(projected["watchlist"]) > config["watch_limit"]:
            raise ValueError("超过当前非持仓观察上限；持仓不占观察名额，调整后名单需在上限内")
    if config.get("kind") == "leader" and phase == "premarket" and analysis_only and now.strftime("%H:%M") < "09:25":
        projected["leader_watch_date"] = day
    elif config.get("kind") == "leader" and phase == "review":
        projected.pop("leader_watch_date", None)  # 复盘候选不能冒充次日已经确认的盘前池。
    projected["selected_today"] = {"date": day, "codes": sorted(chosen)}
    normal = config["position_limit"]
    close_time = now.strftime("%H:%M") >= "14:50"
    locked = {p["code"] for p in projected["positions"] if guardian_available_quantity(p, day) < p["quantity"]}
    if normal and len(locked) > normal:
        raise ValueError("当日新买锁仓数量超过常态上限，T+1下无法按时收敛")
    if normal and len(projected["positions"]) > normal:
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
    if not config["position_limit"] or now.strftime("%H:%M") < "14:50" or len(state["positions"]) <= config["position_limit"]:
        return None
    keep = state.get("agent_close_keep_codes")
    held = {p["code"] for p in state["positions"]}
    locked = {p["code"] for p in state["positions"] if guardian_available_quantity(p, now.date().isoformat()) < p["quantity"]}
    if keep is None or len(keep) > config["position_limit"] or not set(keep) <= held or not locked <= set(keep):
        raise ValueError("临时持仓缺少可执行的收盘名单，禁止凭空替换或伪造卖出")
    return StockAgentDecision(summary="按已保存的留仓名单执行尾盘收敛，不调用模型重新选股。", close_keep_codes=keep,
        orders=[GuardianOrder(code=p["code"], name=p["name"], action="sell", quantity=p["quantity"],
            reason="退出已确认收盘名单之外的临时持仓",
            execution=ExecutionTerms(kind="market", valid_until=(now+timedelta(minutes=3)).isoformat()))
            for p in state["positions"] if p["code"] not in keep])


def empty_mark(state: dict, now: datetime) -> dict:
    return mark_guardian_account(state, {}, now)
