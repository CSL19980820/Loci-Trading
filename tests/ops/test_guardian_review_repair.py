"""报告截断恢复必须保留事实、无工具副作用，并拒绝半成品和虚构证据。"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai import ProviderConfig
from src.ai.application.agent import AgentResult
from src.ops.application.guardian_review_agent import generate_review


@pytest.fixture
def setup_review(monkeypatch):
    provider = ProviderConfig('test', 'openai_compatible', 'https://example.invalid', 'test', 'model',
                              context_window=1000000, max_output_tokens=328000)
    monkeypatch.setattr('src.ai.resolve_config', lambda *a, **kw: provider)
    billing = Mock()
    monkeypatch.setattr('src.ai.record_llm_usage', billing)
    tool = Mock(return_value={'text': '已核实事实'})
    monkeypatch.setattr('src.ops.application.guardian_review_agent.agent_tools',
                        lambda *a, **kw: ([{'type': 'function', 'function': {'name': 'kline'}}], tool, {}))
    facts = {'trade_date': '2026-09-15', 'created_at': '2026-09-15T08:50:00+08:00',
             'evidence_ids': ['trade:1'], 'positions': [{'code': '002349', 'quantity': 4500}]}
    return provider, billing, tool, facts


def call_review(facts):
    return generate_review(SimpleNamespace(db_path='isolated'), {'provider': 'test', 'model': 'model'}, facts)


def completed(text='{"summary":"完整判断","plans":[]}', **kwargs):
    return AgentResult(text=text, rounds=1, model='model', input_tokens=10, output_tokens=20, **kwargs)


@pytest.mark.parametrize('reason,text', [
    ('length', '{"summary":"截断'),
    ('max_tokens', '{"summary":"看似闭合，但上游截断"}'),
    ('stop', '{"summary":"未闭合'),
    ('stop', '{"summary":"完整","plans":[{"code":"bad"}]}'),
])
def test_repair_preserves_context_and_has_no_tools(setup_review, monkeypatch, reason, text):
    provider, billing, tool, facts = setup_review
    initial = completed(text, finish_reason=reason,
                        messages=[{'role': 'user', 'content': json.dumps(facts)},
                                  {'role': 'assistant', 'content': text, 'reasoning_content': '原始推理'}])
    run = Mock(side_effect=[initial, completed(finish_reason='stop')])
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    analysis, usage, sources = call_review(facts)
    assert analysis['summary'] == '完整判断'
    assert usage['input_tokens'] == 20 and usage['output_tokens'] == 40
    assert usage['attempts'][0]['finish_reason'] == reason
    assert 'error' in usage['attempts'][0]
    assert billing.call_count == 2 and not sources
    repair = run.call_args_list[1].kwargs
    assert not repair.get('tool_schemas') and not repair.get('tool_executor')
    assert repair['max_calls_per_round'] == 0
    assert repair['messages'][0].content == json.dumps(facts)
    assert repair['messages'][1].reasoning_content == '原始推理'
    assert all(c.kwargs['max_tokens'] == provider.max_output_tokens for c in run.call_args_list)
    tool.assert_not_called()


def test_missing_transcript_preserves_facts_and_invalid_answer(setup_review, monkeypatch):
    _, _, _, facts = setup_review
    run = Mock(side_effect=[completed('{"summary":"截断'), completed()])
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    call_review(facts)
    messages = run.call_args_list[1].kwargs['messages']
    assert '002349' in messages[0].content
    assert messages[1].content == '{"summary":"截断'


def test_repair_failure_retains_diagnostics_and_never_returns_partial(setup_review, monkeypatch):
    _, billing, _, facts = setup_review
    run = Mock(side_effect=[completed('{"summary":"截断', finish_reason='length'),
                            completed('{"summary":"完整","lessons":[{"hypothesis":"假设","evidence_ids":["fake"],"validation_plan":"核验"}]}')])
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    with pytest.raises(ValueError, match='不存在的证据') as error:
        call_review(facts)
    assert len(error.value.usage['attempts']) == 2
    assert error.value.usage['output_tokens'] == 40
    assert run.call_count == billing.call_count == 2


def test_tool_evidence_remains_valid_after_repair(setup_review, monkeypatch):
    _, _, tool, facts = setup_review
    runs = []
    def run(provider, **kw):
        runs.append(kw)
        if len(runs) == 1:
            kw['tool_executor']('kline', {'code': '002349'})
            return completed('{"summary":"截断')
        return completed('{"summary":"完整","lessons":[{"hypothesis":"假设","evidence_ids":["tool:1"],"validation_plan":"核验"}]}')
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    analysis, _, sources = call_review(facts)
    assert analysis['lessons'][0]['evidence_ids'] == ['tool:1']
    assert sources[0]['id'] == 'tool:1'
    tool.assert_called_once()


@pytest.mark.parametrize('reason', ['max_rounds', 'llm_error: disconnected'])
def test_incomplete_research_does_not_attempt_format_repair(setup_review, monkeypatch, reason):
    _, _, _, facts = setup_review
    run = Mock(return_value=completed(stopped_reason=reason))
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    with pytest.raises(ValueError, match='未完成'):
        call_review(facts)
    run.assert_called_once()


def test_complete_report_does_not_retry(setup_review, monkeypatch):
    provider, billing, _, facts = setup_review
    provider.max_output_tokens = 16000
    run = Mock(return_value=completed(finish_reason='stop'))
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    analysis, _, _ = call_review(facts)
    assert analysis['summary'] == '完整判断'
    assert run.call_args.kwargs['max_tokens'] == 16000
    run.assert_called_once()
    billing.assert_called_once()


def test_report_research_retains_model_capacity_thinking_and_tool_access(setup_review, monkeypatch):
    _, _, _, facts = setup_review
    run = Mock(return_value=completed(finish_reason='stop'))
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    generate_review(SimpleNamespace(db_path='isolated'),
                    {'provider':'test','model':'model','thinking':'high'}, facts)
    options = run.call_args.kwargs
    assert options['max_rounds'] is None and options['max_calls_per_round'] is None
    assert options['thinking'] == 'high' and options['deadline'] > 0
    assert options['check_cancelled']
    names = {(s.get('function') or s)['name'] for s in options['tool_schemas']}
    assert 'system__web_search' in names and 'guardian_calculate' in names


def test_report_can_cover_more_than_twenty_stocks():
    from src.ops.application.guardian_review_agent import ReviewAnalysis
    data = {'summary':'complete', 'stock_reviews':[
        {'code':f'{600000+i}', 'assessment':'independent evidence'} for i in range(30)]}
    assert len(ReviewAnalysis.model_validate(data).stock_reviews) == 30


def test_failed_tool_receipt_cannot_support_a_lesson(setup_review, monkeypatch):
    _, _, tool, facts = setup_review
    tool.return_value = {'is_error':True,'text':'not obtained'}
    def run(provider, **options):
        if options.get('tool_executor'):
            options['tool_executor']('kline', {'code':'002349'})
        return completed(json.dumps({'summary':'complete', 'lessons':[{'hypothesis':'unverified',
            'evidence_ids':['tool:1'],'validation_plan':'check'}]}), finish_reason='stop')
    monkeypatch.setattr('src.ai.application.agent.run_agent', run)
    with pytest.raises(ValueError, match='不存在的证据'):
        call_review(facts)
