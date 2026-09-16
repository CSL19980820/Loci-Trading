"""风险授权、报价、最终价格复核与真实成交消费；只使用隔离账本。"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.ledger import GuardianStore, new_guardian_account, settle_guardian_order
from src.ops.application.guardian_contract import ExecutionTerms, execution_error
from src.ops.application.guardian_risk import (
    RiskPlan, consume_risk_plans, evaluate_risk_plans, install_risk_plans,
)
from src.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CODE = "603920"


def _plan(**changes: Any) -> dict[str, Any]:
    return {"action": "stop_loss", "quantity": 500, "trigger_price": 9.0,
            "execution": {"kind": "market", "valid_until": (NOW + timedelta(days=3)).isoformat()},
            "reason": "跌破研究确认的止损价", **changes}


def _quote(price: float = 9.0, *, code: str = CODE, now: datetime = NOW, **changes: Any) -> dict:
    return {"code": code, "name": "测试股票", "price": price, "source": "fixture",
            "trade_date": now.date().isoformat(), "trade_time": now.strftime("%H:%M:%S"), **changes}


def _state(*, now: datetime = NOW - timedelta(days=1)) -> tuple[dict, dict]:
    state = new_guardian_account()
    fill = settle_guardian_order(state, {"code": CODE, "action": "buy", "quantity": 1000,
                                        "reason": "fixture"}, _quote(10, now=now), now, {})
    return state, fill


def _triggered(plan: dict | None = None) -> tuple[dict, list[dict], list[dict]]:
    state, _ = _state()
    install_risk_plans(state["positions"][0], [plan or _plan()], NOW)
    return evaluate_risk_plans(state, {CODE: _quote()}, NOW)


@pytest.mark.parametrize("quantity", [True, False, 0, -1, 100.0, "100", None])
def test_quantity_is_a_strict_positive_integer(quantity):
    with pytest.raises(ValidationError):
        RiskPlan.model_validate(_plan(quantity=quantity))


@pytest.mark.parametrize("price", [True, False, 0, -1, float("inf"), float("-inf"), float("nan")])
def test_trigger_is_finite_positive_and_not_boolean(price):
    with pytest.raises(ValidationError):
        RiskPlan.model_validate(_plan(trigger_price=price))


@pytest.mark.parametrize("changes", [
    {"action": "sell"}, {"reason": " "}, {"execution": None}, {"unknown": 1},
    {"execution": {"kind": "market", "valid_until": "2026-09-16T10:00:00"}},
    {"execution": {"kind": "limit", "min_price": 10, "valid_until": NOW.isoformat()}},
    {"action": "take_profit", "execution": {"kind": "limit", "max_price": 8, "valid_until": NOW.isoformat()}},
])
def test_contract_rejects_missing_authorization_and_impossible_ranges(changes):
    with pytest.raises(ValidationError):
        RiskPlan.model_validate(_plan(**changes))


def test_install_preserves_null_withdraws_empty_and_deduplicates():
    state, _ = _state()
    position = state["positions"][0]
    source = _plan()
    model = RiskPlan.model_validate(source)
    install_risk_plans(position, [model, source], NOW)
    saved = copy.deepcopy(position)
    row = position["risk_plans"][0]
    assert len(position["risk_plans"]) == 1
    assert row["contract"] == model.model_dump(mode="json")
    assert row["basis_quantity"] == 1000
    assert row["basis_opened_at"] == position["entry_context"]["opened_at"]
    assert row["status"] == "active" and row["plan_id"]
    install_risk_plans(position, None, NOW + timedelta(minutes=1))
    install_risk_plans(position, [source], NOW + timedelta(minutes=2))
    assert position == saved
    source["execution"]["valid_until"] = "changed externally"
    assert position == saved
    install_risk_plans(position, [], NOW)
    assert position["risk_plans"] == []


@pytest.mark.parametrize("code,total,quantity,valid", [
    (CODE, 1000, 500, True), (CODE, 1000, 1100, False), (CODE, 1000, 150, False),
    (CODE, 150, 50, True), (CODE, 100, 50, False), (CODE, 250, 150, True),
    ("688001", 400, 201, True), ("688001", 400, 199, False), ("688001", 199, 199, True),
    ("920001", 201, 101, True), ("920001", 201, 99, False), ("920001", 99, 99, True),
    ("510300", 1000, 100, False),
])
def test_install_uses_existing_board_rules_on_total_holdings(code, total, quantity, valid):
    position = {"code": code, "quantity": total, "available_quantity": 0}
    if valid:
        install_risk_plans(position, [_plan(quantity=quantity)], NOW)
        assert position["risk_plans"][0]["contract"]["quantity"] == quantity
    else:
        with pytest.raises(ValueError):
            install_risk_plans(position, [_plan(quantity=quantity)], NOW)
        assert "risk_plans" not in position


def test_failed_install_is_atomic_and_does_not_replace_previous_plan():
    position = {"code": CODE, "quantity": 1000}
    install_risk_plans(position, [_plan()], NOW)
    before = copy.deepcopy(position)
    with pytest.raises(ValueError):
        install_risk_plans(position, [_plan(trigger_price=8), _plan(quantity=150)], NOW)
    assert position == before


@pytest.mark.parametrize("action,trigger,price,expected", [
    ("stop_loss", 9, 8.99, True), ("stop_loss", 9, 9, True), ("stop_loss", 9, 9.01, False),
    ("take_profit", 12, 12.01, True), ("take_profit", 12, 12, True), ("take_profit", 12, 11.99, False),
])
def test_trigger_inclusive_boundaries_and_ordinary_orders(action, trigger, price, expected):
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan(action=action, trigger_price=trigger)], NOW)
    before = copy.deepcopy(state)
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote(price)}, NOW)
    assert state == before and updated == before and updated is not state
    assert bool(orders) is expected
    assert len(events) == len(orders)
    if expected:
        order = orders[0]
        assert set(order) == {"code", "action", "quantity", "reason", "execution"}
        assert (order["code"], order["action"], order["quantity"]) == (CODE, action, 500)
        terms = ExecutionTerms.model_validate(order["execution"])
        assert terms.kind == "limit"
        assert (terms.max_price if action == "stop_loss" else terms.min_price) == trigger
        assert events[0]["status"] == "triggered" and events[0]["order"] == order
        order["execution"]["kind"] = "mutated"
        assert events[0]["order"]["execution"]["kind"] == "limit"
    updated["positions"][0]["risk_plans"][0]["contract"]["reason"] = "changed"
    assert state == before


def test_stop_has_priority_and_only_one_order_per_stock():
    state, _ = _state()
    position = state["positions"][0]
    install_risk_plans(position, [_plan(action="take_profit", trigger_price=8),
                                  _plan(trigger_price=10), _plan(trigger_price=9)], NOW)
    second = copy.deepcopy(position)
    second["code"] = "002046"
    second["risk_plans"] = []
    install_risk_plans(second, [_plan()], NOW)
    state["positions"].append(second)
    _, orders, events = evaluate_risk_plans(state, {CODE: _quote(), "002046": _quote(code="002046")}, NOW)
    assert [(o["code"], o["action"]) for o in orders] == [(CODE, "stop_loss"), ("002046", "stop_loss")]
    assert events[0]["plan_id"] == position["risk_plans"][1]["plan_id"]


@pytest.mark.parametrize("quote", [{}, None, {"price": 9}, _quote(trade_time="09:56:59"),
    _quote(trade_time="10:00:01"), _quote(code="002046"), _quote(True), _quote(float("nan")),
    _quote(error="upstream unavailable")])
def test_bad_quote_never_triggers_or_consumes(quote):
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan()], NOW)
    updated, orders, events = evaluate_risk_plans(state, {CODE: quote}, NOW)
    assert orders == [] and events[0]["status"] == "quote_unavailable"
    assert updated["positions"][0]["risk_plans"][0]["status"] == "active"
    assert updated == state


def test_current_price_alias_and_naive_shanghai_clock():
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan()], NOW.replace(tzinfo=None))
    quote = _quote()
    quote["current_price"] = quote.pop("price")
    _, orders, _ = evaluate_risk_plans(state, {CODE: quote}, NOW.replace(tzinfo=None))
    assert len(orders) == 1


@pytest.mark.parametrize("offset", [-1, 0])
def test_expiry_is_terminal_even_without_quote(offset):
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan(execution={"kind": "market",
        "valid_until": (NOW + timedelta(seconds=offset)).isoformat()})], NOW - timedelta(minutes=1))
    updated, orders, events = evaluate_risk_plans(state, {}, NOW)
    assert not orders and events[0]["status"] == "expired"
    assert updated["positions"][0]["risk_plans"][0]["status"] == "expired"
    _, retry, retry_events = evaluate_risk_plans(updated, {CODE: _quote()}, NOW)
    assert retry == retry_events == []


@pytest.mark.parametrize("change", ["quantity_up", "quantity_down", "opened_at"])
def test_changed_holding_basis_invalidates_before_quotes(change):
    state, _, _ = _triggered()
    position = state["positions"][0]
    if change == "opened_at":
        position["entry_context"]["opened_at"] = NOW.isoformat()
    else:
        position["quantity"] += 100 if change == "quantity_up" else -100
    updated, orders, events = evaluate_risk_plans(state, {}, NOW)
    assert orders == [] and events[0]["status"] == "invalidated"
    assert updated["positions"][0]["risk_plans"][0]["status"] == "invalidated"
    assert position["risk_plans"][0]["status"] == "active"


@pytest.mark.parametrize("action,trigger,lower,upper,price,final", [
    ("stop_loss", 9, 8, 8.9, 8.8, 9.1),
    ("take_profit", 12, 12.1, 13, 12.2, 11.85),
])
def test_trigger_intersects_original_limits_and_final_quote_can_reject(action, trigger, lower, upper, price, final):
    state, _ = _state()
    source = _plan(action=action, trigger_price=trigger, execution={"kind": "limit",
        "min_price": lower, "max_price": upper, "valid_until": (NOW + timedelta(hours=1)).isoformat()})
    install_risk_plans(state["positions"][0], [source], NOW)
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote(price)}, NOW)
    terms = ExecutionTerms.model_validate(orders[0]["execution"])
    assert (terms.min_price, terms.max_price) == (lower, upper)
    assert execution_error(terms, price, NOW, required=True) == ("", "")
    assert execution_error(terms, final, NOW, required=True)[0] == "price_condition"
    consume_risk_plans(updated, events, [])
    assert updated["positions"][0]["risk_plans"][0]["status"] == "active"
    assert events[0]["status"] == "triggered"


def test_t1_rejection_retries_next_day_and_full_exit_is_in_events():
    state, _ = _state(now=NOW)
    position = state["positions"][0]
    install_risk_plans(position, [_plan(quantity=1000)], NOW)
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote()}, NOW)
    with pytest.raises(ValueError, match=r"T\+1"):
        settle_guardian_order(updated, orders[0], _quote(), NOW, {})
    consume_risk_plans(updated, events, [])
    assert updated["positions"][0]["risk_plans"][0]["status"] == "active"
    tomorrow = NOW + timedelta(days=1)
    updated, orders, events = evaluate_risk_plans(updated, {CODE: _quote(now=tomorrow)}, tomorrow)
    fill = settle_guardian_order(updated, orders[0], _quote(now=tomorrow), tomorrow, {})
    consume_risk_plans(updated, events, [fill])
    assert updated["positions"] == [] and events[0]["status"] == "executed"
    assert events[0]["executed_quantity"] == 1000


def test_partial_fill_consumes_once_and_duplicate_install_never_rearms():
    source = _plan(quantity=800)
    updated, orders, events = _triggered(source)
    plan_id = events[0]["plan_id"]
    fill = settle_guardian_order(updated, orders[0], _quote(), NOW, {})
    consume_risk_plans(updated, events, [fill])
    position = updated["positions"][0]
    assert position["quantity"] == 200
    assert position["risk_plans"][0]["status"] == events[0]["status"] == "executed"
    saved = copy.deepcopy((updated, events))
    consume_risk_plans(updated, events, [fill])
    assert (updated, events) == saved
    install_risk_plans(position, [source], NOW + timedelta(minutes=1))
    install_risk_plans(position, [{**source, "reason": "仅更新说明"}], NOW + timedelta(minutes=2))
    assert position["risk_plans"][0]["status"] == "executed"
    assert position["risk_plans"][0]["plan_id"] == plan_id
    assert position["risk_plans"][0]["basis_quantity"] == 1000
    _, retry, _ = evaluate_risk_plans(updated, {CODE: _quote()}, NOW)
    assert retry == []


@pytest.mark.parametrize("changes", [
    {"code": "002046"}, {"side": "buy"}, {"action": "take_profit"},
    {"quantity": 100}, {"quantity": True}, {"reason": "另一个授权"},
    {"before_quantity": 1500}, {"after_quantity": 0}, {"price_cents": 0},
    {"price_cents": 919},
    {"reject_code": "t_plus_one"}, {"execution": None},
    {"occurred_at": (NOW - timedelta(seconds=1)).isoformat()},
    {"occurred_at": (NOW + timedelta(days=4)).isoformat()},
])
def test_unrelated_or_rejected_fills_cannot_consume_plan(changes):
    updated, orders, events = _triggered()
    fill = settle_guardian_order(updated, orders[0], _quote(), NOW, {})
    consume_risk_plans(updated, events, [{**fill, **changes}])
    assert updated["positions"][0]["risk_plans"][0]["status"] == "active"
    assert events[0]["status"] == "triggered"


def test_partial_sale_invalidates_other_plan_on_next_evaluation():
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan(), _plan(action="take_profit", trigger_price=12)], NOW)
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote()}, NOW)
    fill = settle_guardian_order(updated, orders[0], _quote(), NOW, {})
    consume_risk_plans(updated, events, [fill])
    final, orders, events = evaluate_risk_plans(updated, {CODE: _quote(12)}, NOW)
    assert not orders and events[0]["status"] == "invalidated"
    assert [r["status"] for r in final["positions"][0]["risk_plans"]] == ["executed", "invalidated"]


def test_old_event_cannot_consume_reopened_position_of_same_size():
    updated, orders, events = _triggered(_plan(quantity=1000))
    old_id = events[0]["plan_id"]
    fill = settle_guardian_order(updated, orders[0], _quote(), NOW, {})
    settle_guardian_order(updated, {"code": CODE, "action": "buy", "quantity": 1000,
                                   "reason": "新的开仓"}, _quote(), NOW, {})
    install_risk_plans(updated["positions"][0], [_plan(quantity=1000)], NOW)
    row = updated["positions"][0]["risk_plans"][0]
    assert row["plan_id"] != old_id
    consume_risk_plans(updated, events, [fill])
    assert row["status"] == "active"


def test_contracts_roundtrip_in_separate_tenant_ledgers():
    tenants = [("risk_alpha", 8.0), ("risk_beta", 9.0)]
    for tenant, trigger in tenants:
        with tenant_scope(tenant), GuardianStore() as ledger:
            assert ledger.claim("risk-install")
            state, fill = _state()
            install_risk_plans(state["positions"][0], [_plan(trigger_price=trigger)], NOW)
            ledger.finish("risk-install", {"status": "success", "fills": [fill]}, state)
    for tenant, trigger in tenants:
        with tenant_scope(tenant), GuardianStore() as ledger:
            row = ledger.state()["positions"][0]["risk_plans"][0]
            assert row["status"] == "active" and row["contract"]["trigger_price"] == trigger


@pytest.mark.parametrize("action,trigger,final", [("stop_loss", 9, 9.19), ("take_profit", 12, 11.75)])
def test_market_plan_rejects_rebound_beyond_two_percent(action, trigger, final):
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan(action=action, trigger_price=trigger)], NOW)
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote(trigger)}, NOW)
    terms = ExecutionTerms.model_validate(orders[0]["execution"])
    assert execution_error(terms, final, NOW, required=True)[0] == "price_condition"
    consume_risk_plans(updated, events, [])
    _, retry, _ = evaluate_risk_plans(updated, {CODE: _quote(trigger)}, NOW)
    assert len(retry) == 1


@pytest.mark.parametrize("remaining_sell", [100, 500])
def test_later_same_cycle_sale_does_not_hide_actual_risk_fill(remaining_sell):
    updated, orders, events = _triggered()
    risk_fill = settle_guardian_order(updated, orders[0], _quote(), NOW, {})
    later = settle_guardian_order(updated, {"code": CODE, "action": "sell",
        "quantity": remaining_sell, "reason": "后续独立卖出"}, _quote(), NOW, {})
    consume_risk_plans(updated, events, [risk_fill, later])
    assert events[0]["status"] == "executed"
    if updated["positions"]:
        assert updated["positions"][0]["risk_plans"][0]["status"] == "executed"


@pytest.mark.parametrize("contract", [None, [], {"action": "sell"}])
def test_malformed_persisted_contract_is_invalidated(contract):
    state, _, _ = _triggered()
    state["positions"][0]["risk_plans"][0]["contract"] = contract
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote()}, NOW)
    assert orders == [] and events[0]["status"] == "invalidated"
    assert updated["positions"][0]["risk_plans"][0]["status"] == "invalidated"
