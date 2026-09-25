"""个股智能体：单笔越限只拒该笔，卖出/止损照常；下调上限后不自动清仓、不每轮报错。"""
from datetime import datetime

import pytest

from src.ledger.domain.guardian_account import (
    new_guardian_account,
    settle_guardian_order,
)
from src.ledger.infrastructure.stock_agent_store import _exceeds_agent_limits
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.stock_agent_policy import (
    closing_stock_agent_decision,
    simulate_stock_agent,
)
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime.fromisoformat("2026-09-23T10:00:00+08:00")
CLOSE = datetime.fromisoformat("2026-09-23T14:51:00+08:00")
EXECUTION = {"kind": "market", "valid_until": "2026-09-23T15:00:00+08:00"}


def config(**limits):
    return StockAgentConfig(name="测试", **limits).model_dump()


def quote(code, now=NOW, price=10.0):
    stamp = {"trade_date": now.date().isoformat(), "trade_time": now.strftime("%H:%M:%S")}
    book = {"code": code, "source": "tencent", "price": price, **stamp, "limit_up": price * 1.1,
            "limit_down": price * 0.9, "ask_price": price, "ask_quantity": 1_000_000,
            "bid_price": price, "bid_quantity": 1_000_000}
    return {"code": code, "name": code, "price": price, "source": "tencent", **stamp, "order_book": book}


def holding(*codes, quantity=200):
    state = new_guardian_account()
    for code in codes:
        settle_guardian_order(state, {"code": code, "action": "buy", "quantity": quantity, "reason": "昨日建仓"},
                              {"price": 10}, NOW.replace(day=22), {}, guardian_policy=False)
    return state


def order(code, action, quantity=100):
    return {"code": code, "action": action, "quantity": quantity, "reason": "fixture", "execution": EXECUTION}


def run(state, orders, cfg, now=NOW, **extra):
    decision = StockAgentDecision.model_validate({"summary": "fixture", "orders": orders, **extra})
    codes = {o["code"] for o in orders} | {p["code"] for p in state["positions"]}
    return simulate_stock_agent(state, decision, {code: quote(code, now) for code in codes}, now, cfg)


def test_lowered_temporary_limit_no_longer_blocks_reducing_orders():
    state = holding("600000", "600001", "600002")
    _, fills, rejects = run(state, [order("600000", "reduce")], config(temporary_position_limit=2))
    assert [(f["code"], f["side"]) for f in fills] == [("600000", "sell")]
    assert rejects == []


def test_buy_over_temporary_limit_is_rejected_alone_and_stop_loss_executes():
    state = holding("600000", "600001")
    projected, fills, rejects = run(state, [order("600000", "stop_loss", 200), order("600010", "buy"),
                                            order("600011", "buy")], config(temporary_position_limit=2))
    assert [(f["code"], f["side"]) for f in fills] == [("600000", "sell"), ("600010", "buy")]
    assert [(r["code"], r["reject_code"]) for r in rejects] == [("600011", "agent_limit")]
    assert "临时持仓上限" in rejects[0]["reason"]
    assert projected["selected_today"]["codes"] == ["600010"]


def test_position_weight_cap_withdraws_only_the_heavy_buy():
    state = holding("600000")
    _, fills, rejects = run(state, [order("600010", "buy", 3000), order("600011", "buy", 1000)],
                            config(max_position_pct=10))
    assert [f["code"] for f in fills] == ["600011"]
    assert [(r["code"], r["reject_code"]) for r in rejects] == [("600010", "agent_limit")]
    assert "单股仓位" in rejects[0]["reason"]


def test_over_allocation_without_keep_list_withdraws_buys_but_keeps_sells():
    state = holding("600000", "600001")
    projected, fills, rejects = run(state, [order("600001", "reduce"), order("600010", "buy")],
                                    config(position_limit=2, temporary_position_limit=4))
    assert [(f["code"], f["side"]) for f in fills] == [("600001", "sell")]
    assert [(r["code"], r["reject_code"]) for r in rejects] == [("600010", "agent_limit")]
    assert "留仓名单" in rejects[0]["reason"]
    assert len(projected["positions"]) == 2


def test_over_allocation_with_valid_keep_list_still_allowed():
    state = holding("600000", "600001")
    projected, fills, _ = run(state, [order("600010", "buy")], config(position_limit=2, temporary_position_limit=4),
                              close_keep_codes=["600000", "600010"])
    assert [f["code"] for f in fills] == ["600010"]
    assert projected["agent_close_keep_codes"] == ["600000", "600010"]
    assert projected["agent_close_plan_date"] == "2026-09-23"


def test_no_new_over_allocation_after_1450():
    state = holding("600000", "600001")
    _, fills, rejects = run(state, [order("600010", "buy")], config(position_limit=2, temporary_position_limit=4),
                            now=CLOSE, close_keep_codes=["600000", "600010"])
    assert fills == []
    assert "14:50后禁止新增临时超配" in rejects[0]["reason"]


def test_lowered_position_limit_without_plan_is_left_to_the_model():
    state = holding("600000", "600001")
    cfg = config(position_limit=1)
    # 旧账户在未超配时存的是 []：不能被当成“收盘全部清仓”的名单
    assert closing_stock_agent_decision({**state, "agent_close_keep_codes": []}, CLOSE, cfg) is None
    assert closing_stock_agent_decision(state, CLOSE, cfg) is None  # 没有名单时不再每轮抛错
    projected, fills, rejects = run(state, [order("600000", "hold", 0)], cfg, now=CLOSE)
    assert fills == [] and rejects == []
    assert projected["agent_close_keep_codes"] == [] and "agent_close_plan_date" not in projected


def test_explicit_keep_plan_still_converges_at_close():
    state = {**holding("600000", "600001", "600002"), "agent_close_keep_codes": ["600000", "600003"],
             "agent_close_plan_date": "2026-09-22"}
    decision = closing_stock_agent_decision(state, CLOSE, config(position_limit=1))
    assert sorted(o.code for o in decision.orders) == ["600001", "600002"]
    assert decision.close_keep_codes == ["600000"]
    explicit_empty = {**holding("600000", "600001"), "agent_close_keep_codes": [], "agent_close_plan_date": "2026-09-23"}
    assert len(closing_stock_agent_decision(explicit_empty, CLOSE, config(position_limit=1)).orders) == 2


def test_close_plan_not_covering_today_locked_buy_is_not_forced():
    state = holding("600000", "600001")
    settle_guardian_order(state, {"code": "600010", "action": "buy", "quantity": 100, "reason": "今日"},
                          {"price": 10}, NOW, {}, guardian_policy=False)
    state["agent_close_keep_codes"] = ["600000"]
    assert closing_stock_agent_decision(state, CLOSE, config(position_limit=1)) is None


@pytest.mark.parametrize(("before", "after", "blocked"), [(3, 3, False), (3, 2, False), (3, 4, True), (1, 3, True)])
def test_commit_limits_only_block_growth(before, after, blocked):
    def state(count):
        return {"positions": [{"code": f"60000{i}"} for i in range(count)], "watchlist": [],
                "selected_today": {"date": "2026-09-23", "codes": []}}
    assert _exceeds_agent_limits(config(temporary_position_limit=2), state(before), state(after)) is blocked
