"""用户指定的固定授权基准2%执行容差，不是交易所申报价格笼子。"""
from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.ops.application.guardian_contract import ExecutionTerms, execution_error
from tests.ops.test_guardian import EMPTY, NOW, decision, quotes


def terms(**changes) -> ExecutionTerms:
    return ExecutionTerms.model_validate({"kind": "limit", "max_price": 9,
        "valid_until": (NOW + timedelta(minutes=5)).isoformat(), **changes})


@pytest.mark.parametrize("price,expected", [(9, True), (9.01, True), (9.18, True), (9.19, False)])
def test_upper_reference_uses_exact_two_percent(price, expected):
    assert (execution_error(terms(), price, NOW, required=True) == ("", "")) is expected


@pytest.mark.parametrize("price,expected", [(9, True), (8.99, True), (8.82, True), (8.81, False)])
def test_lower_reference_uses_exact_two_percent(price, expected):
    assert (execution_error(terms(max_price=None, min_price=9), price, NOW, required=True) == ("", "")) is expected


def test_reference_is_not_advanced_by_repeated_checks():
    original = terms()
    for price in (9.01, 9.1, 9.18):
        assert execution_error(original, price, NOW, required=True) == ("", "")
    assert original.max_price == 9
    assert execution_error(original, 9.19, NOW, required=True)[0] == "price_condition"


def test_tolerance_does_not_extend_expiry():
    assert execution_error(terms(valid_until=NOW.isoformat()), 9.01, NOW, required=True)[0] == "intent_expired"


@pytest.mark.parametrize("price", [True, 0, -1, float("nan"), float("inf")])
def test_explicit_reference_rejects_non_price_values(price):
    with pytest.raises(ValidationError):
        terms(kind="market", max_price=None, reference_price=price)


def test_market_reference_is_fixed_across_refreshes():
    from src.ops.application.guardian_decision import bind_execution_references
    proposed = decision()
    first = bind_execution_references(proposed, quotes(9), NOW)
    second = bind_execution_references(first, quotes(9.18), NOW)
    assert proposed.orders[0].execution.reference_price is None
    assert second.orders[0].execution.reference_price == 9
    assert execution_error(second.orders[0].execution, 9.19, NOW, required=True)[0] == "price_condition"


def test_decimal_boundary_and_intersection():
    from src.ops.application.guardian_contract import execution_bounds
    lower, upper = execution_bounds(terms(min_price=8.9, reference_price=9.1))
    assert lower == Decimal("8.918") and upper == Decimal("9.18")


def test_preflight_and_commit_price_share_tolerance():
    from src.ops.application.guardian_decision import simulate
    proposed = decision()
    proposed.orders[0].execution = terms()
    updated, fills, rejects = simulate(EMPTY, proposed, [], quotes(9.01), NOW, require_execution_terms=True)
    assert not rejects and fills[0]["price_cents"] == 901
    assert updated["positions"][0]["quantity"] == 100


def test_risk_trigger_stays_exact_but_execution_allows_small_rebound():
    from src.ledger import settle_guardian_order
    from src.ops.application.guardian_risk import consume_risk_plans, evaluate_risk_plans, install_risk_plans
    from tests.ops.test_guardian_risk import _state, _plan, _quote, CODE, NOW as RISK_NOW
    state, _ = _state()
    install_risk_plans(state["positions"][0], [_plan()], RISK_NOW)
    _, orders, _ = evaluate_risk_plans(state, {CODE: _quote(9.01)}, RISK_NOW)
    assert orders == []
    updated, orders, events = evaluate_risk_plans(state, {CODE: _quote(9)}, RISK_NOW)
    assert len(orders) == 1
    fill = settle_guardian_order(updated, orders[0], _quote(9.01), RISK_NOW, {})
    saved = copy.deepcopy(updated)
    consume_risk_plans(updated, events, [fill])
    assert events[0]["status"] == "executed"
    _, _, other_events = evaluate_risk_plans(state, {CODE: _quote(9)}, RISK_NOW)
    consume_risk_plans(saved, other_events, [{**fill, "price_cents": 919}])
    assert other_events[0]["status"] == "triggered"


def test_new_optional_field_preserves_existing_risk_contract_id():
    from src.ops.application.guardian_risk import _plan_id
    from tests.ops.test_guardian_risk import _plan, CODE
    old = _plan()
    upgraded = copy.deepcopy(old)
    upgraded["execution"]["reference_price"] = None
    assert _plan_id(CODE, old, "opened") == _plan_id(CODE, upgraded, "opened")
