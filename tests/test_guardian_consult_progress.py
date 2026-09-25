from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import GuardianStore
from src.ops.application.guardian_consult_progress import ConsultationProgress


def seed(path):
    conversation, request = str(uuid4()), str(uuid4())
    with GuardianStore(path) as ledger:
        ledger.submit_consultation(conversation, request, '隔离问题', '')
        turn = ledger.claim_consultation(request)
    return conversation, request, turn


def test_real_event_names_boundaries_throttle_and_final_reload(tmp_path, monkeypatch):
    from src.ops.application import guardian_consult_progress as module
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    path = tmp_path / 'palace.db'
    conversation, request, _ = seed(path)
    with GuardianStore(path) as ledger:
        progress = ConsultationProgress(ledger, request, deadline=400)
        assert ledger.consultation_turn(conversation, request)['result']['phase'] == 'preparing'
        progress.event({'type': 'round_start', 'round': 1})
        progress.event({'type': 'think', 'delta': '研究依据 sk-private https://secret.test/?token=private'})
        # Same-phase deltas may be throttled, but the next actual tool boundary flushes them.
        call = progress.start_tool('market_overview')
        snapshot = ledger.consultation_turn(conversation, request)['result']
        assert snapshot['phase'] == 'tools'
        assert snapshot['tool_receipts'][0]['status'] == 'running'
        assert 'private' not in snapshot['thinking'] and 'secret.test' not in snapshot['thinking']
        clock[0] += 0.01
        progress.end_tool(call, ok=True)
        assert ledger.consultation_turn(conversation, request)['result']['tool_receipts'][0]['status'] == 'done'
        progress.event({'type': 'token', 'delta': '研究草稿'})
        progress.event({'type': 'round_start', 'round': 2})
        assert progress.value['answer'] == '' and progress.value['thinking']
        progress.event({'type': 'think', 'delta': '第二轮核对'})
        assert '\n\n第二轮核对' in progress.value['thinking']
        progress.event({'type': 'token', 'delta': '最终正文'})
        final = progress.finish(success=True, answer='完整最终正文')
        ledger.finish_consultation(request, final)
        progress.event({'type': 'token', 'delta': '迟到片段'})
        progress.flush()
    with GuardianStore(path) as ledger:
        final = ledger.consultation_turn(conversation, request)
        assert final['status'] == 'success'
        assert final['result']['phase'] == 'done'
        assert final['result']['answer'] == '完整最终正文'
        assert final['result']['tool_receipts'][0]['elapsed_ms'] >= 0


@pytest.mark.parametrize('fail', [False, True])
def test_consultation_wires_real_protocol_and_tool_execution_without_raw_payloads(tmp_path, monkeypatch, fail):
    import src.ai
    from src.ops.application import guardian_consult as module, guardian_completion, guardian_research_tools
    path = tmp_path / 'palace.db'
    conversation, request, turn = seed(path)
    provider = SimpleNamespace(model='fixture', protocol='openai', context_window=10000, max_output_tokens=1000)
    monkeypatch.setattr(src.ai, 'resolve_config', lambda *a, **k: provider)
    monkeypatch.setattr(module, 'get_config', lambda _: {'provider': 'fixture', 'model': 'fixture'})
    monkeypatch.setattr(module, 'decision_history', lambda *a, **k: {'items': []})
    monkeypatch.setattr(module, 'mark_guardian_account', lambda *a: {})
    monkeypatch.setattr(module, 'guardian_position_policy', lambda *a: {})
    snapshots = []
    with GuardianStore(path) as ledger:
        monkeypatch.setattr(ledger, 'state', lambda: {})
        monkeypatch.setattr(ledger, 'trades', lambda **k: [])
        monkeypatch.setattr(ledger, 'experience', lambda **k: {'text': ''})
        monkeypatch.setattr(ledger, 'reports', lambda *a: [])
        original = ledger.update_consultation_progress
        def capture(request_id, payload):
            snapshots.append(deepcopy(payload))
            original(request_id, payload)
        monkeypatch.setattr(ledger, 'update_consultation_progress', capture)
        def tool(name, args):
            assert ledger.consultation_turn(conversation, request)['result']['tool_receipts'][-1]['status'] == 'running'
            return {'text': 'RAW_PRIVATE_TOOL_RESULT', 'is_error': fail}
        monkeypatch.setattr(guardian_research_tools, 'compose_research_tools', lambda *a, **k: ([], tool, {}))
        def run(*a, **kwargs):
            event = kwargs['on_event']
            event({'type': 'round_start', 'round': 1})
            event({'type': 'think', 'delta': '核对市场资料'})
            kwargs['tool_executor']('market_overview', {'api_key': 'RAW_SECRET_ARGUMENT'})
            if fail:
                raise ValueError('模拟模型中断')
            event({'type': 'round_start', 'round': 2})
            event({'type': 'token', 'delta': '最终答案'})
            event({'type': 'done', 'text': '最终答案'})
            return SimpleNamespace(text='最终答案', model='fixture', invocations=[], messages=[],
                                   stopped_reason='completed', finish_reason='stop')
        monkeypatch.setattr(guardian_completion, 'run_accounted_agent', run)
        if fail:
            with pytest.raises(ValueError, match='模拟模型中断'):
                module.answer_consultation(None, ledger, turn)
            result = ledger.consultation_turn(conversation, request)['result']
            assert result['phase'] == 'error'
        else:
            result, _ = module.answer_consultation(None, ledger, turn)
            assert result['phase'] == 'done' and result['answer'] == '最终答案'
        assert result['thinking'].strip() == '核对市场资料'
        assert result['tool_receipts'][0]['status'] == ('error' if fail else 'done')
        text = json.dumps(snapshots, ensure_ascii=False)
        assert 'RAW_PRIVATE_TOOL_RESULT' not in text and 'RAW_SECRET_ARGUMENT' not in text
        assert all(set(item) <= {'call_id', 'name', 'status', 'elapsed_ms', 'summary'} for item in result['tool_receipts'])


def test_progress_sse_replay_preserves_failed_process_and_excludes_internal_messages(tmp_path, monkeypatch):
    from src.ops.api import guardian_consult
    path = tmp_path / 'palace.db'
    conversation, request, _ = seed(path)
    with GuardianStore(path) as ledger:
        progress = ConsultationProgress(ledger, request)
        progress.event({'type': 'think', 'delta': '已完成的公开过程'})
        progress.start_tool('fixture_tool')
        final = progress.finish(success=False)
        ledger.finish_consultation(request, {**final, 'error': '已中断'})
    monkeypatch.setattr(guardian_consult, 'GuardianStore', lambda: GuardianStore(path))
    app = FastAPI()
    app.include_router(guardian_consult.build_consult_router(lambda: None))
    with TestClient(app) as client:
        response = client.get(f'/consultations/{conversation}/turns/{request}/stream')
        turn = json.loads(response.text.split('data: ', 1)[1])
        assert turn['status'] == 'failed' and turn['result']['phase'] == 'error'
        assert turn['result']['thinking'] == '已完成的公开过程'
        assert turn['result']['tool_receipts'][0]['status'] == 'error'
        assert 'messages_json' not in client.get(f'/consultations/{conversation}').json()
