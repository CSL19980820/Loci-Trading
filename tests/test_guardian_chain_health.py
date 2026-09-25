from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import MagicMock
import time

import pytest

from src.ledger import GuardianStore
from src.ops.application import guardian_review_agent as review
from src.ops.application.guardian_decision import parse_decision
from src.ops.application.guardian_output import load_json_response
from src.ops.application.guardian_review_checkpoint import review_fingerprint
from src.ops.application.guardian_review_prompts import review_system
from src.ops.application.guardian_risk import install_risk_plans, evaluate_risk_plans
from src.ops.application.guardian_risk_execution import risk_decision, finish_risk_execution
from src.ops.application.guardian_tool_schema import LINK_PRESENTATION, research_tool_schemas


def risk_fixture(locked=True, minimum=35.8):
    position = {'code': '600522', 'quantity': 200, 'today_bought': 200 if locked else 0,
                'bought_on': '2026-09-22', 'entry_context': {'opened_at': '2026-09-22T09:47:00+08:00'}}
    now = datetime.fromisoformat('2026-09-22T13:40:00+08:00')
    install_risk_plans(position, [{'action': 'stop_loss', 'quantity': 200, 'trigger_price': 36.6,
        'reason': 'test', 'execution': {'kind': 'limit', 'min_price': minimum,
        'valid_until': '2026-09-23T14:55:00+08:00'}}], now)
    quote = {'600522': {'code': '600522', 'price': 36.5, 'source': 'wudao',
                        'trade_date': '2026-09-22', 'trade_time': '13:40:00'}}
    return {'positions': [position]}, quote, now


def test_locked_contract_keeps_authorization_without_starving_research():
    state, quotes, now = risk_fixture()
    original = deepcopy(state)
    for minute in (40, 45):
        now = now.replace(minute=minute)
        quotes['600522']['trade_time'] = now.strftime('%H:%M:%S')
        state, orders, events = evaluate_risk_plans(state, quotes, now)
        assert risk_decision(orders, events) is None
        assert any(e['status'] == 'execution_blocked' and e['available_quantity'] == 0 for e in events)
        state, _ = finish_risk_execution(state, events, [], quotes, now)
    assert state == original
    now = now.replace(day=23)
    quotes['600522'].update(trade_date='2026-09-23')
    _, orders, _ = evaluate_risk_plans(state, quotes, now)
    assert risk_decision(orders, []) is not None and orders[0]['quantity'] == 200


def test_outside_authorized_price_does_not_starve_research_or_loosen_contract():
    state, quotes, now = risk_fixture(locked=False)
    quotes['600522']['price'] = 30
    original = deepcopy(state)
    after, orders, events = evaluate_risk_plans(state, quotes, now)
    assert not orders and events[0]['status'] == 'execution_blocked'
    assert after == original
    quotes['600522']['price'] = 36.5
    assert evaluate_risk_plans(state, quotes, now)[1][0]['quantity'] == 200


@pytest.mark.parametrize('wrapper', ['{}', '```json\n{}\n```', '```JSON\r\n{}\r\n```', '```\n{}\n```'])
def test_only_complete_json_or_harmless_wrapper_is_accepted(wrapper):
    raw = json.dumps({'summary': '保持原判断', 'orders': []})
    assert parse_decision(wrapper.replace('{}', raw)).summary == '保持原判断'


@pytest.mark.parametrize('raw', ['说明\n{"summary":"x","orders":[]}', '{} {}', '[{}]', '```json\n{}\n```尾注', '{'])
def test_ambiguous_or_partial_json_is_rejected(raw):
    with pytest.raises(ValueError):
        load_json_response(raw)


@pytest.mark.parametrize('raw', [
    '{"summary":"a","summary":"b","orders":[]}',
    '{"orders":[{"quantity":100,"quantity":10000}]}',
    '{"orders":[{"execution":{"max_price":10,"max_price":20}}]}',
    '{"experience":[{"status":"supported","status":"refuted"}]}',
    r'{"quantity":100,"\u0071uantity":10000}',
    '{"quantity":100,"quantity":100}',
])
def test_duplicate_fields_are_rejected_at_every_object_level(raw):
    with pytest.raises(ValueError, match='重复字段'):
        load_json_response(raw)


