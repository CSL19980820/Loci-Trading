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


BUY_ACTIONS = frozenset({"buy", "add"})
LIMIT_REJECT = "agent_limit"
WATCH_ORDERS = "watch_orders"


def _grew_past(limit: int, before: int, after: int) -> bool:
    """数量约束只拦“本轮使其越限并继续变大”的动作。

    用户下调上限后账户可能已经越限；此时卖出、撤观察等收敛动作必须照常执行，
    否则每一轮都会整轮失败，连止损都做不了。
    """
    return bool(limit) and after > limit and after > before


def _reject(order: GuardianOrder, reason: str, code: str = LIMIT_REJECT) -> dict:
    return {**order.model_dump(mode="json"), "reason": reason, "reject_code": code}


def _chooses(order: GuardianOrder, held: set[str]) -> bool:
    return order.action in {"watch", "buy", "add"} and order.code not in held


def simulate_stock_agent(state: dict[str, Any], decision: GuardianDecision, quotes: dict,
                         now: datetime, config: dict, *, analysis_only: bool = False,
                         phase: str | None = None) -> tuple[dict, list, list]:
    """逐笔预检：越过数量或组合约束的意图单独拒绝并写明原因，其余意图照常撮合。

    原先任一约束（入选/观察/临时持仓上限、锁仓数、留仓名单、单股仓位）都会抛错让整轮失败，
    同篮的止损、减仓卖单也一起作废。现在：逐笔约束只拒绝使数量越限的那一笔；依赖成交结果的
    组合约束先撤回相关买入（单股仓位只撤该股，其余撤回本轮全部买入/加仓，不由程序挑选赢家）
    后重算。日内已入选集合仍不可由取消观察绕过。
    """
    current = copy.deepcopy(state)
    is_leader = config.get("kind") == "leader"
    if is_leader:
        current["watchlist"] = pending_watchlist(current)
    day = now.date().isoformat()
    selected = current.get("selected_today", {})
    chosen_before = set(selected.get("codes", [])) if selected.get("date") == day else set()
    chosen = set(chosen_before)
    watched = {item["code"] for item in current.get("watchlist", [])}
    positions = {item["code"]: item["quantity"] for item in current["positions"]}
    held = set(positions)
    errors: list[dict] = []
    accepted = []
    for order in decision.orders:
        scope_problem = ""
        if leader_watch_only(config, phase) and order.action == "watch" and order.code not in watched:
            scope_problem = "龙头选手盘中不得新增或替换观察股；原观察股不合适就放弃，不临时另选"
        if config.get("kind") == "leader" and order.action in BUY_ACTIONS:
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
            errors.append(_reject(order, scope_problem, "leader_watch_scope"))
            continue
        if order.action in TRADE_ACTIONS and (analysis_only or session_clock(now).phase != "regular"):
            errors.append({"code": order.code, "action": order.action, "reason": "本时段只研究和观察，不执行模拟成交；开市后重新核价研判"})
            continue
        book = quotes.get(order.code, {}).get("order_book")
        if order.action in TRADE_ACTIONS and isinstance(book, dict):
            side = "ask" if order.action in BUY_ACTIONS else "bid"
            try:
                no_depth = float(book.get(side + "_price") or 0) <= 0 or float(book.get(side + "_quantity") or 0) <= 0
            except (TypeError, ValueError):
                no_depth = True
            if no_depth:
                errors.append(_reject(order, "当前报价没有可成交的对手盘，不按最新价虚构模拟成交", "missing_executable_depth"))
                continue
        next_chosen, next_watched, next_positions = set(chosen), set(watched), dict(positions)
        if _chooses(order, held):
            next_chosen.add(order.code)
        if order.action == "watch":
            next_watched.add(order.code)
        elif order.action == "unwatch":
            next_watched.discard(order.code)
        elif order.action in BUY_ACTIONS:
            next_positions[order.code] = next_positions.get(order.code, 0) + order.quantity
        elif order.action in {"sell", "reduce", "take_profit", "stop_loss"}:
            next_positions[order.code] = max(0, next_positions.get(order.code, 0) - order.quantity)
            if not next_positions[order.code]:
                next_positions.pop(order.code)
        if _grew_past(config["daily_selection_limit"], len(chosen), len(next_chosen)):
            errors.append(_reject(order, "超过每日累计入选上限；取消观察不会重置当天名额"))
            continue
        if not is_leader and _grew_past(config["watch_limit"], len(watched), len(next_watched)):
            errors.append(_reject(order, "超过当前观察上限；先撤出观察再新增"))
            continue
        if _grew_past(config["temporary_position_limit"], len(positions), len(next_positions)):
            errors.append(_reject(order, "超过临时持仓上限，先减仓再换股"))
            continue
        chosen, watched, positions = next_chosen, next_watched, next_positions
        accepted.append(order)

    normal = config["position_limit"]
    close_time = now.strftime("%H:%M") >= "14:50"
    locked_before = {p["code"] for p in current["positions"] if guardian_available_quantity(p, day) < p["quantity"]}

    def settle(orders: list[GuardianOrder]) -> tuple[dict, list, list, str, Any]:
        """按给定意图撮合并检查组合约束。

        返回 (账户, 成交, 拒单, 问题, 撤回范围)：撤回范围为 ``WATCH_ORDERS`` 表示本轮新增观察，
        股票集合表示这些股票的买入，``None`` 表示本轮全部买入/加仓。
        """
        filtered = decision.model_copy(update={"orders": orders})
        projected, fills, rejected = simulate(current, filtered, [], quotes, now,
                                              require_execution_terms=True, guardian_policy=False)
        buying = [o for o in orders if o.action in BUY_ACTIONS]
        if is_leader:
            # 先按真实成交剔除持仓，再校验整轮最终名单；盘后/盘前换股不受动作排列影响。
            projected["watchlist"] = pending_watchlist(projected)
            if _grew_past(config["watch_limit"], len(current["watchlist"]), len(projected["watchlist"])):
                return projected, fills, rejected, "超过当前非持仓观察上限；持仓不占观察名额，调整后名单需在上限内", WATCH_ORDERS
        locked = {p["code"] for p in projected["positions"] if guardian_available_quantity(p, day) < p["quantity"]}
        if normal and len(locked) > normal and len(locked) > len(locked_before):
            return projected, fills, rejected, "当日新买锁仓数量超过常态上限，T+1下无法按时收敛", None
        actual = {p["code"] for p in projected["positions"]}
        if normal and len(actual) > normal:
            chosen_keep = decision.close_keep_codes
            if chosen_keep is None and current.get("agent_close_keep_codes"):
                chosen_keep = current["agent_close_keep_codes"]  # []只表示此前未超配，不是“收盘全部清仓”
            keep = set(chosen_keep or [])
            if chosen_keep is not None and len(keep) <= normal and keep <= actual and locked <= keep:
                projected["agent_close_keep_codes"] = sorted(keep)
                projected["agent_close_plan_date"] = day
            elif buying:
                return projected, fills, rejected, "临时超配必须指定不超过常态上限的收盘留仓名单，并覆盖全部T+1锁仓", None
            else:
                # 未新增买入的既有超配（如下调常态上限）：不阻断卖出，也不留自动清仓名单，交模型逐轮决定。
                projected["agent_close_keep_codes"] = []
                projected.pop("agent_close_plan_date", None)
            if close_time and buying:
                return projected, fills, rejected, "14:50后禁止新增临时超配，只允许收敛持仓", None
        else:
            projected["agent_close_keep_codes"] = []
            projected.pop("agent_close_plan_date", None)
        bought = {fill["code"] for fill in fills if fill.get("action") in BUY_ACTIONS or fill.get("side") == "buy"}
        bought |= {order.code for order in buying}
        heavy = {p["code"] for p in projected["positions"]
                 if p["code"] in bought and p["market_value_cents"] * 100 > projected["equity_cents"] * config["max_position_pct"]}
        if heavy:
            return projected, fills, rejected, "买入后单股仓位超过智能体配置上限", heavy
        return projected, fills, rejected, "", None

    while True:  # 每轮至少撤回一笔意图，必然收敛
        projected, fills, rejected, problem, offenders = settle(accepted)
        if not problem:
            break
        if offenders == WATCH_ORDERS:
            withdraw = [o for o in accepted if o.action == "watch"]
        else:
            withdraw = [o for o in accepted if o.action in BUY_ACTIONS and (offenders is None or o.code in offenders)]
        if not withdraw:
            raise ValueError(problem)
        errors.extend(_reject(o, problem + "；本笔已撤回，其余意图照常预检") for o in withdraw)
        withdrawn_ids = {id(o) for o in withdraw}
        accepted = [o for o in accepted if id(o) not in withdrawn_ids]
    if config.get("kind") == "leader" and phase == "premarket" and analysis_only and now.strftime("%H:%M") < "09:25":
        projected["leader_watch_date"] = day
    elif config.get("kind") == "leader" and phase == "review":
        projected.pop("leader_watch_date", None)  # 复盘候选不能冒充次日已经确认的盘前池。
    projected["selected_today"] = {"date": day, "codes": sorted(
        chosen_before | {o.code for o in accepted if _chooses(o, held)})}
    return projected, fills, [*errors, *rejected]


