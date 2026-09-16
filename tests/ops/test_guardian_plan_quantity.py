import json
from unittest.mock import Mock

import pytest

from src.ledger import guardian_quantity_error
from src.ops.application.guardian_review_agent import validate_plan_quantities
from tests.ops import test_guardian_review_repair as repair

setup_review = repair.setup_review


@pytest.mark.parametrize('available,quantity,valid', [
    (4500, 2250, False), (4500, 2200, True), (4500, 2300, True),
    (2250, 50, True), (2250, 2250, True), (50, 50, True),
    (50, 20, False), (2250, 25, False), (4500, 50, False), (0, 100, False),
])
def test_whole_lots_and_existing_odd_lots_share_execution_contract(available, quantity, valid):
    assert (not guardian_quantity_error('002349', quantity, True, available)) == valid


def plan(quantity):
    return {'code': '002349', 'action': 'reduce', 'quantity': quantity,
            'trigger': '原条件成立时减仓', 'invalidation': '条件未成立'}


@pytest.mark.parametrize('quantity', [2200, 2300])
def test_invalid_half_lot_is_repaired_by_model_before_report_is_accepted(setup_review, monkeypatch, quantity):
    _, billing, tool, facts = setup_review
    facts['planning_sellable'] = [{'code': '002349', 'quantity': 4500}]
    invalid = repair.completed(json.dumps({'summary': '计划', 'plans': [plan(2250)]}))
    corrected = repair.completed(json.dumps({'summary': '计划', 'plans': [plan(quantity)]}))
    run = Mock(side_effect=[invalid, corrected])
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    analysis, usage, _ = repair.call_review(facts)
    assert analysis['plans'][0]['quantity'] == quantity
    assert analysis['plans'][0]['trigger'] == plan(2250)['trigger']
    assert '2250股不符合申报规则' in usage['attempts'][0]['error']
    assert run.call_count == billing.call_count == 2
    tool.assert_not_called()


def test_repeated_illegal_quantity_never_becomes_a_success_report(setup_review, monkeypatch):
    _, _, _, facts = setup_review
    facts['planning_sellable'] = [{'code': '002349', 'quantity': 4500}]
    run = Mock(return_value=repair.completed(json.dumps({'summary': '计划', 'plans': [plan(2250)]})))
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    with pytest.raises(ValueError, match='2250股不符合申报规则'):
        repair.call_review(facts)
    assert run.call_count == 2


def test_unknown_quantity_can_remain_conditional_and_buy_still_uses_board_lot():
    validate_plan_quantities({'plans': [plan(None)]}, {})
    with pytest.raises(ValueError, match='100 股的整数倍'):
        validate_plan_quantities({'plans': [{**plan(2250), 'action': 'buy'}]}, {})
