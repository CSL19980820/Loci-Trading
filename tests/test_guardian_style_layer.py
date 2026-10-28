"""风格层：用户风格到达各阶段，系统规则不夹带具体风格或倾向，且不收紧交易能力。"""
import json
from types import SimpleNamespace

import pytest

from src.ops.application import guardian_agent, guardian_completion, guardian_config
from src.ops.application.guardian_config import (
    DEFAULTS, DEFAULT_PREMARKET_PROMPT, DEFAULT_PROMPT, DEFAULT_REVIEW_PROMPT, USER_PROMPT_HEADER,
)
from src.ops.application.guardian_contract import GUARDIAN_EXECUTION_RULES
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_research_context import ResearchContext
from src.ops.application.guardian_review_prompts import review_system, stage_prompt
from src.ops.application.guardian_weekly_prompt import DEFAULT_WEEKLY_PROMPT
from src.ops.application.report_writing import INTRADAY_WRITING_VERSION, REPORT_WRITING_VERSION

STYLE = '偏好中小盘趋势股'


def intraday_system(monkeypatch, cfg):
    import src.ai
    captured = {}
    monkeypatch.setattr(src.ai, 'resolve_config', lambda *_a, **_k: SimpleNamespace(model='fixture', protocol='openai'))
    monkeypatch.setattr(guardian_agent, 'compose_research_tools', lambda *_a, **_k: ([], lambda *_: {}, {}))

    def complete(_provider, _store, **kwargs):
        captured.update(kwargs)
        return GuardianDecision(summary='等待', orders=[]), {'tools': []}

    monkeypatch.setattr(guardian_agent, 'complete_decision', complete)
    guardian_agent.decide(None, {**DEFAULTS, 'model': 'fixture', **cfg},
                          {'as_of': '2026-09-24T10:00:00+08:00', 'portfolio': {'positions': [], 'watchlist': []}})
    return captured['system']


def test_intraday_prompt_labels_user_style_and_uses_only_intraday_writing(monkeypatch):
    system = intraday_system(monkeypatch, {'common_prompt': STYLE})
    assert system.index(USER_PROMPT_HEADER) < system.index(STYLE) < system.index('【实际加载的默认交易技能：trading-operations】')
    assert '用户配置中的风格偏好是默认方向' in system
    assert '【盘中表达】' in system and '【盘中节奏】' in system
    assert 'summary固定三行' in system
    assert '动作：' in system and '依据：' in system and '下一步：' in system
    assert '主因：' in system and '证据：最多两个关键证据' in system and '风险：' in system
    assert '40—90' in system and '40—100' in system and '20—80' in system
    # 盘中输出契约没有这些报告字段；提示词不能诱导模型输出后被extra=forbid拒绝。
    for field in ('notification_summary', 'research_notes', 'research_plan', '用户展示与研究接续'):
        assert field not in system
    assert '激进' not in system and '中小盘' not in system.replace(STYLE, '')


@pytest.mark.parametrize('kind', ['falcon', 'leader', 'custom'])
@pytest.mark.parametrize('phase', ['research', 'premarket', 'auction', 'intraday', 'closeout', 'review', 'weekly_review'])
def test_stock_agent_actual_call_uses_phase_format_without_expanding_field_or_scope(monkeypatch, kind, phase):
    from src.ops.application import stock_agent_decide as module
    captured = {}
    source_options = {}
    monkeypatch.setattr(module, 'resolve_config', lambda *_a, **_k: SimpleNamespace(model='fixture', protocol='openai'))

    def sources(*_args, **kwargs):
        source_options.update(kwargs)
        return [], lambda *_: {}, {}

    def complete(*_args, **kwargs):
        captured.update(kwargs)
        return kwargs['decision_parser']('{"summary":"记录本轮判断","orders":[]}'), {'context_documents': {}}

    monkeypatch.setattr(module, 'stock_agent_tools', sources)
    monkeypatch.setattr(module, 'complete_decision', complete)
    config = {'kind': kind, 'provider': 'fixture', 'model': 'fixture', 'common_prompt': STYLE,
              'prompt': '我的阶段任务', 'daily_selection_limit': 0, 'watch_limit': 0,
              'position_limit': 0, 'temporary_position_limit': 0, 'max_position_pct': 100}
    payload = {'phase': phase, 'as_of': '2026-10-14T10:05:00+08:00',
               'portfolio': {'positions': [], 'watchlist': []},
               'candidate_scope': {'candidate_codes': [], 'research_codes': []}}
    _, usage = module.decide_stock_agent(None, {'config': config}, payload, palace_path='unused',
                                         checkpoint=lambda *_: None, deadline=10**20)
    system = captured['system']
    is_intraday = phase in {'auction', 'intraday', 'closeout'}
    assert ('summary固定三行' in system) is is_intraday
    assert ('【用户展示与研究接续】' in system) is not is_intraday
    assert usage['report_writing_version'] == (INTRADAY_WRITING_VERSION if is_intraday else REPORT_WRITING_VERSION)
    assert 'summary使用中文两句' not in system
    assert '字段与来源范围契约继续保留' in system
    assert '"assessments"' in system and '"research_plan_structured"' in system
    assert captured['payload']['execution_policy']['mode'] == ('paper_quote' if kind == 'falcon' else 'order_book')
    assert source_options['payload']['phase'] == phase
    if kind == 'leader' and is_intraday:
        assert '不新开仓或加仓' in system and '不增删或替换观察池' in system
    if kind == 'falcon':
        assert '新买入/加仓/新增观察仅限candidate_codes' in system


