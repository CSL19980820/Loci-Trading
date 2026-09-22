"""独立守护现金账户：金额以分记账，股数为整数，成本含买入费用。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

INITIAL_CENTS = 20_000_000
FEE_POLICY = {"commission_rate": "0.00025", "minimum_commission_cents": 0,
              "stamp_tax_sell_rate": "0.0005", "transfer_rate": "0.00001"}


def rounded(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_guardian_account() -> dict[str, Any]:
    return {"account_version": 2, "initial_capital_cents": INITIAL_CENTS,
            "cash_cents": INITIAL_CENTS, "realized_pnl_cents": 0, "fees_cents": 0,
            "positions": [], "fee_policy": dict(FEE_POLICY), "equity_cents": INITIAL_CENTS,
            "market_value_cents": 0, "unrealized_pnl_cents": 0, "total_pnl_cents": 0,
            "stale_codes": []}


def check_guardian_account(state: dict[str, Any]) -> None:
    if state.get("account_version") != 2:
        raise ValueError("守护账户版本不匹配")
    codes = set()
    for p in state["positions"]:
        if (p["code"] in codes or type(p["quantity"]) is not int or p["quantity"] <= 0
                or type(p["cost_cents"]) is not int or p["cost_cents"] < 0
                or not 0 <= p.get("today_bought", 0) <= p["quantity"]):
            raise ValueError("守护持仓股数或成本不合法")
        codes.add(p["code"])
    for key in ("initial_capital_cents", "cash_cents", "realized_pnl_cents", "fees_cents"):
        if type(state[key]) is not int:
            raise ValueError("守护金额必须以整数分记账")
    if state["cash_cents"] < 0 or state["fees_cents"] < 0:
        raise ValueError("守护现金或费用不能为负")
    if state["cash_cents"] + sum(p["cost_cents"] for p in state["positions"]) != (
        state["initial_capital_cents"] + state["realized_pnl_cents"]
    ):
        raise ValueError("守护账户对账不平：现金+持仓成本不等于本金+已实现盈亏")


def available_quantity(position: dict[str, Any], day: str) -> int:
    locked = position.get("today_bought", 0) if position.get("bought_on") == day else 0
    return position["quantity"] - locked


def guardian_position_policy(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    """持仓描述；股票只数与仓位由模型自主决定，上限为空表示不设限。"""
    locked = [p["code"] for p in state.get("positions", [])
              if available_quantity(p, now.date().isoformat()) < p["quantity"]]
    return {"position_count": len(state.get("positions", [])),
            "locked_codes": locked, "locked_count": len(locked)}


def guardian_quantity_error(code: str, quantity: int, selling: bool, available: int) -> str:
    if type(quantity) is not int or quantity <= 0:
        return "买卖股数必须为正整数"
    star = code.startswith(("688", "689"))
    beijing = code.startswith(("43", "83", "87", "88", "92"))
    if not code.startswith(("600", "601", "603", "605", "688", "689", "000", "001", "002", "003", "30", "43", "83", "87", "88", "92")):
        return "仅支持沪深北 A 股股票"
    minimum = 200 if star else 100
    if selling and quantity > available:
        return f"可卖不足（T+1）：可卖 {available} 股，申报 {quantity} 股"
    if quantity < minimum:
        if selling and not star and not beijing and quantity == available % 100:
            return ""  # 已有零股可单独一次性卖出，例如150股中的50股。
        if not selling or quantity != available:
            return f"不足 {minimum} 股的余额须一次性卖出"
    elif not star and not beijing:
        if not selling and quantity % 100:
            return "普通 A 股买入须为 100 股的整数倍"
        if selling and quantity % 100 not in (0, available % 100):
            if available % 100 == 0:
                return f"普通 A 股卖出须为 100 股的整数倍；当前可卖 {available} 股，可自主选择合法分批股数"
            return "零股余额须一次性卖出，不能拆分"
    return ""


def settle_guardian_order(state: dict[str, Any], order: dict[str, Any], quote: dict[str, Any],
                          now: datetime, reference: dict[str, Any], *, guardian_policy: bool = True) -> dict[str, Any]:
    """调用方先检查新鲜度；校验完成前不写 state，拒单不会留下半笔账。"""
    code, action, quantity = order["code"], order["action"], order["quantity"]
    if action not in ("buy", "add", "sell", "reduce", "take_profit", "stop_loss"):
        raise ValueError("不是可记账的交易动作")
    selling = action in ("sell", "reduce", "take_profit", "stop_loss")
    before = next((p for p in state["positions"] if p["code"] == code), None)
    if action == "add" and before is None:
        raise ValueError("没有持仓，首次建仓请使用买入")
    day = now.date().isoformat()
    available = available_quantity(before, day) if before else 0
    error = guardian_quantity_error(code, quantity, selling, available)
    if error:
        raise ValueError(error)
    price_cents = rounded(Decimal(str(quote.get("price", quote.get("current_price")))) * 100)
    if price_cents <= 0:
        raise ValueError("缺少有效成交价格")
    gross = price_cents * quantity
    policy = state["fee_policy"]
    commission = max(policy["minimum_commission_cents"], rounded(Decimal(gross) * Decimal(policy["commission_rate"])))
    transfer = rounded(Decimal(gross) * Decimal(policy["transfer_rate"]))
    stamp = rounded(Decimal(gross) * Decimal(policy["stamp_tax_sell_rate"])) if selling else 0
    fees = commission + transfer + stamp
    if not selling and gross + fees > state["cash_cents"]:
        raise ValueError(f"现金不足：需 {(gross + fees)/100:.2f} 元，可用 {state['cash_cents']/100:.2f} 元")
    before_quantity = before["quantity"] if before else 0
    if before and before.get("bought_on") != day:
        before["today_bought"] = 0
    allocated_cost = 0
    realized = 0
    if selling:
        allocated_cost = rounded(Decimal(before["cost_cents"]) * quantity / before_quantity)
        realized = gross - fees - allocated_cost
        before["quantity"] -= quantity
        before["cost_cents"] -= allocated_cost
        state["cash_cents"] += gross - fees
        state["realized_pnl_cents"] += realized
        if not before["quantity"]:
            state["positions"].remove(before)
    else:
        state["cash_cents"] -= gross + fees
        if before is None:
            before = {"code": code, "name": quote.get("name") or reference.get("name") or code,
                      "quantity": 0, "cost_cents": 0, "today_bought": 0,
                      "strategies": reference.get("strategies", []),
                      "entry_context": {"reason": order["reason"], "opened_at": now.isoformat()}}
            state["positions"].append(before)
        if before.get("bought_on") != day:
            before["today_bought"] = 0
        before["bought_on"] = day
        before["today_bought"] += quantity
        before["quantity"] += quantity
        before["cost_cents"] += gross + fees
    if before and before["quantity"]:
        before["holding_plan"] = order.get("holding_plan") or before.get("holding_plan", "")
        for key in ("take_profit_plan", "stop_loss_plan"):
            if order.get(key):
                before[key] = order[key]
        if order.get("exit_today_plan"):
            before["exit_today_plan"] = order["exit_today_plan"]
            before["exit_plan_date"] = day
        before["last_review"] = {"action": action, "reason": order["reason"], "at": now.isoformat()}
        before["mark_price_cents"] = price_cents
        before["mark_at"] = f"{quote.get('trade_date', day)} {quote.get('trade_time', '')}"
        before["mark_source"] = quote.get("source", "")
    state["fees_cents"] += fees
    check_guardian_account(state)
    return {**order, "name": (before or {}).get("name", code), "occurred_at": now.isoformat(),
            "side": "sell" if selling else "buy", "price_cents": price_cents,
            "gross_cents": gross, "commission_cents": commission, "transfer_cents": transfer,
            "stamp_tax_cents": stamp, "fees_cents": fees, "allocated_cost_cents": allocated_cost,
            "realized_pnl_cents": realized, "cash_after_cents": state["cash_cents"],
            "before_quantity": before_quantity, "after_quantity": before_quantity + (-quantity if selling else quantity),
            "quote_source": quote.get("source", ""),
            "quote_at": f"{quote.get('trade_date', '')} {quote.get('trade_time', '')}",
            "fee_policy": dict(policy)}


def mark_guardian_account(state: dict[str, Any], quotes: dict[str, dict[str, Any]],
                          now: datetime) -> dict[str, Any]:
    """估值按最后有效参考价；缺报价保留旧价并显式标注，绝不把未知价格当零。"""
    from copy import deepcopy
    result = deepcopy(state)
    official_close = result.get("valuation_kind") == "official_close" and result.get("valuation_date") == now.date().isoformat() and now.hour >= 15
    if quotes:
        result["valuation_kind"] = "live"
        result.pop("valuation_date", None)
        result.pop("closing_sources", None)
    market_value = 0
    missing = []
    for p in result["positions"]:
        q = quotes.get(p["code"]) or {}
        if q:
            p["mark_price_cents"] = rounded(Decimal(str(q.get("price", q.get("current_price")))) * 100)
            p["mark_at"] = f"{q.get('trade_date', '')} {q.get('trade_time', '')}"
            p["mark_source"] = q.get("source", "")
        try:
            timestamp = datetime.fromisoformat(p.get("mark_at", ""))
            timestamp = timestamp.replace(tzinfo=timestamp.tzinfo or now.tzinfo)
            stale = not 0 <= (now - timestamp).total_seconds() <= 180
        except ValueError:
            stale = True
        if official_close and not quotes:
            stale = False
        p["valuation_stale"] = stale
        if stale:
            missing.append(p["code"])
        mark = p.get("mark_price_cents")
        if mark is None:
            raise ValueError("持仓缺少估值价格，不能生成资产汇总")
        p["available_quantity"] = available_quantity(p, now.date().isoformat())
        p["market_value_cents"] = mark * p["quantity"]
        p["unrealized_pnl_cents"] = p["market_value_cents"] - p["cost_cents"]
        p["average_cost"] = float(Decimal(p["cost_cents"]) / 100 / p["quantity"])
        market_value += p["market_value_cents"]
    equity = result["cash_cents"] + market_value
    result.update(market_value_cents=market_value, equity_cents=equity,
                  unrealized_pnl_cents=market_value - sum(p["cost_cents"] for p in result["positions"]),
                  total_pnl_cents=equity - result["initial_capital_cents"],
                  valuation_at=now.isoformat(), stale_codes=missing)
    check_guardian_account(result)
    return result
