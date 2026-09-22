from copy import deepcopy
from src.ops.application import guardian_review_agent as agent
from src.ops.application.guardian_review_prompts import review_system
from src.ops.application.guardian_config import DEFAULTS


def test_forward_context_does_not_auto_inherit_old_strategy_trade_templates():
    facts={'period':'daily','trade_date':'2026-09-21','created_at':'2026-09-21T16:00:00+08:00',
           'account':{'positions':[]},'watchlist':[], 'strategy_reference_pool':[{'code':'600000','name':'候选','signals':[{'date':'2026-09-21'}]}],
           'previous_reviews':[{'analysis':{'plans':[{'trigger':'开盘必须买入并持有3天'}]}}],
           'cycles':[{'decisions':[{'holding_plan':'7%止损不补仓'}]}], 'experience':{'text':'历史经验'}}
    original=deepcopy(facts)
    result=agent.planning_facts(facts)
    assert 'previous_reviews' not in result and 'cycles' not in result and 'experience' not in result
    assert result['strategy_reference_pool']==facts['strategy_reference_pool']
    assert '历史' in result['history_access']
    assert facts == original


def test_fresh_plan_replaces_audit_actions_and_merges_metered_usage(monkeypatch):
    calls=[]
    def run(_store,_cfg,facts,*,stage,**kwargs):
        calls.append((stage,deepcopy(facts)))
        if stage=='retrospective':
            return {'summary':'评价已发生的交易','plans':[],'watchlist_updates':[],'next_steps':[]}, {'input_tokens':10,'output_tokens':3}, [{'id':'tool:1'}]
        return {'plans':[],'watchlist_updates':[{'code':'600000','action':'watch','reason':'等待新的证据'}],'next_steps':['自主观察']}, {'input_tokens':5,'output_tokens':2}, [{'id':'planning:tool:1'}]
    monkeypatch.setattr(agent,'_generate_review',run)
    result,usage,sources=agent.generate_review(None,{}, {'period':'daily','account':{},'previous_reviews':[{'plans':'必须买入'}]})
    assert [s for s,_ in calls]==['retrospective','planning']
    assert 'previous_reviews' not in calls[1][1]
    assert result['plans']==[] and result['watchlist_updates'][0]['action']=='watch'
    assert usage['input_tokens']==15 and usage['output_tokens']==5
    assert len(sources)==2


def test_planning_contract_allows_no_buy_and_requires_own_basis():
    schema=agent.ForwardPlan.model_json_schema()
    assert 'rationale' in schema['$defs']['ReviewPlan']['required']
    assert 'watch' in schema['$defs']['ReviewPlan']['properties']['action']['enum']
    assert agent.ForwardPlan().plans == []
    prompt=review_system(DEFAULTS,'daily',schema,stage='planning')
    assert '全部研究工具' in prompt
    assert '候选只是来源' in prompt