def test_system_rules_carry_no_built_in_style():
    assert '中小盘' not in guardian_config.AUTONOMY_RULES
    assert '激进' not in GUARDIAN_EXECUTION_RULES
    for phase in ('premarket', 'daily', 'weekly'):
        prompt = review_system(DEFAULTS, phase, {})
        assert '中小盘' not in prompt and '09:25开始竞价研判' not in prompt


@pytest.mark.parametrize('period, field, builtin', [
    ('premarket', 'premarket_prompt', DEFAULT_PREMARKET_PROMPT),
    ('daily', 'review_prompt', DEFAULT_REVIEW_PROMPT),
])
def test_blank_stage_follows_custom_intraday_or_builtin_stage(period, field, builtin):
    assert stage_prompt({**DEFAULTS, field: '', 'prompt': '我的盘中方法'}, period) == ('我的盘中方法', True)
    assert stage_prompt({**DEFAULTS, field: '', 'prompt': DEFAULT_PROMPT}, period) == (builtin, False)
    assert stage_prompt({**DEFAULTS, field: '  我的阶段要求 ', 'prompt': '我的盘中方法'}, period) == ('我的阶段要求', True)
    prompt = review_system({**DEFAULTS, field: '', 'prompt': '我的盘中方法'}, period, {})
    assert '我的盘中方法' in prompt and builtin not in prompt


def test_weekly_never_inherits_intraday_or_daily():
    cfg = {**DEFAULTS, 'weekly_prompt': '', 'prompt': '我的盘中方法', 'review_prompt': '我的日复盘'}
    assert stage_prompt(cfg, 'weekly') == (DEFAULT_WEEKLY_PROMPT, False)


@pytest.mark.parametrize('period, field', [('daily', 'review_prompt'), ('weekly', 'weekly_prompt')])
def test_planning_stage_receives_common_style_and_custom_stage_prompt(period, field):
    custom = review_system({**DEFAULTS, 'common_prompt': STYLE, field: '下周偏进攻，集中在主线'}, period, {}, stage='planning')
    assert custom.index(USER_PROMPT_HEADER) < custom.index(STYLE) < custom.index('下周偏进攻，集中在主线')
    builtin = review_system({**DEFAULTS, 'common_prompt': STYLE}, period, {}, stage='planning')
    assert STYLE in builtin
    assert DEFAULT_REVIEW_PROMPT not in builtin and DEFAULT_WEEKLY_PROMPT not in builtin
    bare = review_system(DEFAULTS, period, {}, stage='planning')
    assert USER_PROMPT_HEADER not in bare


@pytest.mark.parametrize('period, stage', [('premarket', 'report'), ('daily', 'retrospective'), ('weekly', 'retrospective')])
def test_reviews_label_price_proxy_fills_without_judging_the_method(period, stage):
    prompt = review_system({**DEFAULTS, 'common_prompt': STYLE}, period, {}, stage=stage)
    assert '当时未核验盘口的行情价模拟属于价格代理和流动性假设' in prompt
    assert '当前买入与加仓仍受可靠当日涨停参考等执行门禁约束' in prompt
    assert '不能用当前规则倒推历史成交违规' in prompt
    assert '不能据旧口径模拟收益把封板买入写成已验证优势' in prompt
    assert prompt.index(USER_PROMPT_HEADER) < prompt.index(STYLE)


