from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.ledger import new_guardian_account, check_guardian_account
from src.ops.application.guardian_decision import GuardianDecision, simulate, closing_decision, render_digest
from src.ops.application.notify import split_text_for_wecom

NOW = datetime(2026, 9, 14, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
OLD = [f"60000{i}" for i in range(1, 5)]
NEW = [f"60000{i}" for i in range(5, 9)]


def buy(code, **extra):
    return {"code": code, "action": "buy", "quantity": 100, "reason": "自主选择", **extra}


def apply(state, orders, *, day=14, hour=10, minute=0, keep=None):
    now = NOW.replace(day=day, hour=hour, minute=minute)
    decision = GuardianDecision(summary="test", orders=orders, close_keep_codes=keep)
    codes = {p['code'] for p in state['positions']} | {o['code'] for o in orders}
    quotes = {code: {"price": 10, "name": "股票" + code,
                     "trade_date": now.date().isoformat(), "trade_time": now.strftime('%H:%M:%S')}
              for code in codes}
    return simulate(state, decision, [], quotes, now)


def four_positions():
    state, fills, rejects = apply(new_guardian_account(), [buy(code) for code in OLD])
    assert len(fills) == 4 and not rejects
    return state


def eight_positions():
    state, fills, rejects = apply(four_positions(), [buy(code) for code in NEW], day=15, keep=NEW)
    assert len(state['positions']) == 8 and len(fills) == 4 and not rejects
    return state


def test_four_normal_positions_need_no_replacement_or_exit_binding():
    assert len(four_positions()['positions']) == 4


def test_intraday_eight_is_allowed_but_ninth_is_rejected():
    state = eight_positions()
    updated, fills, rejects = apply(state, [buy('600009')], day=15)
    assert updated['cash_cents'] == state['cash_cents'] and len(updated['positions']) == 8
    assert not fills and '上限为8只' in rejects[0]['reason']


def test_fifth_locked_stock_is_impossible_to_exit_today():
    state = four_positions()
    updated, fills, rejects = apply(state, [buy('600005')])
    assert not fills and 'T+1锁定股票将超过4只' in rejects[0]['reason']
    assert updated['cash_cents'] == state['cash_cents']


def test_adding_to_sellable_stock_cannot_create_fifth_locked_stock():
    state = eight_positions()
    updated, fills, rejects = apply(state, [buy(OLD[0], action='add')], day=15)
    assert not fills and 'T+1锁定股票将超过4只' in rejects[0]['reason']
    assert updated['positions'][0]['quantity'] == 100


@pytest.mark.parametrize('keep', [None, [OLD[0]], ['600099'], [NEW[0], NEW[0]]])
def test_invalid_close_choice_refuses_whole_uncommitted_combination(keep):
    state = four_positions()
    updated, fills, rejects = apply(state, [buy(NEW[0])], day=15, keep=keep)
    assert not fills and rejects
    assert updated['positions'] == apply(state, [], day=15)[0]['positions']
    assert updated['cash_cents'] == state['cash_cents']


def test_model_can_change_which_sellable_stocks_to_keep():
    state, _, rejects = apply(four_positions(), [buy(c) for c in NEW[:2]], day=15, keep=OLD[:2] + NEW[:2])
    assert not rejects
    state, _, rejects = apply(state, [], day=15, hour=14, minute=45, keep=OLD[2:] + NEW[:2])
    assert not rejects
    decision = closing_decision(state, NOW.replace(day=15, hour=14, minute=50))
    assert [o.code for o in decision.orders] == OLD[:2]
    assert set(decision.close_keep_codes) == set(OLD[2:] + NEW[:2])


def test_eight_to_four_executes_model_choice_and_reconciles_money():
    state = eight_positions()
    now = NOW.replace(day=15, hour=14, minute=50)
    decision = closing_decision(state, now)
    assert len(decision.orders) == 4 and all(o.code in OLD for o in decision.orders)
    updated, fills, rejects = apply(state, [o.model_dump() for o in decision.orders], day=15, hour=14, minute=50)
    assert not rejects and len(fills) == 4
    assert {p['code'] for p in updated['positions']} == set(NEW)
    check_guardian_account(updated)
    assert closing_decision(updated, now) is None


def test_late_window_disallows_expansion_beyond_four():
    _, fills, rejects = apply(four_positions(), [buy(NEW[0])], day=15, hour=14, minute=50, keep=NEW[:1])
    assert not fills and '尾盘收敛期持仓上限为4只' in rejects[0]['reason']


def test_close_choice_does_not_survive_to_another_day():
    with pytest.raises(ValueError, match='必须明确'):
        closing_decision(eight_positions(), NOW.replace(day=16, hour=14, minute=50))


def test_intraday_digest_omits_all_four_costs_but_full_renderer_keeps_them():
    from src.ops.application.guardian_decision import render_positions
    state = four_positions()
    body = render_digest('很长的研究判断' * 1000, [], [], state)
    sent = split_text_for_wecom(body, max_chunks=1)[0]
    assert '持仓 4 只' in sent and '很长的研究判断' not in sent
    assert '截断' not in sent and '持仓成本' not in sent
    full = render_positions(state)
    for code in OLD:
        assert code not in sent and code in full
    assert full.count('成本 10.0026元/股') == 4
