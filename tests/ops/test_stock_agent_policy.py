from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.ledger import new_guardian_account, settle_guardian_order, check_guardian_account, mark_guardian_account
from src.ops.application.guardian_decision import GuardianDecision, bind_execution_references
from src.ops.application.stock_agent_policy import closing_stock_agent_decision, simulate_stock_agent
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CODES = ["600001", "600002", "600003", "600004", "600005", "600006"]


def config(**values):
    return StockAgentConfig(name="测试龙头", kind="leader", **values).model_dump()


def quotes(codes=CODES, now=NOW, **changes):
    return {code: {"code": code, "name": "测试股票" + code[-1], "price": 10,
                   "trade_date": now.date().isoformat(), "trade_time": now.strftime("%H:%M:%S"), **changes} for code in codes}


def decision(orders, now=NOW, **values):
    prepared = []
    for order in orders:
        order = {"name": "测试股票", "reason": "已核实的测试计划", **order}
        if order["action"] in {"buy", "add", "sell", "reduce", "stop_loss", "take_profit"}:
            order["execution"] = {"kind": "market", "valid_until": (now+timedelta(minutes=3)).isoformat()}
        prepared.append(order)
    return GuardianDecision.model_validate({"summary": "测试研究结果", "orders": prepared, **values})


def account_with_positions(count=3, now=NOW-timedelta(days=1)):
    state = new_guardian_account()
    for code in CODES[:count]:
        settle_guardian_order(state, {"code": code, "name": "测试股票", "action": "buy", "quantity": 100, "reason": "测试建仓"},
                              quotes([code], now)[code], now, {"name": "测试股票"})
    return mark_guardian_account(state, quotes(now=now), now)


def run(state, plan, now=NOW, **values):
    market = quotes(now=now)
    plan = bind_execution_references(plan, market, now)
    return simulate_stock_agent(state, plan, market, now, config(**values))


def test_cumulative_selection_cannot_be_reset_by_unwatch():
    state = new_guardian_account()
    state, _, _ = run(state, decision([{"action": "watch", "code": code} for code in CODES[:3]]))
    state, _, _ = run(state, decision([{"action": "unwatch", "code": CODES[0]}]))
    with pytest.raises(ValueError, match="累计入选"):
        run(state, decision([{"action": "watch", "code": CODES[3]}]))
    tomorrow = NOW+timedelta(days=1)
    state, _, _ = run(state, decision([{"action": "watch", "code": CODES[3]}]), now=tomorrow)
    assert len(state["watchlist"]) == 3
    assert state["selected_today"]["codes"] == [CODES[3]]


def test_auction_never_fills_even_when_decision_asks_to_buy():
    now = NOW.replace(hour=9, minute=25)
    state, fills, rejected = run(new_guardian_account(), decision([{"action": "buy", "code": CODES[0], "quantity": 100}], now), now=now)
    assert not fills and not state["positions"]
    assert rejected and "不执行" in rejected[0]["reason"]


def test_three_new_locked_positions_cannot_become_four():
    state = account_with_positions(3, now=NOW)
    with pytest.raises(ValueError, match="锁仓"):
        run(state, decision([{"action": "buy", "code": CODES[3], "quantity": 100}], close_keep_codes=CODES[1:4]))


def test_temporary_exchange_requires_explicit_feasible_close_plan():
    state = account_with_positions()
    with pytest.raises(ValueError, match="收盘留仓"):
        run(state, decision([{"action": "buy", "code": CODES[3], "quantity": 100}]))
    after, fills, rejected = run(state, decision([{"action": "buy", "code": CODES[3], "quantity": 100}], close_keep_codes=CODES[1:4]))
    assert len(after["positions"]) == 4
    assert len(fills) == 1 and not rejected
    assert after["agent_close_keep_codes"] == CODES[1:4]
    assert state.get("agent_close_keep_codes") is None


def test_closeout_executes_saved_plan_without_llm_or_arbitrary_picks():
    state = account_with_positions()
    state, _, _ = run(state, decision([{"action": "buy", "code": CODES[3], "quantity": 100}], close_keep_codes=CODES[1:4]))
    now = NOW.replace(hour=14, minute=50)
    plan = closing_stock_agent_decision(state, now, config())
    assert plan and [order.code for order in plan.orders] == [CODES[0]]
    after, fills, rejected = run(state, plan, now=now)
    assert len(after["positions"]) == 3 and len(fills) == 1 and not rejected
    check_guardian_account(after)


def test_expired_quote_does_not_create_an_execution():
    now = NOW.replace(hour=14, minute=50)
    state = account_with_positions(4)
    state["agent_close_keep_codes"] = CODES[1:4]
    plan = closing_stock_agent_decision(state, now, config())
    after, fills, rejects = simulate_stock_agent(state, plan, quotes(now=NOW), now, config())
    assert not fills and rejects and len(after["positions"]) == 4


def test_late_session_cannot_increase_temporary_positions():
    now = NOW.replace(hour=14, minute=51)
    with pytest.raises(ValueError, match="14:50"):
        run(account_with_positions(), decision([{"action": "buy", "code": CODES[3], "quantity": 100}], now,
                                              close_keep_codes=CODES[1:4]), now=now)


def test_single_stock_cap_is_enforced_by_code_not_prompt():
    with pytest.raises(ValueError, match="单股仓位"):
        run(new_guardian_account(), decision([{"action": "buy", "code": CODES[0], "quantity": 10000}]))