@pytest.mark.parametrize('period, stage', [('premarket', 'report'), ('daily', 'retrospective'), ('weekly', 'planning')])
def test_review_actual_call_keeps_report_fields_and_short_records(tmp_path, monkeypatch, period, stage):
    import src.ai
    from src.ops.application import guardian_research_tools, guardian_review_agent
    captured = {}
    monkeypatch.setattr(src.ai, 'resolve_config', lambda *_a, **_k: SimpleNamespace(
        model='fixture', protocol='openai', max_output_tokens=4096))
    source_options = {}

    def sources(*_args, **kwargs):
        source_options.update(kwargs)
        return [], lambda *_a: {}, {}

    def run(*_args, **kwargs):
        captured.update(kwargs)
        body = {'plans': [], 'next_steps': [], 'watchlist_updates': []} if stage == 'planning' else {
            'summary': '一句复核结论', 'experience': None}
        return SimpleNamespace(text=json.dumps(body), stopped_reason='completed', finish_reason='stop', output_tokens=10)

    monkeypatch.setattr(guardian_research_tools, 'compose_research_tools', sources)
    monkeypatch.setattr(guardian_completion, 'run_accounted_agent', run)
    facts = {'period': period, 'trade_date': '2026-10-14', 'created_at': '2026-10-14T16:00:00+08:00',
             'account': {'positions': []}, 'experience': {'revision': 1, 'items': [], 'text': ''}, 'evidence_ids': [],
             'current_position_policy': {'buyable_boards': ['沪深主板', '创业板']}}
    if stage == 'planning':
        facts = guardian_review_agent.planning_facts(facts)
    guardian_review_agent._generate_review(None, {'provider': 'fixture', 'model': 'fixture'}, facts,
                                           stage=stage, palace_path=str(tmp_path / 'palace.db'))
    system = captured['system']
    assert 'summary只写一句全局结论' in system
    assert '逐项rationale、assessment、评语和研究记录各用一至两句' in system
    assert 'summary固定三行' not in system
    assert '不套用摘要字数目标' not in system and '重要事项多时可超出' not in system
    assert source_options['read_only'] is True and '"analysis_only": true' in system


def test_brief_targets_preserve_legal_order_and_complete_conditions():
    from src.ops.application.guardian_decision import parse_decision
    reason = '主因：证据支持参与；证据：本轮独立核验；风险：保留完整风险说明。' * 8
    condition = '价格与承接条件满足后复核，失效则撤回，不增加额外交易权限。' * 5
    value = {'summary': '动作：拟买入\n依据：条件已核验\n下一步：检查实际成交回执', 'orders': [
        {'code': '600000', 'action': 'buy', 'quantity': 100, 'reason': reason,
         'entry_condition': condition, 'holding_plan': condition,
         'execution': {'kind': 'limit', 'max_price': 10, 'reference_price': 10,
                       'valid_until': '2026-10-14T10:10:00+08:00'}}]}
    decision = parse_decision(json.dumps(value), require_execution_terms=True)
    order = decision.orders[0]
    assert order.reason == reason and order.entry_condition == condition and order.holding_plan == condition
    assert order.quantity == 100 and order.execution.max_price == 10


def test_intraday_context_shows_premarket_conclusion_inline():
    plan = {'summary': '今日偏防守，只做主线回踩', 'next_steps': ['观察甲股回踩承接'],
            'plans': [{'code': '600000', 'action': 'buy', 'trigger': '回踩10元企稳'}]}
    compact, _ = ResearchContext().compact({'preopen_plan': plan, 'candidates': []}, on_demand=True)
    view = compact['preopen_plan']
    assert view['summary'] == plan['summary'] and view['next_steps'] == plan['next_steps']
    assert view['plans_index'] == [{'code': '600000', 'action': 'buy'}]
    assert 'trigger' not in json.dumps(view, ensure_ascii=False)  # 完整条件仍在source中按需读取


def test_format_repair_keeps_original_trading_intent(monkeypatch):
    calls = []
    good = json.dumps({'summary': '拟买入', 'orders': []}, ensure_ascii=False)

    def run(_provider, _store, _usage, **arguments):
        calls.append(arguments)
        text = '{"summary": "拟买入", "notification_summary": "多余", "orders": []}' if len(calls) == 1 else good
        return SimpleNamespace(text=text, finish_reason='stop', stopped_reason='completed', messages=[],
                               input_tokens=0, output_tokens=0, rounds=1, invocations=[], model='fixture')

    monkeypatch.setattr(guardian_completion, 'run_accounted_agent', run)
    provider = SimpleNamespace(model='fixture', context_window=1, max_output_tokens=1)
    guardian_completion.complete_decision(provider, None, system='s', payload={}, schemas=[], execute=None,
        archive=ResearchContext(), checkpoint=lambda *_: None, deadline=0, config={})
    repair = calls[1]['messages'][-1].content
    assert '按原判断补全价格授权与有效期' in repair
    assert '只有你判断条件确实不成立或无法确认时才改为hold/watch' in repair
