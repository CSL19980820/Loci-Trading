from uuid import uuid4
from unittest.mock import Mock
from types import SimpleNamespace
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from src.ledger import GuardianStore
from src.ops import OpsStore
from src.shared.tenancy import tenant_scope
from src.ops.application.guardian_config import save_config
from src.ops.application import guardian_consult
from src.ops.api.guardian_consult import build_consult_router


def test_consultation_retry_serialization_and_tenant_isolation():
    with tenant_scope('consult_a'),GuardianStore() as ledger:
        before=ledger.state()
        assert ledger.submit_consultation('topic','request','我买贵了怎么办','我持有100股')
        assert not ledger.submit_consultation('topic','request','我买贵了怎么办','我持有100股')
        with pytest.raises(ValueError):ledger.submit_consultation('topic','request2','另一问题','')
        turn=ledger.claim_consultation('request')
        assert turn['notes']=='我持有100股'
        assert ledger.claim_consultation('request') is None
        ledger.finish_consultation('request',{'answer':'需要核对你的实际成本'},messages=[{'role':'assistant','content':'问题','reasoning_content':'preserved'}])
        assert ledger.state()==before and ledger.trades()['total']==0
        assert ledger.submit_consultation('topic','request2','我成本20','100股')
        assert ledger.claim_consultation('request2')['messages'][0]['reasoning_content']=='preserved'
        assert 'messages_json' not in ledger.consultation('topic')
    with tenant_scope('consult_b'),GuardianStore() as other:
        assert other.consultation('topic') is None and other.consultations()==[]


def test_read_only_consult_uses_real_notes_and_simulated_account_separately(monkeypatch):
    from src.ai import ProviderConfig
    provider=ProviderConfig('test','openai_compatible','https://example.invalid','test','test')
    monkeypatch.setattr('src.ai.resolve_config',lambda *a,**kw:provider)
    monkeypatch.setattr('src.ai.record_llm_usage',lambda **kw:None)
    def tools(protocol,**kwargs):
        assert kwargs['read_only']
        return [],None,{'label':'test'}
    monkeypatch.setattr(guardian_consult,'agent_tools',tools)
    run=Mock(return_value=SimpleNamespace(stopped_reason='completed',rounds=1,finish_reason='stop',text='请核对实际成本与买入日期',model='test',input_tokens=10,output_tokens=5,invocations=[],messages=[{'role':'assistant','content':'答复','reasoning_content':'kept'}]))
    monkeypatch.setattr('src.ai.application.agent.run_agent',run)
    with OpsStore(None) as store,GuardianStore() as ledger:
        save_config(store,{'provider':'test','model':'test'})
        before=ledger.state()
        ledger.submit_consultation('topic','request','是否追高','我实际买入300股，成本12元')
        turn=ledger.claim_consultation('request')
        result,messages=guardian_consult.answer_consultation(store,ledger,turn)
        assert run.call_args.kwargs['max_tokens']==328000
        import json
        payload=json.loads(run.call_args.kwargs['messages'][-1].content)
        assert payload['user_reported_real_context']=='我实际买入300股，成本12元'
        assert payload['simulated_account']['positions']==[]
        assert ledger.state()==before and messages[0]['reasoning_content']=='kept'
        assert result['answer']=='请核对实际成本与买入日期'


def test_consult_api_authorization_and_tenant_background_binding(monkeypatch):
    worker=Mock()
    monkeypatch.setattr('src.ops.api.guardian_consult.run_consultation',worker)
    def denied():raise HTTPException(403,'forbidden')
    payload={'conversation_id':str(uuid4()),'request_id':str(uuid4()),'message':'我的操作和模拟仓不同，怎么办','real_context':'今天买入100股'}
    app=FastAPI();app.include_router(build_consult_router(denied))
    with TestClient(app) as client:assert client.post('/consultations',json=payload).status_code==403
    app=FastAPI();app.include_router(build_consult_router(lambda:None))
    @app.middleware('http')
    async def tenant(request,call_next):
        with tenant_scope('consult_api'):return await call_next(request)
    with TestClient(app) as client:
        assert client.post('/consultations',json=payload).status_code==202
        assert client.post('/consultations',json=payload).status_code==202
        assert client.get('/consultations/'+payload['conversation_id']).json()['notes']==payload['real_context']
    worker.assert_called_once_with('consult_api',payload['request_id'])
