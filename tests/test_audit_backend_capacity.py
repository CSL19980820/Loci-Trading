import json
from datetime import date
from threading import Event

import pytest

from src.shared.bounded_executor import BoundedExecutor, QueueFull
from src.shared.tenancy import tenant_scope, current_tenant
from src.ops.application import skill_runs
from src.research.infrastructure.backtest_jobs import ResearchBacktestJobStore, recover_research_jobs, DuplicateResearchJob
from src.ai.application import usage_reporting


def test_event_cursor_bad_lines_partial_and_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_runs, 'skill_runs_dir', lambda: tmp_path)
    path = tmp_path / 'run.events.jsonl'
    path.write_bytes(b'{"n":0}\ninvalid\n{"n":2}\n{"n":3')
    events, cursor = skill_runs.read_events('run')
    assert [row['_seq'] for row in events] == [0, 2]
    assert cursor == 3
    assert skill_runs.read_events('run', after=cursor) == ([], 3)
    with path.open('ab') as handle:
        handle.write(b'}\n')
    assert skill_runs.read_events('run', after=cursor)[0][0]['n'] == 3
    assert len(skill_runs.read_events('run', limit=1)[0]) == 1
    path.write_bytes(b'{"n":9}\n')
    assert skill_runs.read_events('run')[0][0]['n'] == 9


def test_job_import_recovery_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCI_DATA_DIR', str(tmp_path))
    for tenant in [tmp_path, tmp_path / 'tenants' / 'child']:
        for name in ['backtest_jobs.json', 'factor_jobs.json']:
            path = tenant / 'research_runs' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            original = json.dumps({'jobs': {'old': {'id': 'old', 'status': 'running'}}})
            path.write_text(original)
            store = ResearchBacktestJobStore(path)
            live = store.create({'strategy': 'x'})
            assert store.get('old')['status'] == 'running'
            recover_research_jobs()
            assert store.get('old')['status'] == 'failed'
            assert store.get(live['id'])['status'] == 'queued'
            with pytest.raises(DuplicateResearchJob):
                store.create({'strategy': 'x'})
            assert path.read_text() == original
            store.update(live['id'], status='completed')
            store.export_legacy(tenant / f'rollback-{name}')
            assert json.loads((tenant / f'rollback-{name}').read_text(encoding='utf-8'))['jobs'][live['id']]['status'] == 'completed'


def test_executor_admission_tenant_cancel_and_reuse():
    executor = BoundedExecutor('test-audit', capacity=2, per_tenant=1)
    gate = Event()
    entered = Event()
    cancelled = Event()
    def running():
        entered.set()
        gate.wait(5)
        return current_tenant()
    with tenant_scope('a'), executor.reserve() as submit:
        first = submit(running)
    assert entered.wait(2)
    with tenant_scope('a'), pytest.raises(QueueFull), executor.reserve():
        pass
    with tenant_scope('b'), executor.reserve() as submit:
        second = submit(lambda: None, on_cancel=cancelled.set)
    assert second.cancel()
    assert cancelled.wait(2)
    gate.set()
    assert first.result(2) == 'a'
    executor.shutdown()
    executor.start()
    with executor.reserve() as submit:
        assert submit(lambda: 42).result(2) == 42
    executor.shutdown()


def test_usage_cache_isolated_and_partial(tmp_path, monkeypatch):
    calls = []
    def read(root, **kwargs):
        calls.append(root)
        return {'items': [], 'unavailable_tenants': ['x']}
    monkeypatch.setattr(usage_reporting, '_read_platform_model_usage', read)
    kwargs = dict(start=date(2026, 1, 1), end=date(2026, 1, 2))
    first = usage_reporting.platform_model_usage(tmp_path, **kwargs)
    first['unavailable_tenants'].clear()
    second = usage_reporting.platform_model_usage(tmp_path, **kwargs)
    assert second['partial'] and second['unavailable_tenants'] == ['x']
    assert len(calls) == 1
    usage_reporting.platform_model_usage(tmp_path / 'other', **kwargs)
    assert len(calls) == 2


