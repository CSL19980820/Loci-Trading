from copy import deepcopy

import pytest

from src.ops.application.guardian_context import premarket_plan_context
from src.ops.application.guardian_review_format import _plan


def report():
    position = {'code': '002349', 'quantity': 4500, 'available_quantity': 4500, 'cost_cents': 3916018}
    plans = [{'code': '002349', 'action': action, 'quantity': quantity, 'trigger': trigger, 'invalidation': '条件未成立'}
             for action, quantity, trigger in [('take_profit', 2200, '冲高滞涨'),
                                                ('reduce', 2200, '低开不修复'),
                                                ('stop_loss', 4500, '跌破失效位')]]
    return {'status': 'success', 'result': {'facts': {'account': {'positions': [position]}},
                                           'analysis': {'summary': '计划', 'plans': plans}}}


def test_alternative_trims_show_remaining_shares_and_stop_is_remaining_liquidation():
    saved = report()['result']
    position = saved['facts']['account']['positions'][0]
    labels = [_plan(p, position)['label'] for p in saved['analysis']['plans']]
    assert '卖2,200股 → 余2,300股（本项单独触发）' in labels[0]
    assert '卖2,200股 → 余2,300股（本项单独触发）' in labels[1]
    assert '清仓当时剩余可卖' in labels[2]
    assert '报告时4,500股' in labels[2]


@pytest.mark.parametrize('change', [
    {'quantity': 2300, 'available_quantity': 2300, 'cost_cents': 2000000},
    {'available_quantity': 2300},
    {'cost_cents': 4000000},
])
def test_position_change_invalidates_old_plan_quantities_but_preserves_conditions(change):
    saved = report(); original = deepcopy(saved)
    position = {**saved['result']['facts']['account']['positions'][0], **change}
    context = premarket_plan_context(saved, {'positions': [position]})
    assert [p['quantity'] for p in context['plans']] == [None, None, None]
    assert [p['snapshot_quantity'] for p in context['plans']] == [2200, 2200, 4500]
    assert [p['trigger'] for p in context['plans']] == ['冲高滞涨', '低开不修复', '跌破失效位']
    assert context['plans'][2]['current_available'] == position['available_quantity']
    assert saved == original


def test_closed_position_does_not_reuse_original_sell_quantity():
    context = premarket_plan_context(report(), {'positions': []})
    assert all(p['quantity'] is None and p['current_available'] == 0 for p in context['plans'])


def test_unchanged_position_retains_snapshot_and_conditions_are_not_cumulative():
    saved = report()
    context = premarket_plan_context(saved, saved['result']['facts']['account'])
    assert [p['quantity'] for p in context['plans']] == [2200, 2200, 4500]
    assert '不是累计卖单' in context['execution_note']
