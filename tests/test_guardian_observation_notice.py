from contextlib import nullcontext
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore
from src.ledger.domain.guardian_watchlist import update_watchlist
from src.ops.application.guardian_cycle_notice import observation_changes, observation_notice, publish_cycle_report
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.jobs import guardian


def test_observation_changes_only_reports_effective_actions():
    old = {'watchlist': [{'code': '600000', 'name': '浦发银行', 'added_at': '2026-09-22T10:00:00+08:00',
                          'entry_condition': '等待', 'exit_condition': '破位'}]}
    same = {'watchlist': [{**old['watchlist'][0], 'reason': '重新评价', 'updated_at': '2026-09-23T10:00:00+08:00'}]}
    assert observation_changes(old, same, '2026-09-23T10:00:00+08:00') == []
    changed = observation_changes(old, {'watchlist': [{**same['watchlist'][0], 'exit_condition': '失效'}]},
                                  '2026-09-23T10:00:00+08:00')
    assert changed[0]['action'] == 'update'
    assert '重新评价' not in observation_notice(changed)
    dismissed = observation_changes({'watchlist': []},
                                    {'watchlist': [], 'reference_dismissals': {'600001': {'at': '2026-09-23T10:00:00+08:00'}}},
                                    '2026-09-23T10:00:00+08:00',
                                    references=[{'code': '600001', 'name': '候选股'}])
    assert dismissed == [{'action': 'unwatch', 'code': '600001', 'name': '候选股',
                          'at': '2026-09-23T10:00:00+08:00'}]


@pytest.mark.parametrize('action,expected', [('watch', '移入观察'), ('unwatch', '移出观察'), ('hold', None)])
def test_five_minute_notice_tracks_committed_watchlist(tmp_path, monkeypatch, action, expected):
    instant = datetime(2026, 9, 23, 10, 0, 10, tzinfo=ZoneInfo('Asia/Shanghai'))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    path = tmp_path / 'palace.db'
    if action == 'unwatch':
        with GuardianStore(path) as ledger:
            state = ledger.state()
            update_watchlist(state, {'code': '600000', 'action': 'watch', 'reason': '旧理由'},
                             '2026-09-22T10:00:00+08:00', name='浦发银行')
            ledger.conn.execute('UPDATE guardian_portfolio SET state_json=? WHERE id=1',
                                (json.dumps(state, ensure_ascii=False),))
            ledger.conn.commit()
    cfg = {'enabled': True, 'notify': True, 'model': 'fixture'}
    store = SimpleNamespace(get_run=lambda _: None, guardian_commit_guard=lambda _: nullcontext())
    context = SimpleNamespace(ops_store=store, palace_db=path, run_id='',
                              market=lambda: nullcontext(), check_cancelled=lambda: None)
    orders = [] if action == 'hold' else [{'code': '600000', 'name': '浦发银行',
                                           'action': action, 'reason': '内部研究依据'}]
    monkeypatch.setattr(guardian, 'datetime', Clock)
    monkeypatch.setattr(guardian, 'get_config', lambda _: cfg)
    monkeypatch.setattr(guardian, 'calendar_trading_day', lambda _: True)
    monkeypatch.setattr(guardian, 'PalaceStore', MagicMock())
    monkeypatch.setattr(guardian, 'observe', lambda *_: [])
    monkeypatch.setattr(guardian, 'strategy_sources', lambda _: [])
    monkeypatch.setattr(guardian, 'decide', lambda *a, **k: (GuardianDecision(summary='本轮研判', orders=orders), {}))
    monkeypatch.setattr(guardian, 'data_source', lambda: {'label': 'fixture'})
    monkeypatch.setattr(guardian, 'deliver_pending', lambda *_: {})
    monkeypatch.setattr(guardian, 'publish_cycle_report', lambda *_: 'https://example.test/shared/reports/token')

    result = guardian.execute_guardian({}, context)
    with GuardianStore(path) as ledger:
        notices = list(ledger.conn.execute('SELECT title,body FROM guardian_notices'))
        assert len(notices) == (1 if expected else 0)
        if expected:
            assert expected in notices[0]['body']
            assert '浦发银行 600000' in notices[0]['body']
            assert '内部研究依据' not in notices[0]['body']
            assert 'https://example.test/shared/reports/token' in notices[0]['body']
            assert result['outcome'] == 'observation_changed'
            assert result['observation_changes'][0]['at'].startswith('2026-09-23T10:00:10')
        else:
            assert result['outcome'] == 'no_action'
            assert result['notify']['skipped'] == 'no_action'


def test_cycle_report_uses_public_readonly_document(monkeypatch):
    from src.ops.application import guardian_report_share

    captured = {}
    monkeypatch.setattr(guardian_report_share, 'public_report_base_url', lambda: 'https://example.test')
    monkeypatch.setattr(guardian_report_share, 'publish_document_share',
                        lambda token, identity, document: captured.update(token=token, identity=identity,
                                                                          document=document) or 'https://example.test/shared/reports/token')
    result = {'status': 'success', 'analysis': '详细研判', 'as_of': '2026-09-23T10:00:10+08:00',
              'decisions': [{'code': '600000', 'action': 'watch', 'reason': '报告里的观察依据'}],
              'stock_names': {'600000': '浦发银行'}}
    assert publish_cycle_report('2026-09-23T10:00:00+08:00', result).endswith('/token')
    assert captured['identity']['slot'] == '2026-09-23T10:00:00+08:00'
    assert any('报告里的观察依据' in str(section) for section in captured['document']['sections'])


def test_cycle_report_link_opens_only_public_content(tmp_path, monkeypatch):
    from src.ops.application import guardian_report_share

    monkeypatch.setenv('LOCI_PUBLIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(guardian_report_share, 'data_dir', lambda: tmp_path)
    result = {'status': 'success', 'analysis': '本轮观察判断', 'as_of': '2026-09-23T10:00:10+08:00',
              'decisions': [{'code': '600000', 'name': '浦发银行', 'action': 'watch', 'reason': '报告详细依据'}],
              'usage': {'provider_secret': 'SHOULD_NOT_LEAK'}}
    url = publish_cycle_report('2026-09-23T10:00:00+08:00', result)
    html = guardian_report_share.read_shared_report(url.rsplit('/', 1)[-1], root=tmp_path)
    assert '本轮观察判断' in html and '报告详细依据' in html
    assert 'SHOULD_NOT_LEAK' not in html