def test_same_fields_in_separate_orders_are_valid():
    raw = '{"orders":[{"quantity":100},{"quantity":200}],"reason":"quantity quantity"}'
    assert load_json_response(raw)['orders'] == [{'quantity': 100}, {'quantity': 200}]


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_duplicate_order_retries_without_accepting_ambiguous_quantity(monkeypatch, repair_succeeds):
    from src.ops.application import guardian_completion as completion
    from src.ops.application.guardian_research_context import ResearchContext
    provider = SimpleNamespace(model='fixture', context_window=100000, max_output_tokens=4096)
    raw = ('{"summary":"拟买入","orders":[{"code":"600000","action":"buy",'
           '"quantity":100,"quantity":10000,"reason":"fixture",'
           '"execution":{"kind":"market","valid_until":"2026-09-23T10:05:00+08:00"}}]}')
    seen = []
    def run(*args, **kwargs):
        seen.append(kwargs)
        if len(seen) == 2:
            assert any(m.role == 'assistant' and m.content == raw for m in kwargs['messages'])
            assert '重复字段' in kwargs['messages'][-1].content
        text = raw.replace('"quantity":100,"quantity":10000', '"quantity":100') if repair_succeeds and len(seen) == 2 else raw
        return SimpleNamespace(text=text, messages=[], stopped_reason='completed', finish_reason='stop', input_tokens=1, output_tokens=1)
    monkeypatch.setattr(completion, 'run_accounted_agent', run)
    options = dict(system='fixture', payload={}, schemas=[], execute=lambda *a: {}, archive=ResearchContext(),
                   checkpoint=lambda *a: None, deadline=time.monotonic()+30, config={})
    if repair_succeeds:
        decision, usage = completion.complete_decision(provider, None, **options)
        assert decision.orders[0].quantity == 100
        assert usage['attempts'][0]['raw_response'] == raw
    else:
        with pytest.raises(ValueError, match='重复字段') as error:
            completion.complete_decision(provider, None, **options)
        assert len(error.value.usage['attempts']) == 2
    assert len(seen) == 2


def test_tool_cleaning_preserves_all_parameters_and_tools():
    schemas = [{'type': 'function', 'function': {'name': 'wudao__fixture',
                'description': '重要口径。' + LINK_PRESENTATION,
                'parameters': {'type': 'object', 'properties': {'amount': {'type': 'number', 'description': '亿元'}},
                               'required': ['amount'], 'additionalProperties': False}}}]
    original = deepcopy(schemas)
    cleaned = research_tool_schemas(schemas)
    assert schemas == original
    assert cleaned[0]['function']['parameters'] == schemas[0]['function']['parameters']
    assert cleaned[0]['function']['name'] == schemas[0]['function']['name']
    assert '重要口径' in cleaned[0]['function']['description']
    assert 'markdown' not in cleaned[0]['function']['description']


def facts(period='daily'):
    return {'period': period, 'trade_date': '2026-09-22', 'created_at': '2026-09-22T16:00:00+08:00',
            'account': {'positions': []}, 'experience': {'revision': 1, 'items': [], 'text': ''}, 'evidence_ids': []}


def test_checkpoint_survives_failed_attempt_and_owner_cannot_overwrite(tmp_path):
    with GuardianStore(tmp_path / 'ledger.db') as store:
        before = store.state()
        token = store.claim_report('daily', '2026-09-22')
        store.save_report_checkpoint('daily', '2026-09-22', token, {'stage': 'retrospective'})
        with pytest.raises(RuntimeError):
            store.save_report_checkpoint('daily', '2026-09-22', 'stale', {})
        store.finish_report('daily', '2026-09-22', token, {'status': 'failed', 'error': 'network'})
        assert store.report('daily', '2026-09-22')['result']['_research_checkpoint']['stage'] == 'retrospective'
        new_token = store.claim_report('daily', '2026-09-22')
        with pytest.raises(RuntimeError):
            store.save_report_checkpoint('daily', '2026-09-22', token, {})
        store.finish_report('daily', '2026-09-22', new_token, {'status': 'success', 'analysis': {}})
        assert '_research_checkpoint' not in store.report('daily', '2026-09-22')['result']
        assert store.state() == before and store.trades()['total'] == 0