def closing_stock_agent_decision(state: dict, now: datetime, config: dict) -> GuardianDecision | None:
    """只执行此前确认的收盘名单，程序不自行挑选赢家或替换股票。

    名单缺失、失效（未覆盖T+1锁仓）或只是“此前未超配”的空列表时返回None，交由模型本轮研判，
    而不是每轮抛错或把全部持仓当作名单外清掉（下调常态上限后曾出现这两种情况）。
    """
    if not config["position_limit"] or now.strftime("%H:%M") < "14:50" or len(state["positions"]) <= config["position_limit"]:
        return None
    day = now.date().isoformat()
    keep = state.get("agent_close_keep_codes")
    if keep is None or (not keep and state.get("agent_close_plan_date") != day):
        return None
    held = {p["code"] for p in state["positions"]}
    keep = sorted(set(keep) & held)  # 名单内已卖出的股票不影响其余名单外持仓的收敛
    locked = {p["code"] for p in state["positions"] if guardian_available_quantity(p, day) < p["quantity"]}
    if len(keep) > config["position_limit"] or not locked <= set(keep):
        return None
    return StockAgentDecision(summary="按已保存的留仓名单执行尾盘收敛，不调用模型重新选股。", close_keep_codes=keep,
        orders=[GuardianOrder(code=p["code"], name=p["name"], action="sell", quantity=p["quantity"],
            reason="退出已确认收盘名单之外的临时持仓",
            execution=ExecutionTerms(kind="market", valid_until=(now+timedelta(minutes=3)).isoformat()))
            for p in state["positions"] if p["code"] not in keep])


def empty_mark(state: dict, now: datetime) -> dict:
    return mark_guardian_account(state, {}, now)
