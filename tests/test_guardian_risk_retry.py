"""风险拒单的模型新授权须消费原合同，撤回须保留尚未执行的保护。"""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from src.ledger.domain.guardian_account import new_guardian_account, settle_guardian_order
from src.ops.application.guardian_decision import simulate
from src.ops.application.guardian_risk import evaluate_risk_plans, install_risk_plans
from src.ops.application.guardian_risk_execution import (
    finish_risk_execution,
    reauthorize_risk_events,
    risk_decision,
)


NOW = datetime.fromisoformat("2026-10-13T10:00:00+08:00")


def quote(price, now=NOW):
    return {"600000": {"code": "600000", "price": price, "source": "tencent",
                       "trade_date": now.date().isoformat(), "trade_time": now.strftime("%H:%M:%S")}}


def triggered_fixture():
    state = new_guardian_account()
    settle_guardian_order(state, {"code": "600000", "action": "buy", "quantity": 400,
                                 "reason": "昨日建仓"}, {"price": 10}, NOW - timedelta(days=1), {})
    install_risk_plans(state["positions"][0], [
        {"action": "stop_loss", "quantity": 200, "trigger_price": 10, "reason": "首道止损",
         "execution": {"kind": "market", "valid_until": "2026-10-13T14:55:00+08:00"}},
        {"action": "stop_loss", "quantity": 400, "trigger_price": 9, "reason": "剩余持仓保护",
         "execution": {"kind": "market", "valid_until": "2026-10-13T14:55:00+08:00"}},
    ], NOW)
    state, orders, events = evaluate_risk_plans(state, quote(10), NOW)
    decision = risk_decision(orders, events)
    assert decision is not None
    return state, decision, events


def test_reauthorized_risk_fill_consumes_original_contract_once_and_keeps_remaining_protection():
    state, original, events = triggered_fixture()
    contracts = deepcopy(state["positions"][0]["risk_plans"])
    evidence = deepcopy(events)
    refreshed = NOW + timedelta(seconds=20)
    quotes = quote(10.21, refreshed)
    _, fills, rejects = simulate(state, original, [], quotes, refreshed,
                                require_execution_terms=True, risk_only=True)
    assert not fills and rejects[0]["reject_code"] == "price_condition"
    revised_order = original.orders[0].model_copy(update={
        "quantity": 100, "reason": "核对反弹报价后仍止损，缩量执行",
        "execution": original.orders[0].execution.model_copy(update={
            "reference_price": 10.21, "max_price": 10.21}),
    })
    revised = original.model_copy(update={"orders": [revised_order]})
    updated, fills, rejects = simulate(state, revised, [], quotes, refreshed,
                                      require_execution_terms=True, risk_only=True)
    assert not rejects and len(fills) == 1
    reauthorized = reauthorize_risk_events(events, revised)
    assert events == evidence
    assert reauthorized[0]["original_order"] == evidence[0]["order"]
    assert reauthorized[0]["reauthorized"] is True
    for key in ("plan_id", "basis_quantity", "basis_opened_at"):
        assert reauthorized[0][key] == evidence[0][key]
    assert state["positions"][0]["risk_plans"] == contracts

    finished, receipts = finish_risk_execution(updated, reauthorized, fills, quotes, refreshed)
    position = finished["positions"][0]
    consumed, remaining = position["risk_plans"]
    assert position["quantity"] == 300
    assert consumed["status"] == "executed" and consumed["executed_quantity"] == 100
    assert consumed["plan_id"] == contracts[0]["plan_id"]
    assert consumed["contract"] == contracts[0]["contract"]
    assert receipts[0]["status"] == "executed" and receipts[0]["reauthorized"] is True
    assert remaining["status"] == "active" and remaining["basis_quantity"] == 300
    assert remaining["contract"]["quantity"] == 300
    assert remaining["contract"]["trigger_price"] == contracts[1]["contract"]["trigger_price"]
    assert remaining["contract"]["execution"] == contracts[1]["contract"]["execution"]
    assert any(event["status"] == "adjusted" for event in receipts)
    next_now = refreshed + timedelta(minutes=5)
    _, next_orders, _ = evaluate_risk_plans(finished, quote(9.9, next_now), next_now)
    assert next_orders == []


@pytest.mark.parametrize("keep_zero_order", [False, True])
def test_withdrawn_risk_retry_has_no_fill_and_leaves_original_contract_active(keep_zero_order):
    state, original, events = triggered_fixture()
    contracts = deepcopy(state["positions"][0]["risk_plans"])
    evidence = deepcopy(events)
    orders = [original.orders[0].model_copy(update={"quantity": 0})] if keep_zero_order else []
    revised = original.model_copy(update={"orders": orders})
    reauthorized = reauthorize_risk_events(events, revised)
    assert reauthorized[0]["status"] == "withdrawn"
    assert reauthorized[0]["order"] == evidence[0]["order"]
    assert events == evidence
    executable = revised.model_copy(update={"orders": []})
    updated, fills, rejects = simulate(state, executable, [], quote(10), NOW,
                                      require_execution_terms=True, risk_only=True)
    assert not fills and not rejects
    finished, receipts = finish_risk_execution(updated, reauthorized, fills, quote(10), NOW)
    assert finished["positions"][0]["quantity"] == 400
    assert finished["positions"][0]["risk_plans"] == contracts
    assert receipts[0]["status"] == "withdrawn"
    _, next_orders, _ = evaluate_risk_plans(finished, quote(10), NOW)
    assert len(next_orders) == 1 and next_orders[0]["quantity"] == 200


def test_risk_reauthorization_preserves_unchanged_and_unrelated_events():
    _, decision, events = triggered_fixture()
    unrelated = {"code": "600001", "status": "expired", "reason": "合同到期"}
    original = [*events, unrelated]
    revised = reauthorize_risk_events(original, decision)
    assert revised == original and revised is not original
    revised[0]["order"]["quantity"] = 100
    assert original[0]["order"]["quantity"] == 200
