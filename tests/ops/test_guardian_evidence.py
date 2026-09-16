import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ledger import GuardianStore, new_guardian_account, settle_guardian_order
from src.ops import OpsStore
from src.ops.application import guardian_consult
from src.ops.application.guardian_config import save_config
from src.ops.application.guardian_evidence import (
    HISTORY_TOOL, consultation_day, cycle_evidence, decision_context, decision_history,
)
from src.shared.tenancy import tenant_scope

DAY = '2026-09-15'
SLOT = DAY + 'T09:30:00+08:00'


def record(ledger, slot=SLOT, **result):
    assert ledger.claim(slot)
    ledger.finish(slot, {'status': 'success', **result})


def test_history_reads_opening_record_beyond_recent_five_and_pages(tmp_path):
    with GuardianStore(tmp_path / 'history.db') as ledger:
        record(ledger, analysis='常态3只，暂不新增', candidates=[{'code': '300537'}],
               decisions=[{'code': '300537', 'action': 'watch', 'reason': '主力净买93万，资金支撑一般'}])
        for minute in range(10):
            record(ledger, DAY + f'T14:{minute:02d}:00+08:00', analysis='尾盘')
        assert not any(c['slot'] == SLOT for c in ledger.recent(5))
        first = decision_history(ledger, day=DAY, code='300537', limit=1)
        assert first['total'] == 11 and first['next_offset'] == 1
        assert first['items'][0]['decisions'][0]['reason'] == '主力净买93万，资金支撑一般'
        assert first['items'][0]['position_policy'] is None
        assert first['items'][0]['policy_evidence'] == 'not_recorded'
        second = decision_history(ledger, day=DAY, code='300537', offset=1, limit=10)
        assert len(second['items']) == 10 and second['next_offset'] is None
        assert second['items'][0]['decisions'] == []


def test_snapshot_survives_failure_without_replacing_it_with_current_state(tmp_path):
    payload = {'as_of': SLOT, 'portfolio': new_guardian_account(),
               'candidates': [{'code': '300537', 'signals': [{'timing': '次日开盘'}]}]}
    saved = decision_context(payload)
    payload['portfolio']['cash_cents'] = 0
    payload['candidates'].clear()
    with GuardianStore(tmp_path / 'snapshot.db') as ledger:
        assert ledger.claim(SLOT)
        ledger.annotate(SLOT, {'decision_context': saved})
        ledger.finish(SLOT, {'status': 'failed', 'error': '模型中断'})
        item = decision_history(ledger, day=DAY)['items'][0]
        assert item['account_before']['cash_cents'] == 20_000_000
        assert item['input_candidates'][0]['signals'][0]['timing'] == '次日开盘'
        assert item['policy_evidence'] == 'recorded_before_research'
        assert item['position_policy'] == saved['position_policy']
        assert item['candidate_assessments'] == [{'code': '300537', 'status': 'not_recorded'}]


def test_account_at_slot_excludes_later_fills_and_preserves_t1(tmp_path):
    with GuardianStore(tmp_path / 'account.db') as ledger:
        state = ledger.state()
        stamp = datetime.fromisoformat(DAY + 'T09:36:09+08:00')
        fill = settle_guardian_order(state, {'code': '300285', 'action': 'buy', 'quantity': 100, 'reason': '测试'},
                                    {'price': 10, 'name': '国瓷材料'}, stamp, {})
        assert ledger.claim(DAY + 'T09:35:00+08:00')
        ledger.finish(DAY + 'T09:35:00+08:00', {'status': 'success', 'fills': [fill]}, state)
        record(ledger, DAY + 'T09:40:00+08:00')
        items = decision_history(ledger, day=DAY)['items']
        assert items[0]['account_before']['positions'] == []
        assert items[0]['account_before']['cash_cents'] == 20_000_000
        assert items[1]['account_before'] is not None, items[1].get('account_error')
        assert items[1]['account_before']['cash_cents'] == fill['cash_after_cents']
        assert items[1]['account_before']['positions'][0]['available_quantity'] == 0


