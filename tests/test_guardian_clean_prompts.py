from types import SimpleNamespace

from src.ops.application import guardian_agent, guardian_config
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_context import premarket_plan_context
from src.ops.application.guardian_review_prompts import review_system
from src.ops.application.stock_agent_decision import StockAgentDecision


def test_actual_decision_prompt_is_clean_and_opening_aware(monkeypatch):
    import src.ai
    captured = {}
    monkeypatch.setattr(src.ai, 'resolve_config', lambda *_args, **_kwargs: SimpleNamespace(model='fixture', protocol='openai'))
    monkeypatch.setattr(guardian_agent, 'compose_research_tools', lambda *_args, **_kwargs: ([], lambda *_: {}, {}))

    def complete(_provider, _store, **kwargs):
        captured.update(kwargs)
        return GuardianDecision(summary='等待', orders=[]), {'tools': []}

    monkeypatch.setattr(guardian_agent, 'complete_decision', complete)
    guardian_agent.decide(None, {**guardian_config.DEFAULTS, 'provider': 'fixture', 'model': 'fixture'},
                          {'as_of': '2026-09-21T09:25:00+08:00', 'portfolio': {'positions': [], 'watchlist': []}})
    prompt = captured['system']
    for fragment in ('最多4只', '最多8只', '收盘4只', '盘中8只', '撤销旧', '替代旧', '旧数量限制已取消', 'close_keep_codes'):
        assert fragment not in prompt
    assert '竞价成交金额' in prompt
    assert 'opening_plan_reviews' in prompt
    assert 'T+1' in prompt
    assert '不设持仓只数上限' in prompt
    assert 'absolute_max' not in captured['payload']['position_policy']


def test_phase_prompts_and_legacy_schema_compatibility():
    for phase in ('premarket', 'daily', 'weekly'):
        prompt = review_system(guardian_config.DEFAULTS, phase, {})
        assert '撤销旧' not in prompt
        assert '最多4只' not in prompt
        assert '不设持仓只数上限' in prompt
    assert 'close_keep_codes' not in GuardianDecision.model_json_schema()['properties']
    # 独立智能体有自己的用户设置，不改变其契约。
    assert 'close_keep_codes' in StockAgentDecision.model_json_schema()['properties']


def test_saved_custom_prompts_are_not_overwritten():
    saved = {'prompt': '请重点研究我指定的行业。', 'common_prompt': '我的自定义偏好',
             'premarket_prompt': '我的盘前需求', 'model': 'custom'}
    store = SimpleNamespace(get_job_by_name=lambda _: {'config': saved, 'enabled': True})
    result = guardian_config.get_config(store)
    for key, value in saved.items():
        assert result[key] == value
    assert 'enabled' not in saved


def test_historical_research_is_not_rewritten_as_current_policy():
    original = {'holding_plan': '价格站上10元且已有持仓退出腾出名额时考虑买入。',
                'facts': {'reason': '当时收盘最多4只'}, 'fills': [{'quantity': 100}]}
    current = premarket_plan_context({'status':'success','result':{'analysis':original}}, {'positions':[]})
    assert current['holding_plan'] == original['holding_plan']
    assert current['facts'] == original['facts']
    assert current['fills'] == original['fills']


def test_other_agent_uses_its_own_closing_decision():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.ops.application.stock_agent_policy import closing_stock_agent_decision
    state = {'positions':[{'code':'600000','name':'甲','quantity':100}, {'code':'600001','name':'乙','quantity':100}], 'agent_close_keep_codes':['600000']}
    decision = closing_stock_agent_decision(state, datetime(2026,9,21,14,55,tzinfo=ZoneInfo('Asia/Shanghai')), {'position_limit':1})
    assert isinstance(decision, StockAgentDecision)
    assert decision.close_keep_codes == ['600000']
    assert decision.orders[0].code == '600001'
