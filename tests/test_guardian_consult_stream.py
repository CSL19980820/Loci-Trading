import asyncio
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import GuardianStore
from src.ops.api import guardian_consult


def seed(path):
    conversation, request = str(uuid4()), str(uuid4())
    with GuardianStore(path) as store:
        store.submit_consultation(conversation, request, '问题', '')
        store.claim_consultation(request)
    return conversation, request


def test_progress_survives_reopen_and_cannot_overwrite_terminal(tmp_path):
    path = tmp_path / 'palace.db'
    conversation, request = seed(path)
    with GuardianStore(path) as store:
        store.update_consultation_progress(request, {'answer': '正在逐段回复'})
    with GuardianStore(path) as store:
        assert store.consultation_turn(conversation, request)['result']['answer'] == '正在逐段回复'
        assert store.consultation_turn(str(uuid4()), request) is None
        assert not store.submit_consultation(conversation, request, '问题', '')
        store.finish_consultation(request, {'answer': '完整回复'}, messages=[])
        store.update_consultation_progress(request, {'answer': '迟到的片段'})
        turn = store.consultation_turn(conversation, request)
        assert turn['status'] == 'success'
        assert turn['result']['answer'] == '完整回复'


def test_snapshot_stream_sends_partial_then_final_and_replays(tmp_path, monkeypatch):
    path = tmp_path / 'palace.db'
    conversation, request_id = seed(path)
    monkeypatch.setattr(guardian_consult, 'GuardianStore', lambda: GuardianStore(path))
    router = guardian_consult.build_consult_router(lambda: None)
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith('/stream'))

    class Request:
        async def is_disconnected(self):
            return False

    async def collect():
        response = await endpoint(conversation, request_id, Request())
        iterator = response.body_iterator
        first = await anext(iterator)
        assert '"status": "running"' in first
        with GuardianStore(path) as store:
            store.update_consultation_progress(request_id, {'answer': '第一段'})
        second = await anext(iterator)
        assert '第一段' in second
        with GuardianStore(path) as store:
            store.finish_consultation(request_id, {'answer': '第一段，第二段'})
        final = await anext(iterator)
        assert '第一段，第二段' in final
        assert '"status": "success"' in final
        assert [part async for part in iterator] == []
    asyncio.run(collect())

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(f'/consultations/{conversation}/turns/{request_id}/stream')
        assert response.headers['content-type'].startswith('text/event-stream')
        assert response.headers['x-accel-buffering'] == 'no'
        data = json.loads(response.text.split('data: ', 1)[1].strip())
        assert data['result']['answer'] == '第一段，第二段'
        assert client.get(f'/consultations/{uuid4()}/turns/{request_id}/stream').status_code == 404


def test_other_tenant_has_no_consultation(tmp_path):
    first, second = tmp_path / 'first.db', tmp_path / 'second.db'
    conversation, request = seed(first)
    with GuardianStore(second) as store:
        assert store.consultation_turn(conversation, request) is None


def test_expired_turn_terminates_stream_with_partial_answer(tmp_path):
    path = tmp_path / 'palace.db'
    conversation, request = seed(path)
    with GuardianStore(path) as store:
        store.update_consultation_progress(request, {'answer': '已收到的正文'})
        with store.conn:
            store.conn.execute('UPDATE guardian_consult_turns SET updated=0 WHERE id=?', (request,))
        turn = store.consultation_turn(conversation, request)
        assert turn['status'] == 'failed'
        assert turn['result']['answer'] == '已收到的正文'
        assert turn['result']['error']