def test_missing_stock_reason_is_not_fabricated_and_conditions_are_compared():
    cycle = {'slot': SLOT, 'status': 'success', 'result': {
        'candidates': [{'code': '300537', 'watch': {'entry_condition': '站稳20.00'}}, {'code': '000957'}],
        'decisions': [{'code': '300537', 'action': 'watch', 'entry_condition': '站稳20.30', 'reason': '资金支撑一般'}]}}
    item = cycle_evidence(cycle)
    assert item['candidate_assessments'][1] == {'code': '000957', 'status': 'not_recorded'}
    assert item['condition_changes'] == [{'code': '300537', 'before': '站稳20.00', 'after': '站稳20.30', 'recorded_reason': '资金支撑一般'}]
    assert item['rejects'] == []


def test_large_input_is_available_on_demand_without_hiding_candidates(tmp_path):
    original = {'code': '300537', 'signals': [{'id': 'signal-1', 'timing': '次日开盘', 'evidence': {'raw': 'x' * 100_000}}]}
    with GuardianStore(tmp_path / 'large.db') as ledger:
        record(ledger, candidates=[original, {'code': '000957'}], decisions=[])
        summary = decision_history(ledger, day=DAY)
        assert len(json.dumps(summary)) < 10_000
        assert [c['code'] for c in summary['items'][0]['input_candidates']] == ['300537', '000957']
        full = decision_history(ledger, day=DAY, code='300537', include_inputs=True)
        assert full['items'][0]['input_candidates'] == [original]
        assert full['items'][0]['input_detail'] == 'full'


def test_consultation_receives_history_and_only_reads_its_own_tenant(monkeypatch):
    from src.ai import ProviderConfig
    provider = ProviderConfig('test', 'openai_compatible', 'https://example.invalid', 'test', 'test')
    monkeypatch.setattr('src.ai.resolve_config', lambda *a, **kw: provider)
    monkeypatch.setattr('src.ai.record_llm_usage', lambda **kw: None)
    monkeypatch.setattr(guardian_consult, 'agent_tools', lambda *a, **kw: ([], Mock(), {'label': 'test'}))
    with tenant_scope('evidence_other'), GuardianStore() as other:
        record(other, analysis='其他租户的秘密')
    def run(*args, **kwargs):
        payload = json.loads(kwargs['messages'][-1].content)
        assert payload['decision_history']['date'] == DAY
        assert payload['decision_history']['items'][0]['analysis'] == '主租户的原始判断'
        assert '历史' in payload['current_policy_note']
        tool = kwargs['tool_executor']
        result = tool(HISTORY_TOOL, {'date': DAY, 'code': '300537'})
        assert '其他租户的秘密' not in result['text']
        assert '主租户的原始判断' in result['text']
        assert tool(HISTORY_TOOL, {'date': DAY, 'tenant': 'evidence_other'})['is_error']
        return SimpleNamespace(stopped_reason='completed', rounds=1, finish_reason='stop', text='根据09:30原始记录回答', model='test',
            input_tokens=10, output_tokens=5, invocations=[], messages=[])
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    with tenant_scope('evidence_current'), OpsStore(None) as store, GuardianStore() as ledger:
        save_config(store, {'provider': 'test', 'model': 'test'})
        record(ledger, analysis='主租户的原始判断')
        ledger.submit_consultation('topic', 'request', '2026年9月15日为什么不买？', '')
        before = ledger.state()
        result, _ = guardian_consult.answer_consultation(store, ledger, ledger.claim_consultation('request'))
        assert len(result['decision_evidence_reads']) == 2
        assert ledger.state() == before and ledger.trades()['total'] == 0


@pytest.mark.parametrize('question', ['2026-09-15开盘为何没买', '2026年9月15日开盘为何没买'])
def test_explicit_historical_date_is_not_replaced_by_today(question):
    assert consultation_day(question, '2026-09-16') == DAY