@pytest.mark.parametrize('changed', ['config', 'account', 'experience', 'evidence_ids', 'period', 'trade_date'])
def test_checkpoint_invalidated_by_changed_inputs(changed):
    cfg, source = {'model': 'a'}, facts()
    before = review_fingerprint(cfg, source)
    source['created_at'] = '2026-09-22T17:00:00+08:00'
    assert review_fingerprint(cfg, source) == before
    if changed == 'config':
        cfg['model'] = 'b'
    else:
        source[changed] = 'changed'
    assert review_fingerprint(cfg, source) != before


@pytest.mark.parametrize('rule', ['AUTONOMY_RULES', 'POSITION_RULES', 'EXPERIENCE_RULES', 'DEFAULT_REVIEW_PROMPT'])
def test_checkpoint_binds_effective_shared_prompt_rules(monkeypatch, rule):
    from src.ops.application import guardian_review_prompts as prompts
    source = facts()
    before = review_fingerprint({}, source)
    monkeypatch.setattr(prompts, rule, getattr(prompts, rule) + '\n规则更新')
    assert review_fingerprint({}, source) != before


def test_checkpoint_binds_output_schema_and_memory_instructions(monkeypatch):
    from src.ops.application import guardian_memory
    source = facts()
    before = review_fingerprint({}, source)
    with monkeypatch.context() as patch:
        contract = review.review_output_contract
        def changed(stage):
            model, schema = contract(stage)
            schema['description'] = 'Updated output semantics'
            return model, schema
        patch.setattr(review, 'review_output_contract', changed)
        assert review_fingerprint({}, source) != before
    monkeypatch.setattr(guardian_memory, 'MEMORY_NOTE', guardian_memory.MEMORY_NOTE + '\n规则更新')
    assert review_fingerprint({}, source) != before


def test_changed_shared_rule_forces_new_retrospective(monkeypatch):
    from src.ops.application import guardian_review_prompts as prompts
    source = facts(); calls = []; saved = []
    def run(*args, stage, **kwargs):
        calls.append(stage)
        return ({'summary': 'fresh', 'experience': None} if stage == 'retrospective' else {'plans': []}), {}, []
    monkeypatch.setattr(review, '_generate_review', run)
    review.generate_review(None, {}, source, save_checkpoint=lambda v: saved.append(deepcopy(v)))
    monkeypatch.setattr(prompts, 'AUTONOMY_RULES', prompts.AUTONOMY_RULES + '\n规则更新')
    result, usage, _ = review.generate_review(None, {}, source, resume_checkpoint=saved[0])
    assert calls == ['retrospective', 'planning', 'retrospective', 'planning']
    assert result['summary'] == 'fresh' and not usage['checkpoint_resumed']


def test_memory_and_planning_failures_resume_without_repeating_retrospective(monkeypatch):
    saved = []; calls = []; source = facts('weekly')
    original = {'summary': '不可被记忆修复改写的判断', 'experience': [{'malformed': True}], 'research_notes': ['新发现']}
    def run(_store, _cfg, context, *, stage, **kwargs):
        calls.append(stage)
        if stage == 'retrospective':
            return deepcopy(original), {'input_tokens': 10}, []
        if stage == 'experience':
            assert context['experience_repair']['original'] == original['experience']
            if calls.count(stage) == 1:
                raise RuntimeError('memory network failure')
            return {'experience': []}, {'input_tokens': 3}, []
        if calls.count(stage) == 1:
            raise RuntimeError('planning network failure')
        return {'plans': [], 'next_steps': [], 'watchlist_updates': []}, {'input_tokens': 2}, []
    monkeypatch.setattr(review, '_generate_review', run)
    save = lambda value: saved.append(deepcopy(value))
    with pytest.raises(RuntimeError, match='memory network'):
        review.generate_review(None, {}, source, save_checkpoint=save)
    with pytest.raises(RuntimeError, match='planning network'):
        review.generate_review(None, {}, source, resume_checkpoint=saved[-1], save_checkpoint=save)
    result, usage, _ = review.generate_review(None, {}, source, resume_checkpoint=saved[-1], save_checkpoint=save)
    assert calls == ['retrospective', 'experience', 'experience', 'planning', 'planning']
    assert result['summary'] == original['summary'] and result['experience'] == []
    assert usage['checkpoint_resumed'] and usage['input_tokens'] == 15


