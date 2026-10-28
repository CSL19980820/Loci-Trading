from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from src.ledger import GuardianStore
from src.ops.application.guardian_context import observation_snapshot, premarket_plan_context, review_memory_context
from src.ops.application.guardian_memory import current_research
from src.ops.application.guardian_research_context import ResearchContext
from src.ops.application.guardian_tool_catalog import ResearchToolCatalog


def test_no_strategy_content_or_index_is_preloaded_but_tools_can_be_discovered():
    state = {'positions': [], 'watchlist': [{'code': '600000', 'name': '自主观察'}]}
    payload = {'portfolio': state, 'candidates': [{'code': '600001', 'signals': [{'reason': '必须买入'}]}],
               'active_strategies': [{'slug': 'quant-a', 'instructions': '持有三日'}],
               'strategy_rules': ['固定止损'], 'reference_pool': ['旧目录']}
    original = deepcopy(payload)
    archive = ResearchContext()
    compact, _ = archive.compact(payload, on_demand=True)
    assert compact == {'portfolio': state}
    assert not archive.documents
    assert payload == original
    snapshot = observation_snapshot(state)
    assert snapshot['reference_pool'] == []
    assert [row['code'] for row in snapshot['watchlist']] == ['600000']
    assert snapshot['watchlist'][0]['signals'] == snapshot['watchlist'][0]['strategies'] == []
    schema = {'type': 'function', 'function': {'name': 'system__strategy_catalog',
              'description': '读取量化策略目录', 'parameters': {'type': 'object', 'properties': {}}}}
    catalog = ResearchToolCatalog('openai', [schema], lambda: None)
    assert 'system__strategy_catalog' not in catalog.loaded
    found = catalog.search({'names': ['system__strategy_catalog']})
    assert json.loads(found['text'])['loaded'][0]['name'] == 'system__strategy_catalog'
    assert 'system__strategy_catalog' in catalog.loaded


def test_reset_preserves_account_and_audit_history_and_is_idempotent(tmp_path):
    with GuardianStore(tmp_path / 'palace.db') as ledger:
        state = ledger.state()
        state['cash_cents'] -= 100000
        state['positions'] = [{'code': '600000', 'name': '持仓', 'quantity': 100,
                              'cost_cents': 100000, 'today_bought': 100,
                              'strategies': ['quant-a'], 'holding_plan': '旧研究',
                              'entry_context': {'reason': '旧策略', 'opened_at': '2026-01-01'},
                              'risk_plans': [{'id': 'active-stop', 'status': 'active'}]}]
        state['watchlist'] = [{'code': '600001', 'name': '旧观察', 'reason': '旧研究'}]
        before = deepcopy(state)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        old_report = {'created_at': past, 'analysis': {'summary': '旧策略研究'}}
        with ledger.conn:
            ledger.conn.execute('UPDATE guardian_portfolio SET state_json=?', (json.dumps(state),))
            ledger.conn.execute("INSERT INTO guardian_reports VALUES('daily:2026-01-01','daily','2026-01-01','success','',0,?)", (json.dumps(old_report),))
            ledger.conn.execute("INSERT INTO guardian_trades VALUES('trade-1','slot','600000','2026-01-01','{}')")
            ledger.conn.execute("INSERT INTO guardian_consultations VALUES('topic','旧话题','',0,0,?)", ('[{"role":"assistant","content":"旧观点"}]',))
            ledger.conn.execute("INSERT INTO guardian_consult_turns VALUES('turn','topic','旧问题','','success',0,0,'{}')")
            ledger._save_experience([{'id': 'old', 'hypothesis': '旧策略经验', 'validation_plan': '继续观察',
                                      'status': 'proposed', 'evidence_ids': []}],
                                    source_report='daily:2026-01-01', source_revision=1, day='2026-01-01', expected_revision=0)
        result = ledger.reset_research_context('independent-1')
        after = ledger.state()
        assert not result['reused']
        for key in ('cash_cents', 'realized_pnl_cents', 'fees_cents', 'initial_capital_cents'):
            assert after[key] == before[key]
        for key in ('quantity', 'cost_cents', 'today_bought', 'risk_plans'):
            assert after['positions'][0][key] == before['positions'][0][key]
        assert 'holding_plan' not in after['positions'][0] and 'strategies' not in after['positions'][0]
        assert after['positions'][0]['entry_context'] == {'opened_at': '2026-01-01'}
        assert after['watchlist'] == [] and ledger.experience()['items'] == []
        assert ledger.trades()['total'] == 1
        report = ledger.report('daily', '2026-01-01')
        assert report['result'] == old_report
        assert premarket_plan_context(report, after) is None
        assert review_memory_context([report], after, datetime.now(timezone.utc)) == []
        assert not current_research({}, after)
        assert current_research({'created_at': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}, after)
        assert ledger.conn.execute('SELECT messages_json FROM guardian_consultations').fetchone()[0] == '[]'
        assert ledger.conn.execute('SELECT count(*) FROM guardian_consult_turns').fetchone()[0] == 1
        assert ledger.conn.execute('SELECT count(*) FROM guardian_experience_versions').fetchone()[0] == 2
        assert ledger.reset_research_context('independent-1')['reused']
        assert ledger.state() == after
        with ledger.conn:
            ledger._save_experience([{'id': 'new', 'hypothesis': '新的独立研究', 'validation_plan': '核对新数据',
                                      'status': 'proposed', 'evidence_ids': []}],
                                    source_report='daily:new', source_revision=1,
                                    day=ledger.experience()['trade_date'], expected_revision=2)
        assert ledger.experience()['items'][0]['id'] == 'new'


@pytest.mark.parametrize('table,values', [
    ('guardian_cycles', "('slot',0,'running','{}')"),
    ('guardian_reports', "('daily:day','daily','day','running','token',0,'{}')"),
    ('guardian_consult_turns', "('turn','topic','question','','queued',0,0,'{}')"),
])
def test_reset_refuses_active_work_without_partial_changes(tmp_path, table, values):
    with GuardianStore(tmp_path / 'palace.db') as ledger:
        original = ledger.state()
        with ledger.conn:
            ledger.conn.execute(f'INSERT INTO {table} VALUES {values}')
        with pytest.raises(ValueError, match='运行中'):
            ledger.reset_research_context('blocked')
        assert ledger.state() == original
        assert ledger.experience()['revision'] == 0
