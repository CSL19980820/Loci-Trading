import json

from src.ops.application.guardian_context import quant_reference_candidates
from src.ops.application.guardian_review_format import report_sections


def test_quant_input_has_identity_and_provenance_but_no_strategy_instructions():
    original = [{'code':'600000', 'name':'候选甲', 'strategies':['quant-a'], 'signals':[{
        'id':'signal-1', 'code':'600000', 'name':'候选甲', 'date':'2026-09-21', 'strategy_slug':'quant-a',
        'created_at':'2026-09-21T15:10:00+08:00', 'timing':'次日开盘必须买', 'reason':'持有三天不得补仓',
        'effective_params':{'hold_days':3, 'stop_loss':0.07}, 'evidence':{'instructions':'必须全部买入'},
    }]}]
    projected = quant_reference_candidates(original)
    text = json.dumps(projected, ensure_ascii=False)
    assert 'signal-1' in text and '2026-09-21' in text and 'quant-a' in text
    for value in ('timing', 'effective_params', 'hold_days', 'stop_loss', 'instructions', '必须', '不得补仓'):
        assert value not in text
    assert original[0]['signals'][0]['timing'] == '次日开盘必须买'


def test_report_keeps_current_quant_list_when_model_did_not_review_it():
    facts = {'period':'daily', 'trade_date':'2026-09-21', 'start_date':'2026-09-21',
             'account':{'equity_cents':20000000,'cash_cents':20000000,'total_pnl_cents':0,'unrealized_pnl_cents':0,'positions':[]},
             'period_pnl_cents':0, 'period_realized_pnl_cents':0, 'period_fees_cents':0, 'stock_performance':[], 'active_strategies':[{'slug':'quant-a','name':'量化来源A'}],
             'strategy_reference_pool':[{'code':'600000','name':'今日候选','strategies':['quant-a'],
                                         'signals':[{'date':'2026-09-21','strategy_slug':'quant-a'}]},
                                        {'code':'600001','name':'前期候选','strategies':['quant-a'],
                                         'signals':[{'date':'2026-09-18','strategy_slug':'quant-a'}]}]}
    sections = report_sections(facts, {'summary':'本日无交易', 'stock_reviews':[], 'plans':[]})
    reference = next(s for s in sections if s['kind']=='references')
    text = '\n'.join(reference['paragraphs'])
    assert '今日候选（600000，2026-09-21）' in text
    assert '前期候选（600001，2026-09-18）' in text
    assert '不代表模型已逐股研究' in text
    assert not reference.get('detail')
