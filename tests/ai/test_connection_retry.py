"""连接抖动恢复与不可重放错误边界；全部使用内存传输。"""
from __future__ import annotations

import json
from unittest.mock import patch

import httpx2
import pytest

from src.ai.infrastructure.client import ChatMessage, LLMError, ProviderConfig, chat
from src.ai.infrastructure.connection_retry import ConnectionRetryClient
from src.ai.application.agent import run_agent


def config() -> ProviderConfig:
    return ProviderConfig(name="test", protocol="openai_compatible",
                          base_url="https://model.invalid", api_key="test-key", model="test")


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.ConnectTimeout])
@pytest.mark.parametrize("stream", [False, True])
def test_connect_failures_recover_without_changing_request(error, stream) -> None:
    requests = []

    def handle(request):
        requests.append((request.content, request.headers["Authorization"]))
        if len(requests) < 3:
            raise error("TLS handshake failed", request=request)
        return httpx2.Response(200, text="OK")

    with patch("src.ai.infrastructure.connection_retry.time.sleep") as sleep:
        with ConnectionRetryClient(transport=httpx2.MockTransport(handle)) as client:
            request = client.build_request("POST", "https://model.invalid", json={"x": 1},
                                           headers={"Authorization": "Bearer test-key"})
            response = client.send(request, stream=stream)
            assert response.read() == b"OK"
            response.close()
    assert requests == [requests[0]] * 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


@pytest.mark.parametrize("error,attempts", [
    (httpx2.ConnectError, 3), (httpx2.ConnectTimeout, 3),
    (httpx2.ReadTimeout, 1), (httpx2.ReadError, 1),
    (httpx2.WriteError, 1), (httpx2.RemoteProtocolError, 1),
])
def test_retries_are_bounded_and_never_retry_read_write_errors(error, attempts) -> None:
    calls = []

    def handle(request):
        calls.append(request)
        raise error("broken", request=request)

    with patch("src.ai.infrastructure.connection_retry.time.sleep"):
        with ConnectionRetryClient(transport=httpx2.MockTransport(handle)) as client:
            with pytest.raises(error):
                client.post("https://model.invalid", json={})
    assert len(calls) == attempts


def test_quota_error_is_not_retried() -> None:
    calls = []

    def handle(request):
        calls.append(request)
        return httpx2.Response(400, json={"error": {"code": "insufficient_user_quota"}})

    with patch("src.ai.infrastructure.client.ConnectionRetryClient",
               side_effect=lambda **kw: ConnectionRetryClient(transport=httpx2.MockTransport(handle), **kw)):
        with pytest.raises(LLMError, match="insufficient_user_quota"):
            chat(config(), [ChatMessage(role="user", content="hello")])
    assert len(calls) == 1


def test_agent_recovers_second_round_without_replaying_tool() -> None:
    requests = []
    tool_calls = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) in (2, 3):
            raise httpx2.ConnectError("SSL UNEXPECTED_EOF_WHILE_READING", request=request)
        delta = ({"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                                  "function": {"name": "quote", "arguments": "{}"}}]}
                 if len(requests) == 1 else {"content": "done"})
        data = {"model": "test", "choices": [{"delta": delta}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        return httpx2.Response(200, text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n")

    def execute(name, arguments):
        tool_calls.append(name)
        return {"price": 12}

    with patch("src.ai.infrastructure.connection_retry.time.sleep"), patch(
        "src.ai.infrastructure.client.ConnectionRetryClient",
        side_effect=lambda **kw: ConnectionRetryClient(transport=httpx2.MockTransport(handle), **kw),
    ):
        result = run_agent(config(), system="test", user_prompt="quote", tool_executor=execute,
                           tool_schemas=[{"type": "function", "function": {"name": "quote"}}])
    assert result.stopped_reason == "completed"
    assert result.text == "done"
    assert result.rounds == 2
    assert result.input_tokens == 20 and result.output_tokens == 4
    assert tool_calls == ["quote"]
    assert requests[1] == requests[2] == requests[3]
    assert requests[1]["messages"][-1]["role"] == "tool"