def test_event_tail_100000_records_uses_saved_offset(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_runs, 'skill_runs_dir', lambda: tmp_path)
    path = tmp_path / 'large.events.jsonl'
    path.write_bytes(b'{"type":"progress"}\n' * 100000)
    rows, cursor = skill_runs.read_events('large', after=99990)
    assert len(rows) == 10 and cursor == 100000
    offsets = skill_runs._event_indexes[str(path.resolve())][2]
    assert offsets[-1] == path.stat().st_size
    with path.open('ab') as handle:
        handle.write(b'{"type":"done"}\n')
    rows, cursor = skill_runs.read_events('large', after=cursor)
    assert len(rows) == 1 and cursor == 100001
    assert skill_runs._event_indexes[str(path.resolve())][2] is offsets


def test_shutdown_cancels_queued_and_releases_admission():
    from concurrent.futures import ThreadPoolExecutor
    executor = BoundedExecutor('shutdown-test', capacity=2, per_tenant=2)
    entered, release, cancelled = Event(), Event(), Event()
    def work():
        entered.set()
        release.wait(5)
    with executor.reserve() as submit:
        running = submit(work)
    assert entered.wait(2)
    with executor.reserve() as submit:
        queued = submit(lambda: None, on_cancel=cancelled.set)
    with ThreadPoolExecutor(max_workers=1) as helper:
        shutdown = helper.submit(executor.shutdown)
        assert cancelled.wait(2)
        release.set()
        shutdown.result(2)
    assert queued.cancelled() and running.done()
    assert not executor._counts


def test_events_http_cursor_and_sse_drain_before_terminal(tmp_path, monkeypatch):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from src.ops.api.skill_runs_api import register_skill_run_routes
    monkeypatch.setattr(skill_runs, 'skill_runs_dir', lambda: tmp_path)
    skill_runs.save_run({'id': 'run', 'status': 'done'})
    path = tmp_path / 'run.events.jsonl'
    path.write_bytes(b'{"type":"progress"}\nbroken\n' + b'{"type":"progress"}\n' * 450)
    router = APIRouter()
    register_skill_run_routes(router, write_guard=None, ops_factory=lambda: None,
                              market_db=None, ops_db=None, palace_db=None)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        first = client.get('/api/skill-runs/run/events').json()
        assert first['next_after'] == 200
        assert len(first['events']) == 199
        second = client.get('/api/skill-runs/run/events?after=200').json()
        assert second['events'][0]['_seq'] == 200
        response = client.get('/api/skill-runs/run/events?stream=true')
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert len([event for event in events if event['type'] == 'progress']) == 451
        assert events[-1] == {'type': 'status', 'status': 'done'}


def test_reservation_cannot_submit_twice_or_after_exit():
    executor = BoundedExecutor('single-ticket')
    with executor.reserve() as submit:
        future = submit(lambda: 1)
        with pytest.raises(RuntimeError):
            submit(lambda: 2)
    assert future.result(2) == 1
    with pytest.raises(RuntimeError):
        submit(lambda: 3)
    executor.shutdown()
    assert not executor._counts


