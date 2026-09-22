from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore
from src.ops.application.guardian_decision import GuardianDecision, simulate
from src.ops.application.guardian_opening_plans import (
    build_opening_plans, fold_opening_plans, pending_opening_plans, opening_plan_updates,
    validate_opening_reviews, opening_notice,
)

START = datetime(2026, 9, 21, 9, 25, tzinfo=ZoneInfo('Asia/Shanghai'))


def decision(plan_id=None, review=None, price=10, until='2026-09-21T11:30:00+08:00'):
    orders = [] if review in {'wait', 'abandon'} else [{'code': '600000', 'name': '测试股票', 'action': 'buy', 'quantity': 100,
              'reason': '自主判断', 'opening_plan_id': plan_id,
              'execution': {'kind': 'limit', 'max_price': price, 'valid_until': until}}]
    return GuardianDecision(summary='计划', orders=orders, opening_plan_reviews=[{
        'plan_id': plan_id, 'decision': review, 'reason': '依据当前行情重新判断'}] if review else [])


def save_cycle(ledger, now, result, state=None):
    assert ledger.claim(now.isoformat())
    ledger.finish(now.isoformat(), result, state)


def test_failure_and_more_than_twenty_cycles_do_not_lose_plan(tmp_path):
    with GuardianStore(tmp_path / 'palace.db') as ledger:
        initial = build_opening_plans(decision(until='2026-09-21T09:30:00+08:00'), START.isoformat())
        save_cycle(ledger, START, {'status': 'success', 'opening_plans': initial})
        for i in range(1, 26):
            now = START + timedelta(minutes=5 * i)
            pending = pending_opening_plans(ledger, now)
            assert len(pending) == 1
            save_cycle(ledger, now, {'status': 'failed', 'opening_plan_updates': opening_plan_updates(pending, unavailable='本轮失败')})
        pending = pending_opening_plans(ledger, now)
        assert pending[0]['status'] == 'unreviewed'
        assert 'history' not in pending[0]
        assert all(row['slot'] != START.isoformat() for row in ledger.recent())
        assert len(pending) == 1


def test_rejection_then_new_decision_fills_and_reconciles_actual_money(tmp_path):
    with GuardianStore(tmp_path / 'palace.db') as ledger:
        initial = build_opening_plans(decision(), START.isoformat())
        save_cycle(ledger, START, {'status': 'success', 'opening_plans': initial})
        pending = pending_opening_plans(ledger, START + timedelta(minutes=5))
        plan_id = pending[0]['id']
        for minute, price, status in [(30, 12, 'blocked'), (35, 9.9, 'executed')]:
            now = START.replace(minute=minute)
            current = decision(plan_id, 'execute')
            validate_opening_reviews(current, pending)
            quotes = {'600000': {'code': '600000', 'price': price, 'source': 'fixture',
                                 'trade_date': '2026-09-21', 'trade_time': now.strftime('%H:%M:%S')}}
            state, fills, rejects = simulate(ledger.state(), current, [], quotes, now, require_execution_terms=True)
            updates = opening_plan_updates(pending, current, fills, rejects)
            assert updates[0]['status'] == status
            save_cycle(ledger, now, {'status': 'failed' if rejects else 'success', 'fills': fills, 'opening_plan_updates': updates}, state)
            pending = pending_opening_plans(ledger, now)
        assert pending == []
        result = fold_opening_plans(ledger.opening_plan_cycles('2026-09-21'), now)[0]
        assert result['planned_amount_cents'] == 100000
        assert result['actual_gross_cents'] == 99000
        assert result['actual_fees_cents'] > 0
        assert result['filled_quantity'] == 100
        assert len(result['history']) == 2
        assert ledger.trades()['total'] == 1


def test_wait_abandon_expiry_and_missing_reviews_are_distinct():
    plans = build_opening_plans(decision(), START.isoformat())
    plan_id = plans[0]['id']
    with pytest.raises(ValueError, match='逐笔'):
        validate_opening_reviews(decision(), plans)
    for action, status in [('wait', 'waiting'), ('abandon', 'abandoned')]:
        current = decision(plan_id, action)
        validate_opening_reviews(current, plans)
        assert opening_plan_updates(plans, current)[0]['status'] == status
    cycle = {'slot': START.isoformat(), 'result': {'opening_plans': plans}}
    expired = fold_opening_plans([cycle], START.replace(hour=15, minute=0))[0]
    assert expired['status'] == 'expired'
    assert '不是模型主动放弃' in expired['last_reason']
    notice = opening_notice(decision(), plans, START)
    assert '100股' in notice and '1,000.00元' in notice
    assert '不挂单、不成交' in notice


def test_historical_deferred_is_not_converted_into_new_plan():
    assert fold_opening_plans([{'slot':START.isoformat(), 'result':{'deferred':[{'code':'600000'}]}}], START) == []
