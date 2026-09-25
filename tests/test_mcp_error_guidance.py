import json
from threading import Event

import pytest

from src.ai.application.agent_execution import _invoke
from src.ai.infrastructure.client import ToolCall
from src.intel.infrastructure import mcp


def failing_client(monkeypatch, error):
    client = mcp.McpClient(name="fixture", url="https://example.com/mcp", token="private-token",
                           headers={"X-Custom-Auth": "private-header"})
    client._initialized = True
    response = mcp._BufferedResponse(200, {}, json.dumps({"jsonrpc": "2.0", "id": 1, "error": error}))
    monkeypatch.setattr(mcp, "active_deadline", lambda: 123.0)
    monkeypatch.setattr(mcp, "deadline_request", lambda *_args: response)
    return client


@pytest.mark.parametrize(("code", "message"), [
    (-32052, "集合竞价数据仍在稳定中，需 09:25:30 后稳定帧。请稍后重试。"),
    (-32603, "该参数组合依赖的竞价指标尚未预热完成，可先查询原始竞价数据。"),
    (-32028, "Rate limit exceeded. Max 50 requests/minute"),
    (-32602, "参数 tradeDate 格式无效"),
])
def test_rpc_reason_reaches_model_tool_outcome(monkeypatch, code, message):
    client = failing_client(monkeypatch, {"code": code, "message": message})
    result = _invoke(ToolCall(id="call-1", name="fixture__scan", arguments={}), client.call_tool, Event())
    assert result.failed
    assert str(code) in result.text and message in result.text
    assert not result.invocation().ok
    assert message in result.invocation().error


def test_rpc_error_redacts_before_logging_or_returning_recovery(monkeypatch, caplog):
    client = failing_client(monkeypatch, {
        "code": -32052,
        "message": '数据未就绪 private-token private-header https://example.com/?auth=url-secret '
                   'Authorization: Bearer bearer-secret; "api_key": "quoted-secret"; '
                   'token=plain-secret; password=pass-secret; "Authorization": "Basic basic-secret"',
        "data": {"retryable": True, "retryAfterMs": 30000, "token": "data-secret"},
    })
    with pytest.raises(mcp.McpError) as caught:
        client.call_tool("fixture__scan", {})
    text = str(caught.value)
    assert "数据未就绪" in text and "可重试" in text and "30000 毫秒" in text
    for secret in ("private-token", "private-header", "url-secret", "bearer-secret", "quoted-secret",
                   "plain-secret", "pass-secret", "basic-secret", "data-secret"):
        assert secret not in text and secret not in caplog.text


@pytest.mark.parametrize("error", [None, "broken", {"message": "x" * 1000, "data": "broken"},
                                       {"code": "private-token", "data": {"retryAfterMs": "private-token"}}])
def test_malformed_rpc_error_still_returns_bounded_failure(monkeypatch, error):
    client = failing_client(monkeypatch, error)
    with pytest.raises(mcp.McpError) as caught:
        client.call_tool("scan", {})
    assert "MCP 协议错误" in str(caught.value)
    assert len(str(caught.value)) < 400
    assert "private-token" not in str(caught.value)
