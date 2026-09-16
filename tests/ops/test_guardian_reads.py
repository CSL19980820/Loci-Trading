"""Bounded UI reads must not bound the trading agent's evidence or alter the account."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import GuardianStore
from src.ops.api.guardian import build_guardian_router
from src.shared.tenancy import tenant_scope


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr('src.ops.application.notify_calendar.notification_silence_reason', lambda: '')
    app = FastAPI()
    app.include_router(build_guardian_router(write_dependency=lambda: None))
    with TestClient(app) as value:
        yield value


def seed(day, count=25):
    # Large private evidence is intentionally retained in storage, never in list payloads.
    result = json.dumps({'analysis': '显示完整研判', 'body': '报告正文', 'outcome': 'no_action',
                         'decision_context': {'private_evidence': 'EVIDENCE_ONLY' * 10000},
                         'usage': {'private_accounting': 'INTERNAL_ONLY'},
                         'notify': {'success': True, 'targets': ['PRIVATE_TARGET']}})
    with GuardianStore() as store, store.conn:
        for i in range(count):
            slot = f'{day}T10:{i:02d}:00+08:00'
            store.conn.execute('INSERT INTO guardian_cycles VALUES(?,?,?,?)', (slot, i, 'success', result))
            trade = {'name': '测试股票', 'code': '600001', 'side': 'buy', 'quantity': 100,
                     'realized_pnl_cents': i, 'fees_cents': 26, 'occurred_at': slot}
            store.conn.execute('INSERT INTO guardian_trades VALUES(?,?,?,?,?)',
                               (f'{day}-{i:03d}', slot, '600001', slot, json.dumps(trade)))
        for period in ('premarket', 'daily', 'weekly'):
            payload = {'body': '报告正文', 'analysis': {'summary': '报告摘要'},
                       'tool_evidence': {'private_evidence': 'EVIDENCE_ONLY' * 10000},
                       'notify': {'success': True, 'targets': ['PRIVATE_TARGET']}}
            store.conn.execute('INSERT INTO guardian_reports VALUES(?,?,?,?,?,?,?)',
                               (f'{period}:{day}', period, day, 'success', 'PRIVATE_TOKEN', 1, json.dumps(payload)))


def test_overview_never_reads_history_or_research(client, monkeypatch):
    seed('2026-01-01', 2)
    def forbidden(*args, **kwargs):
        pytest.fail('overview must not perform an expensive history/research read')
    for method in ('recent', 'reports', 'trades', 'performance', 'cycle_page', 'report_page'):
        monkeypatch.setattr(GuardianStore, method, forbidden)
    monkeypatch.setattr('src.ops.api.guardian_reads.observation_snapshot', forbidden)
    response = client.get('/api/ops/guardian')
    assert response.status_code == 200
    data = response.json()
    assert len(response.content) < 30000
    assert data['runs'][0]['result'] == {}
    assert not ({'reports', 'trades', 'performance', 'watchlist', 'active_strategies'} & data.keys())
    assert 'EVIDENCE_ONLY' not in response.text


@pytest.mark.parametrize(('endpoint', 'expected'), [('runs', 20), ('trades', 20), ('reviews', 3)])
def test_default_is_shanghai_today_and_bounded(client, endpoint, expected):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    seed(today.isoformat()); seed((today - timedelta(days=1)).isoformat())
    response = client.get(f'/api/ops/guardian/{endpoint}')
    assert response.status_code == 200
    data = response.json()
    assert data['start'] == data['end'] == today.isoformat()
    assert data['limit'] == 20 and data['offset'] == 0
    assert len(data['items']) == expected
    assert data['total'] == (3 if endpoint == 'reviews' else 25)
    assert 'EVIDENCE_ONLY' not in response.text and 'PRIVATE_TARGET' not in response.text
    assert len(response.content) < 30000


@pytest.mark.parametrize('endpoint,key', [('runs', 'slot'), ('trades', 'id'), ('reviews', 'report_key')])
def test_historical_queries_page_in_sql_without_overlap(client, endpoint, key):
    seed('2026-01-01'); seed('2026-01-02'); seed('2026-01-03')
    args = {'start': '2026-01-01', 'end': '2026-01-02', 'limit': 2}
    first = client.get(f'/api/ops/guardian/{endpoint}', params=args).json()
    second = client.get(f'/api/ops/guardian/{endpoint}', params={**args, 'offset': 2}).json()
    assert len(first['items']) == len(second['items']) == 2
    assert first['total'] == second['total'] == (6 if endpoint == 'reviews' else 50)
    assert not ({r[key] for r in first['items']} & {r[key] for r in second['items']})
    assert '2026-01-03' not in json.dumps(first)
    with GuardianStore() as store:
        assert len(store.recent(100)) == 75  # engine history is NOT silently narrowed
        assert len(store.reports()) == 9


@pytest.mark.parametrize('endpoint', ['runs', 'trades', 'reviews'])
@pytest.mark.parametrize('args', [
    {'limit': 0}, {'limit': 201}, {'offset': -1}, {'start': 'invalid'},
    {'start': '2026-02-01', 'end': '2026-01-01'}, {'end': '9999-12-31'},
])
def test_invalid_query_is_rejected(client, endpoint, args):
    assert client.get(f'/api/ops/guardian/{endpoint}', params=args).status_code == 422


def test_single_day_and_empty_history_do_not_fallback_to_other_days(client):
    seed('2026-01-01')
    assert client.get('/api/ops/guardian/runs', params={'start': '2026-01-02'}).json()['items'] == []
    selected = client.get('/api/ops/guardian/runs', params={'end': '2026-01-01', 'limit': 1}).json()
    assert selected['start'] == selected['end'] == '2026-01-01'
    assert len(selected['items']) == 1


def test_details_keep_visible_text_but_not_internal_evidence(client):
    seed('2026-01-01', 1)
    cycle = client.get('/api/ops/guardian/runs/2026-01-01T10:00:00%2B08:00')
    report = client.get('/api/ops/guardian/reviews/daily/2026-01-01')
    assert cycle.status_code == report.status_code == 200
    for response in (cycle, report):
        assert response.json()['result']['body'] == '报告正文'
        for secret in ('EVIDENCE_ONLY', 'PRIVATE_TOKEN', 'PRIVATE_TARGET', 'INTERNAL_ONLY'):
            assert secret not in response.text
    with GuardianStore() as store:
        assert 'EVIDENCE_ONLY' in json.dumps(store.recent()[0])
        assert 'EVIDENCE_ONLY' in json.dumps(store.report('daily', '2026-01-01'))
    assert client.get('/api/ops/guardian/runs/missing').status_code == 404


def test_performance_remains_cumulative_and_read_only(client):
    seed('2026-01-01', 2); seed('2026-01-02', 3)
    with GuardianStore() as store:
        before = store.state()
        expected = store.performance()
    result = client.get('/api/ops/guardian/performance', params={'limit': 1}).json()
    assert result['items'] == expected and result['total'] == 1
    assert result['items'][0]['trade_count'] == 5
    with GuardianStore() as store:
        assert store.state() == before


def test_existing_account_read_does_not_take_a_write_lock(tmp_path):
    path = tmp_path / 'read-lock-test.db'
    with GuardianStore(path) as writer:
        writer.conn.execute('PRAGMA journal_mode=WAL')
        writer.conn.execute('BEGIN IMMEDIATE')
        try:
            # An unnecessary BEGIN IMMEDIATE would now wait 15s and fail.
            with GuardianStore(path) as reader:
                assert reader.state()['initial_capital_cents'] == 20000000
        finally:
            writer.conn.rollback()


def test_read_models_resolve_current_tenant(monkeypatch):
    monkeypatch.delenv('PALACE_DB', raising=False)
    with tenant_scope('guardian_ui_a'):
        seed('2026-01-01', 1)
    with tenant_scope('guardian_ui_b'), GuardianStore() as store:
        assert store.cycle_page(start='2026-01-01', end='2026-01-01', limit=20, offset=0)['total'] == 0
    with tenant_scope('guardian_ui_a'), GuardianStore() as store:
        assert store.cycle_page(start='2026-01-01', end='2026-01-01', limit=20, offset=0)['total'] == 1
