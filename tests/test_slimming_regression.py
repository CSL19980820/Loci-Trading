"""Slim profile: exact feature retirement, source limits and bounded home projection."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

from src.ledger.infrastructure.agent_activity import read_agent_activity
from src.market.infrastructure.adapters import registry
from src.market.infrastructure import http_client
from src.ops import OpsStore
from src.ops.infrastructure.store_schema import RETIRED_OPS_TABLES


def test_registry_has_only_retained_adapters():
    registry.reset_registry()
    assert {a.meta.id for a in registry.all_adapters()} == {'tdx', 'sina', 'exchange_list'}
    assert registry.enabled_adapter_ids('adjust_factor', config={}) == ['sina']
    assert registry.enabled_adapter_ids('instruments', config={}) == ['exchange_list']
    for lane in ('hist_daily', 'spot_batch', 'minute_bars'):
        assert len(registry.enabled_adapter_ids(lane, config={})) <= 2
    for removed in ('eastmoney', 'baostock', 'tencent', 'hithink', 'wudao'):
        with pytest.raises(KeyError):
            registry.get_adapter(removed)


def test_retirement_is_tenant_local_idempotent_and_keeps_core(tmp_path):
    untouched = tmp_path/'palace.db'
    untouched.write_bytes(b'core ledger sentinel')
    paths = [tmp_path/'ops.db', tmp_path/'tenants'/'example'/'ops.db']
    for path in paths:
        with OpsStore(path) as store:
            keep = store.create_job(name='retained-screen', kind='screen', config={'strategy': 'original'})
            for name in RETIRED_OPS_TABLES:
                store.conn.execute(f'CREATE TABLE "{name}" (id TEXT PRIMARY KEY, payload TEXT)')
                store.conn.execute(f'INSERT INTO "{name}" VALUES (?,?)', ('old', 'retired-only'))
            store.conn.execute("INSERT INTO jobs(id,name,kind,created_at,updated_at) VALUES ('retired','old-cabin','paper_eod','old','old')")
            store.conn.execute("INSERT INTO job_runs(id,job_id,kind,status,started_at) VALUES ('retired-run','retired','paper_eod','success','old')")
            store.conn.commit()
        with OpsStore(path) as store:
            tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert not set(RETIRED_OPS_TABLES) & tables
            assert store.get_job(keep)['config'] == {'strategy': 'original'}
            assert store.get_job('retired') is None
            assert store.conn.execute("SELECT COUNT(*) FROM job_runs WHERE id='retired-run'").fetchone()[0] == 0
        with OpsStore(path) as store:
            assert store.conn.total_changes == 0
            assert store.get_job(keep)['kind'] == 'screen'
    assert untouched.read_bytes() == b'core ledger sentinel'


def test_http_pool_reuses_only_same_thread_host_and_credentials(monkeypatch):
    http_client.close_thread_sessions()
    created = []
    def session():
        result = Mock()
        result.cookies = Mock()
        created.append(result)
        return result
    monkeypatch.setattr(http_client, 'market_session', session)
    http_client.market_get('https://example.invalid/a', headers={'Authorization': 'first'})
    http_client.market_get('https://example.invalid/b', headers={'Authorization': 'first'})
    assert len(created) == 1 and created[0].get.call_count == 2
    http_client.market_get('https://example.invalid/a', headers={'Authorization': 'second'})
    assert len(created) == 2
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(http_client.market_get, 'https://example.invalid/a', headers={'Authorization': 'first'}).result()
    assert len(created) == 3
    http_client.close_thread_sessions()
    assert created[0].close.called and created[1].close.called


def _activity_db(path: Path):
    conn = sqlite3.connect(path)
    conn.executescript('''
    CREATE TABLE guardian_cycles(slot TEXT PRIMARY KEY,started REAL,status TEXT,result_json TEXT);
    CREATE TABLE guardian_reports(report_key TEXT PRIMARY KEY,started REAL,status TEXT,period TEXT,result_json TEXT);
    CREATE TABLE stock_agent_profiles(id TEXT PRIMARY KEY,archived INTEGER,config_json TEXT);
    CREATE TABLE stock_agent_runs(id TEXT PRIMARY KEY,agent_id TEXT,started_at TEXT,finished_at TEXT,phase TEXT,status TEXT,summary TEXT,private_context TEXT);
    ''')
    return conn


def test_home_feed_exact_top_n_without_private_payloads_or_writes(tmp_path):
    path = tmp_path/'palace.db'
    with closing(_activity_db(path)) as conn, conn:
        conn.execute("INSERT INTO guardian_cycles VALUES (?,?,?,?)", ('cycle', 2000000030, 'success', json.dumps({'analysis': {'summary': 'cycle'}, 'secret': 'MUST_NOT_LEAK'})))
        conn.execute("INSERT INTO guardian_reports VALUES (?,?,?,?,?)", ('report', 2000000031, 'success', 'daily', json.dumps({'summary': 'report'})))
        for i in range(24):
            agent = f'agent-{i:02}'
            conn.execute('INSERT INTO stock_agent_profiles VALUES (?,?,?)', (agent, 0, json.dumps({'name': agent, 'secret': 'MUST_NOT_LEAK'})))
            # All records share a timezone representation with strict lexical ordering.
            conn.execute('INSERT INTO stock_agent_runs VALUES (?,?,?,?,?,?,?,?)', (agent, agent, f'2033-05-18T03:33:{i:02}+00:00', '', 'intraday', 'success', 'x'*3000, 'MUST_NOT_LEAK'*10000))
        conn.execute("INSERT INTO stock_agent_profiles VALUES ('archived',1,'{}')")
        conn.execute("INSERT INTO stock_agent_runs VALUES ('old','archived','2099-01-01T00:00:00Z','','intraday','success','hidden','')")
    before = path.read_bytes()
    large = read_agent_activity(limit=50, db_path=path)
    result = read_agent_activity(limit=16, db_path=path)
    assert result['partial_errors'] == []
    assert result['items'] == large['items'][:16]
    assert len(result['items']) == 16
    assert 'MUST_NOT_LEAK' not in json.dumps(result)
    assert all(len(row['summary']) <= 2000 for row in result['items'])
    assert all(row['agentId'] != 'archived' for row in result['items'])
    assert path.read_bytes() == before


@pytest.mark.parametrize('limit', [True, 0, 51, -1, 1.5])
def test_home_feed_rejects_unbounded_request(tmp_path, limit):
    with pytest.raises(ValueError):
        read_agent_activity(limit=limit, db_path=tmp_path/'absent.db')
    assert not (tmp_path/'absent.db').exists()