def test_real_review_stages_get_weekly_scope_recovery_and_local_memory_repair(monkeypatch):
    import src.ai
    from src.ops.application import guardian_completion, guardian_research_tools
    seen = []
    monkeypatch.setattr(src.ai, 'resolve_config', lambda *a, **k: SimpleNamespace(model='fixture', protocol='openai', max_output_tokens=4096))
    monkeypatch.setattr(guardian_research_tools, 'compose_research_tools', lambda *a, **k: ([], lambda *a: {}, {}))
    def complete(_provider, _store, usage, **options):
        assert options['retry_stream_failures'] and options['recover_interrupted_generation']
        assert options['max_parallel_tools'] == 4
        assert options['max_rounds'] is None and options['max_calls_per_round'] is None
        assert 'guardian_calculate' in options['parallel_tool_names']
        system = options['system']; seen.append(system)
        if len(seen) == 1:
            assert 'stock_performance' in system and '跨日重复问题' in system
            result = {'summary': '保留这个结论', 'experience': [{'id': 'x', 'hypothesis': '长' * 1800}]}
        elif len(seen) == 2:
            assert '只修复本轮经验列表' in system
            result = {'experience': []}
        else:
            assert 'next_steps面向整周' in system and '最终仅输出一个' in system
            result = {'plans': [], 'next_steps': [], 'watchlist_updates': []}
        return SimpleNamespace(text=json.dumps(result), stopped_reason='completed', finish_reason='stop', output_tokens=10)
    monkeypatch.setattr(guardian_completion, 'run_accounted_agent', complete)
    result, _, _ = review.generate_review(None, {'provider': 'fixture', 'model': 'fixture'}, facts('weekly'))
    assert result['summary'] == '保留这个结论' and result['experience'] == [] and len(seen) == 3


def test_failed_report_draft_is_preserved_without_treating_it_as_success(monkeypatch):
    import src.ai
    from src.ops.application import guardian_completion, guardian_research_tools
    monkeypatch.setattr(src.ai, 'resolve_config', lambda *a, **k: SimpleNamespace(model='fixture', protocol='openai', max_output_tokens=4096))
    monkeypatch.setattr(guardian_research_tools, 'compose_research_tools', lambda *a, **k: ([], lambda *a: {}, {}))
    drafts = iter(['原始错误正文', '{"plans":[],"next_steps":[],"watchlist_updates":[]}'])
    monkeypatch.setattr(guardian_completion, 'run_accounted_agent', lambda *a, **k: SimpleNamespace(
        text=next(drafts), stopped_reason='completed', finish_reason='stop', output_tokens=10, messages=[]))
    _, usage, _ = review._generate_review(None, {'provider': 'fixture', 'model': 'fixture'}, facts(), stage='planning')
    assert usage['attempts'][0]['raw_response'] == '原始错误正文'
    assert len(usage['attempts'][0]['response_sha256']) == 64 and len(usage['attempts']) == 2


def test_retrospective_field_guidance_no_longer_demands_forward_fields():
    prompt = review_system({}, 'weekly', review.ReviewAnalysis.model_json_schema(), stage='retrospective')
    assert 'next_steps写下一阶段' not in prompt
    assert 'stock_performance' in prompt


