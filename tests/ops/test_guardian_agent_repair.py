from unittest.mock import Mock
from types import SimpleNamespace
from src.ai import ProviderConfig
from src.ai.application.agent import AgentResult
from src.ops.application.guardian_agent import decide


def test_invalid_json_is_repaired_without_repeating_tools(monkeypatch):
    provider=ProviderConfig('test','openai_compatible','https://example.invalid','test','test',max_output_tokens=328000)
    monkeypatch.setattr('src.ai.resolve_config',lambda *a,**kw:provider)
    monkeypatch.setattr('src.ai.record_llm_usage',Mock())
    tool=Mock()
    monkeypatch.setattr('src.ops.application.guardian_tools.agent_tools',lambda *a,**kw:([],tool,{}))
    original=AgentResult(text='{"summary":',rounds=1,model='test',messages=[{'role':'assistant','content':'{"summary":','reasoning_content':'keep reason'}],input_tokens=10,output_tokens=3,finish_reason='stop')
    fixed=AgentResult(text='{"summary":"暂时持股","orders":[]}',rounds=1,model='test',input_tokens=7,output_tokens=5,finish_reason='stop')
    run=Mock(side_effect=[original,fixed]);monkeypatch.setattr('src.ai.application.agent.run_agent',run)
    decision,meta=decide(SimpleNamespace(db_path='test'),{'provider':'test','model':'test','prompt':'自主选择方法'}, {})
    assert decision.summary=='暂时持股' and meta['input_tokens']==17
    repaired_args=run.call_args_list[1].kwargs
    assert all(call.kwargs['max_tokens']==328000 for call in run.call_args_list)
    assert not repaired_args.get('tool_executor') and not repaired_args.get('tool_schemas')
    assert repaired_args['messages'][0].reasoning_content=='keep reason'
    tool.assert_not_called()
