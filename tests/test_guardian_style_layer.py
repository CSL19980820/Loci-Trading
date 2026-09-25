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
    assert system.index(USER_PROMPT_HEADER) < system.index(STYLE) < system.index('【账户接口】')
    assert '用户配置中的风格偏好是默认方向' in system
    assert '【盘中表达】' in system and '【盘中节奏】' in system
    # 盘中输出契约没有这些报告字段；提示词不能诱导模型输出后被extra=forbid拒绝。
    for field in ('notification_summary', 'research_notes', 'research_plan', '用户展示与研究接续'):
        assert field not in system
    assert '激进' not in system and '中小盘' not in system.replace(STYLE, '')


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
    assert '封板、盘口不足等情形下的成交只是乐观假设' in prompt
    assert '也不据此否定该方法' in prompt
    assert prompt.index(USER_PROMPT_HEADER) < prompt.index(STYLE)


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
