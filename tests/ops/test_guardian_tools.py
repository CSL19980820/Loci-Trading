import json
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime
from zoneinfo import ZoneInfo

from src.ops.application import guardian_tools
NOW = datetime(2026, 9, 11, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_wudao_is_preferred_and_system_tools_work_without_it(monkeypatch):
    from src.intel import BUILTIN_MCP_NAME, BUILTIN_WUDAO_NAME
    monkeypatch.setattr("src.intel.collect_tools", lambda *a: ([], {}))
    monkeypatch.setattr("src.intel.wudao_availability", lambda: {"available": True})
    assert guardian_tools.data_source()["server"] == BUILTIN_WUDAO_NAME
    monkeypatch.setattr("src.intel.wudao_availability", lambda: {"available": False, "reason": "未配置"})
    assert guardian_tools.data_source()["server"] == BUILTIN_MCP_NAME
    local = Mock(return_value=SimpleNamespace(quotes={"600001": {"price": 10, "trade_date": "2026-09-11", "trade_time": "10:00:00"}}))
    monkeypatch.setattr("src.market.application.live_cache.build_monitor_snapshot", local)
    assert guardian_tools.snapshot(["600001"], now=NOW).quotes["600001"]["price"] == 10
    local.assert_called_once()


def test_wudao_minute_payload_is_used_as_quote(monkeypatch):
    source = {"wudao": True, "server": "wudao", "watchlist_group": "守护测试"}
    monkeypatch.setattr(guardian_tools, "data_source", lambda: source)
    call = Mock(return_value={"structured": {
        "stock": {"code": "600001", "name": "测试股票"},
        "points": [{"time": "2026-09-11 10:00", "price": 10}, {"time": "2026-09-11 09:59", "price": 9}],
    }})
    monkeypatch.setattr("src.intel.call_mcp_tool", call)
    result = guardian_tools.snapshot(["600001"], now=NOW)
    assert result.quotes["600001"]["price"] == 10
    assert result.quotes["600001"]["source"] == "wudao"
    assert result.quotes["600001"]["trade_time"] == "10:00:00"
    assert call.call_args.args[0] == "minute_data"


def test_full_structured_tool_data_survives_transport_text_truncation(monkeypatch):
    from src.intel import McpTool
    monkeypatch.setattr(guardian_tools, "data_source", lambda: {"server": "test"})
    monkeypatch.setattr("src.intel.collect_tools", lambda *a: ([McpTool(name="quotes", description="报价", server="test"), McpTool(name="watchlist_remove", description="自选管理", server="test")], {"test__quotes": "test", "test__watchlist_remove": "test"}))
    complete = {"rows": ["完整数据" * 4000]}
    client = SimpleNamespace(call_tool=Mock(return_value={"text": "截断正文", "truncated": True, "structured": complete}))
    monkeypatch.setattr("src.intel.build_client", lambda *a: client)
    _, execute, _ = guardian_tools.agent_tools("openai_compatible")
    assert json.loads(execute("test__quotes", {})["text"]) == complete
    assert not execute("test__watchlist_remove", {"stock": "600001"}).get("is_error")
    client.call_tool.assert_called_with("test__watchlist_remove", {"stock": "600001"})


def test_consultation_tools_retain_research_but_block_writes(monkeypatch):
    from src.intel import McpTool
    monkeypatch.setattr(guardian_tools,'data_source',lambda:{'server':'test','wudao':True})
    monkeypatch.setattr('src.intel.collect_tools',lambda *a:([McpTool(name='kline',description='行情',server='test'),McpTool(name='watchlist_remove',description='删除',server='test')],{'test__kline':'test','test__watchlist_remove':'test'}))
    client=SimpleNamespace(call_tool=Mock(return_value={'text':'行情'}))
    monkeypatch.setattr('src.intel.build_client',lambda *a:client)
    schemas,execute,_=guardian_tools.agent_tools('openai_compatible',read_only=True)
    assert len(schemas)==1
    assert execute('test__watchlist_remove',{})['is_error']
    client.call_tool.assert_not_called()


def test_parallel_quotes_preserve_tenant_context(monkeypatch):
    from src.shared.tenancy import tenant_scope,current_tenant
    monkeypatch.setattr(guardian_tools,'data_source',lambda:{'server':'wudao','wudao':True})
    seen=[]
    def call(name,args,**kw):
        seen.append(current_tenant())
        return {'structured':{'stock':{'code':args['code']},'points':[{'time':'2026-09-14 10:00','price':10}]}}
    monkeypatch.setattr('src.intel.call_mcp_tool',call)
    with tenant_scope('parallel_quote_tenant'):
        result=guardian_tools.snapshot(['600001','600002','600003'], now=NOW.replace(day=14))
    assert len(result.quotes)==3 and seen==['parallel_quote_tenant']*3


def test_quote_failure_uses_system_source_with_provenance(monkeypatch):
    monkeypatch.setattr(guardian_tools,'data_source',lambda:{'server':'wudao','wudao':True})
    monkeypatch.setattr('src.intel.call_mcp_tool',Mock(side_effect=ValueError('primary offline')))
    local=Mock(return_value=SimpleNamespace(quotes={'600001':{'code':'600001','price':10,'source':'tencent','trade_date':'2026-09-14','trade_time':'10:00:00'}}))
    monkeypatch.setattr('src.market.application.live_cache.build_monitor_snapshot',local)
    result=guardian_tools.snapshot(['600001'], now=NOW.replace(day=14))
    assert result.quotes['600001']['source']=='tencent'
    assert 'primary offline' in result.quotes['600001']['primary_error']
    assert local.call_args.args[0]==['600001']