def test_usage_different_keys_do_not_block_and_same_key_is_single_flight(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    entered, release = Event(), Event()
    calls = []
    def read(root, **kwargs):
        calls.append(root)
        if root == tmp_path:
            entered.set()
            assert release.wait(3)
        return {'items': [], 'unavailable_tenants': []}
    monkeypatch.setattr(usage_reporting, '_read_platform_model_usage', read)
    kwargs = dict(start=date(2026, 2, 1), end=date(2026, 2, 2))
    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(usage_reporting.platform_model_usage, tmp_path, **kwargs)
        assert entered.wait(2)
        duplicate = executor.submit(usage_reporting.platform_model_usage, tmp_path, **kwargs)
        other = executor.submit(usage_reporting.platform_model_usage, tmp_path / 'other', **kwargs)
        try:
            assert other.result(1)['partial'] is False
        finally:
            release.set()
        first.result(2)
        duplicate.result(2)
    assert calls.count(tmp_path) == 1


def test_research_paths_respect_primary_override_and_child_isolation(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    custom = tmp_path / 'custom' / 'configured-ops.db'
    monkeypatch.setenv('LOCI_DATA_DIR', str(root))
    monkeypatch.setenv('PALACE_OPS_DB', str(custom))
    with tenant_scope('__primary__'):
        primary = ResearchBacktestJobStore()
        assert primary.db_path == custom
        primary_job = primary.create({'owner': 'primary'})
    with tenant_scope('child'):
        child = ResearchBacktestJobStore()
        assert child.db_path == root / 'tenants' / 'child' / 'ops.db'
        child_job = child.create({'owner': 'child'})
    with tenant_scope('__primary__'):
        explicit_child = ResearchBacktestJobStore(root / 'tenants' / 'child' / 'research_runs' / 'backtest_jobs.json')
        assert explicit_child.db_path == child.db_path
        assert explicit_child.get(child_job['id'])['request']['owner'] == 'child'
        isolated = ResearchBacktestJobStore(tmp_path / 'isolated' / 'research_runs' / 'backtest_jobs.json')
        assert isolated.db_path == tmp_path / 'isolated' / 'ops.db'
    primary.update(primary_job['id'], process_id='previous-process')
    child.update(child_job['id'], process_id='previous-process')
    recover_research_jobs()
    assert primary.get(primary_job['id'])['status'] == 'failed'
    assert child.get(child_job['id'])['status'] == 'failed'
    assert primary.get(child_job['id']) is None
    assert child.get(primary_job['id']) is None
    assert not (root / 'ops.db').exists()


def test_recovery_never_rewrites_current_process_job(tmp_path, monkeypatch):
    store = ResearchBacktestJobStore(tmp_path / 'jobs.json')
    old = store.create({'owner': 'old'})
    store.update(old['id'], process_id='old-process')
    live = store.create({'owner': 'live'})
    store.update(live['id'], status='running', run_id='active-run')
    before = store.get(live['id'])
    statements = []
    original = store._connect
    def connect():
        conn = original()
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(store, '_connect', connect)
    assert store.recover_interrupted() == [old['id']]
    assert store.get(live['id']) == before
    assert all(live['id'] not in sql for sql in statements if sql.startswith('UPDATE'))


@pytest.mark.parametrize('kind', ['backtest', 'factor'])
def test_research_http_queue_duplicate_and_shutdown(tmp_path, monkeypatch, kind):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.research.api import backtest_router, factor_router
    module = backtest_router if kind == 'backtest' else factor_router
    executor = BoundedExecutor('http-research', capacity=3, per_tenant=3)
    monkeypatch.setattr(module, f'_{kind.upper()}_EXECUTOR', executor)
    store = ResearchBacktestJobStore(tmp_path / f'{kind}_jobs.json')
    build = getattr(module, f'build_research_{kind}_router')
    app = FastAPI()
    app.include_router(build(write_dependency=lambda: None,
                             backtest_job_store_factory=lambda: store))
    gate, entered = Event(), Event()
    def blocker():
        entered.set()
        gate.wait(5)
    with executor.reserve() as submit:
        submit(blocker)
    assert entered.wait(2)
    payload = {'start': '2026-01-01', 'end': '2026-02-28', 'split': {
        'train_start': '2026-01-01', 'train_end': '2026-01-31',
        'oos_start': '2026-02-01', 'oos_end': '2026-02-28'}}
    payload.update({'strategy': 'no-real-strategy'} if kind == 'backtest' else {'historical_universe_id': 'isolated-test'})
    try:
        with TestClient(app) as client:
            url = f'/api/research/{kind}-jobs'
            first = client.post(url, json=payload)
            assert first.status_code == 202
            job_id = first.json()['job']['id']
            assert client.post(url, json=payload).status_code == 409
            payload.update({'seed': 1} if kind == 'backtest' else {'historical_universe_id': 'isolated-second'})
            assert client.post(url, json=payload).status_code == 202
            full = client.post(url, json=payload)
            assert full.status_code == 429 and full.headers['retry-after'] == '5'
            assert client.get(f'{url}/{job_id}').json()['job']['status'] == 'queued'
        with ThreadPoolExecutor(max_workers=1) as helper:
            shutdown = helper.submit(executor.shutdown)
            # A cancellation callback persists synchronously before shutdown waits for running work.
            import time
            deadline = time.monotonic() + 2
            while store.get(job_id)['status'] == 'queued' and time.monotonic() < deadline:
                time.sleep(0.01)
            assert store.get(job_id)['status'] == 'failed'
            gate.set()
            shutdown.result(2)
    finally:
        gate.set()
        executor.shutdown()


def test_consult_http_full_queue_preserves_idempotency(tmp_path, monkeypatch):
    from uuid import uuid4
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ledger import GuardianStore
    from src.ops.api import guardian_consult
    path = tmp_path / 'palace.db'
    executor = BoundedExecutor('http-consult', capacity=1, per_tenant=1)
    monkeypatch.setattr(guardian_consult, 'GuardianStore', lambda: GuardianStore(path))
    monkeypatch.setattr(guardian_consult, '_CONSULT_EXECUTOR', executor)
    entered, release = Event(), Event()
    def run(tenant, request_id):
        entered.set()
        release.wait(5)
    monkeypatch.setattr(guardian_consult, 'run_consultation', run)
    app = FastAPI()
    app.include_router(guardian_consult.build_consult_router(lambda: None))
    payload = {'conversation_id': str(uuid4()), 'request_id': str(uuid4()), 'message': '问题'}
    try:
        with TestClient(app) as client:
            assert client.post('/consultations', json=payload).status_code == 202
            assert entered.wait(2)
            assert client.post('/consultations', json=payload).status_code == 202
            assert client.post('/consultations', json={**payload, 'message': '不同内容'}).status_code == 409
            other = {**payload, 'conversation_id': str(uuid4()), 'request_id': str(uuid4())}
            assert client.post('/consultations', json=other).status_code == 429
            with GuardianStore(path) as store:
                assert store.consultation_turn(other['conversation_id'], other['request_id']) is None
    finally:
        release.set()
        executor.shutdown()


def test_event_rotation_and_same_size_rewrite_reset_stale_cursor(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(skill_runs, 'skill_runs_dir', lambda: tmp_path)
    path = tmp_path / 'rotated.events.jsonl'
    path.write_bytes(b'{"n":1}\n' * 5)
    assert skill_runs.read_events('rotated')[1] == 5
    replacement = tmp_path / 'replacement.jsonl'
    replacement.write_bytes(b'{"n":2}\n')
    os.replace(replacement, path)
    events, cursor = skill_runs.read_events('rotated', after=5)
    assert [item['n'] for item in events] == [2] and cursor == 1
    old_mtime = path.stat().st_mtime_ns
    path.write_bytes(b'{"n":3}\n')
    os.utime(path, ns=(old_mtime + 1000000, old_mtime + 1000000))
    events, cursor = skill_runs.read_events('rotated', after=1)
    assert [item['n'] for item in events] == [3] and cursor == 1


def test_usage_failure_wakes_waiter_and_allows_retry(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    entered, release = Event(), Event()
    calls = []
    def read(root, **kwargs):
        calls.append(root)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
            raise RuntimeError('transient read failure')
        return {'items': [], 'unavailable_tenants': []}
    monkeypatch.setattr(usage_reporting, '_read_platform_model_usage', read)
    kwargs = dict(start=date(2026, 3, 1), end=date(2026, 3, 2))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(usage_reporting.platform_model_usage, tmp_path, **kwargs)
        assert entered.wait(2)
        second = executor.submit(usage_reporting.platform_model_usage, tmp_path, **kwargs)
        release.set()
        with pytest.raises(RuntimeError, match='transient read failure'):
            first.result(2)
        assert second.result(2)['partial'] is False
    assert len(calls) == 2
