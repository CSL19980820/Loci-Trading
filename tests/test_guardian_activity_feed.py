"""Home research projection: all stages, actual generation time and bounded read-only data."""
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger.infrastructure.guardian_queries import GuardianQueriesMixin
from src.ops.api import guardian_reads


class FeedStore(GuardianQueriesMixin):
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE guardian_cycles(slot TEXT PRIMARY KEY, started REAL, status TEXT, result_json TEXT);
            CREATE TABLE guardian_reports(report_key TEXT PRIMARY KEY, period TEXT, trade_date TEXT,
                started REAL, status TEXT, token TEXT, result_json TEXT);
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def run(self, key, started, payload=None, status='success'):
        self.conn.execute('INSERT INTO guardian_cycles VALUES(?,?,?,?)',
                          (key, started, status, json.dumps(payload or {'analysis': key})))
        self.conn.commit()

    def report(self, period, day, started, payload=None, status='success'):
        self.conn.execute('INSERT INTO guardian_reports VALUES(?,?,?,?,?,?,?)',
                          (f'{period}:{day}', period, day, started, status, 'PRIVATE-LEASE',
                           json.dumps(payload or {'analysis': {'summary': period}})))
        self.conn.commit()


@pytest.fixture
def ledger():
    store = FeedStore()
    yield store
    store.conn.close()


def test_all_stages_and_generation_time_not_subject_date(ledger):
    ledger.run('2026-09-21T14:50', 400)
    ledger.report('premarket', '2026-09-21', 300)
    ledger.report('daily', '2026-09-21', 500)
    # Old week's report regenerated last: it must appear before newer subject dates.
    ledger.report('weekly', '2026-09-11', 600)
    page = ledger.activity_feed(4)
    assert [r['period'] for r in page['reports']] == ['weekly', 'daily', 'premarket']
    assert page['runs'][0]['result']['analysis'] == '2026-09-21T14:50'
    newest = ledger.activity_feed(1)
    assert newest['reports'][0]['period'] == 'weekly' and newest['runs'] == []


def test_limit_is_applied_after_merging_sources(ledger):
    for i in range(25):
        ledger.run(f'cycle-{i:02}', 100 + i)
    ledger.report('weekly', '2026-09-18', 1)
    page = ledger.activity_feed()
    assert len(page['runs']) == 16 and not page['reports']
    assert [r['started'] for r in page['runs']] == list(range(124, 108, -1))


def test_complete_preview_and_no_private_context(ledger):
    ledger.run('cycle', 10, {'analysis': '盘中正文', 'decision_context': 'PRIVATE-CONTEXT'})
    ledger.report('daily', '2026-09-21', 11,
                  {'analysis': {'summary': '盘后摘要'}, 'body': '更长正文', 'share_token': 'PRIVATE-SHARE'})
    page = ledger.activity_feed()
    assert page['runs'][0]['result']['analysis'] == '盘中正文'
    assert page['reports'][0]['summary'] == '盘后摘要'
    assert 'PRIVATE' not in json.dumps(page)


def test_legacy_body_fallback_failure_and_bounded_text(ledger):
    ledger.run('cycle', 10, {'body': '旧版正文'})
    ledger.report('daily', '2026-09-21', 11, {'error': '模型限流'}, status='failed')
    ledger.report('weekly', '2026-09-18', 12, {'body': '长' * 20000})
    page = ledger.activity_feed()
    assert page['runs'][0]['result']['analysis'] == '旧版正文'
    assert page['reports'][1]['error'] == '模型限流'
    assert page['reports'][1]['status'] == 'failed'
    assert len(page['reports'][0]['summary']) == 12000


def test_empty_and_invalid_json_are_not_fabricated(ledger):
    assert ledger.activity_feed() == {'runs': [], 'reports': [], 'limit': 16}
    ledger.run('broken', 10)
    ledger.conn.execute("UPDATE guardian_cycles SET result_json='invalid' WHERE slot='broken'")
    ledger.conn.commit()
    assert ledger.activity_feed()['runs'][0]['result']['analysis'] == ''


def test_feed_is_read_only(ledger):
    ledger.run('cycle', 10)
    before = ledger.conn.total_changes
    writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}
    ledger.conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK)
    assert ledger.activity_feed()['runs']
    assert ledger.conn.total_changes == before


@pytest.mark.parametrize('limit', [0, -1, 51, 100000])
def test_rejects_unbounded_limit(ledger, limit):
    with pytest.raises(ValueError):
        ledger.activity_feed(limit)


def test_route_uses_activity_contract_and_validation(ledger, monkeypatch):
    ledger.run('cycle', 10)
    ledger.report('weekly', '2026-09-18', 11)
    monkeypatch.setattr(guardian_reads, 'GuardianStore', lambda: ledger)
    app = FastAPI()
    app.include_router(guardian_reads.build_guardian_reads_router(), prefix='/ops/guardian')
    with TestClient(app) as client:
        result = client.get('/ops/guardian/activity?limit=1')
        assert result.status_code == 200
        assert result.json()['reports'][0]['period'] == 'weekly'
        assert client.get('/ops/guardian/activity?limit=0').status_code == 422
        assert client.get('/ops/guardian/activity?limit=51').status_code == 422
        assert client.post('/ops/guardian/activity').status_code == 405