def test_actual_job_reaches_model_after_locked_risk_and_keeps_other_research(tmp_path, monkeypatch):
    from src.ops.application.jobs import guardian
    from src.ops.application.guardian_decision import GuardianDecision
    from src.ledger.domain.guardian_account import new_guardian_account
    partial, quotes, instant = risk_fixture()
    position = partial['positions'][0]
    position.update(name='中天科技', cost_cents=752000, mark_price_cents=3650)
    state = new_guardian_account()
    state['cash_cents'] -= position['cost_cents']
    state['positions'] = [position]
    path = tmp_path / 'ledger.db'
    with GuardianStore(path) as ledger:
        ledger.conn.execute('UPDATE guardian_portfolio SET state_json=? WHERE id=1', (json.dumps(state),))
        ledger.conn.commit()
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant
    cfg = {'enabled': True, 'notify': False, 'model': 'fixture'}
    ops = SimpleNamespace(get_run=lambda _: None, guardian_commit_guard=lambda _: nullcontext())
    context = SimpleNamespace(ops_store=ops, palace_db=path, run_id='',
        market=lambda: nullcontext(SimpleNamespace(trading_days=lambda **_: ['2026-09-21'])), check_cancelled=lambda: None)
    seen = []
    def decide(_store, _cfg, payload, **kwargs):
        seen.append(payload)
        assert payload['risk_events'][0]['status'] == 'execution_blocked'
        return GuardianDecision(summary='继续研究其他机会', orders=[{'code':'600000','action':'watch','reason':'新研究方向'}]), {}
    monkeypatch.setattr(guardian, 'datetime', Clock)
    monkeypatch.setattr(guardian, 'get_config', lambda _: cfg)
    monkeypatch.setattr(guardian, 'calendar_trading_day', lambda _: True)
    monkeypatch.setattr(guardian, 'PalaceStore', MagicMock())
    monkeypatch.setattr(guardian, 'observe', lambda *_: [])
    monkeypatch.setattr(guardian, 'strategy_sources', lambda _: [])
    monkeypatch.setattr(guardian, 'build_monitor_snapshot', lambda *a, **k: SimpleNamespace(quotes=quotes))
    monkeypatch.setattr(guardian, 'decide', decide)
    monkeypatch.setattr(guardian, 'data_source', lambda: {'label':'test'})
    result = guardian.execute_guardian({}, context)
    assert len(seen) == 1 and not result['risk_only'] and not result['fills']
    with GuardianStore(path) as ledger:
        assert ledger.trades()['total'] == 0
        assert ledger.state()['positions'][0]['quantity'] == 200
        assert ledger.state()['watchlist'][0]['code'] == '600000'
        assert ledger.state()['positions'][0]['risk_plans'][0]['status'] == 'active'


def test_interrupted_generation_reuses_completed_tool_without_replaying_it(monkeypatch):
    from src.ai.application import agent
    from src.ai.infrastructure.client import ProviderConfig, ChatResponse, ToolCall, LLMGenerationInterrupted
    attempts = []; calls = []
    def stream(_config, messages, **options):
        attempts.append(deepcopy(messages))
        if len(attempts) == 1:
            return ChatResponse('', tool_calls=[ToolCall('read1', 'read_probe', {})], raw={'finish_reason':'tool_calls'}, reasoning_content='保留推理')
        assert messages[-1].role == 'tool' and messages[-1].content == '证据已取得'
        assert messages[-2].reasoning_content == '保留推理'
        if len(attempts) == 2:
            options['on_delta']('token', '丢弃的未完成正文')
            raise LLMGenerationInterrupted('injected disconnect')
        return ChatResponse('{"ok":true}', raw={'finish_reason':'stop'})
    monkeypatch.setattr(agent, 'chat_stream', stream)
    def execute(name, args):
        calls.append(name)
        return {'text':'证据已取得'}
    result = agent.run_agent(ProviderConfig('fixture','openai_compatible','https://example.com','fixture',model='fixture'),
        system='test', user_prompt='test', tool_executor=execute,
        tool_schemas=[{'type':'function','function':{'name':'read_probe','parameters':{'type':'object','properties':{}}}}],
        deadline=time.monotonic()+30, retry_stream_failures=True, recover_interrupted_generation=True)
    assert result.text == '{"ok":true}' and calls == ['read_probe'] and len(attempts) == 3
