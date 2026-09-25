"""上游拒收（429/503/529）的有限重放：只重放未开始生成的请求，不越过上限或期限。"""
import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx2
import pytest

from src.ai.infrastructure import client as client_module
from src.ai.infrastructure import connection_retry, stream_deadline
from src.ai.infrastructure.client import ChatMessage, LLMError, ProviderConfig, chat
from src.ai.infrastructure.client_stream import chat_stream
from src.ai.infrastructure.connection_retry import (
    ConnectionRetryClient,
    status_retry_delay,
)

CONFIG = ProviderConfig(name="fixture", protocol="openai_compatible", base_url="http://fixture.invalid/v1",
                        api_key="fixture-key", model="fixture", timeout=30)
OK_BODY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
SSE_BODY = (b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')


def scripted(responses):
    calls = []

    def handler(request):
        calls.append(request)
        status, headers, body = responses[min(len(calls), len(responses)) - 1]
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx2.Response(status, headers=headers, content=content)

    return handler, calls


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(connection_retry.time, "sleep", slept.append)
    return slept


def use_sync_transport(monkeypatch, handler):
    monkeypatch.setattr(client_module, "_client",
                        lambda config: ConnectionRetryClient(transport=httpx2.MockTransport(handler)))


def test_rate_limited_request_is_replayed_then_succeeds(monkeypatch, no_sleep):
    handler, calls = scripted([(429, {"Retry-After": "2"}, {"error": "busy"}), (200, {}, OK_BODY)])
    use_sync_transport(monkeypatch, handler)
    response = chat(CONFIG, [ChatMessage(role="user", content="hi")])
    assert response.text == "ok"
    assert len(calls) == 2
    assert no_sleep == [2.0]


def test_retry_after_beyond_cap_surfaces_original_error(monkeypatch, no_sleep):
    handler, calls = scripted([(429, {"Retry-After": "60"}, {"error": "slow down"})])
    use_sync_transport(monkeypatch, handler)
    with pytest.raises(LLMError, match="429"):
        chat(CONFIG, [ChatMessage(role="user", content="hi")])
    assert len(calls) == 1
    assert no_sleep == []


def test_non_busy_errors_are_not_replayed(monkeypatch, no_sleep):
    handler, calls = scripted([(400, {}, {"error": "bad parameter"})])
    use_sync_transport(monkeypatch, handler)
    with pytest.raises(LLMError, match="400"):
        chat(CONFIG, [ChatMessage(role="user", content="hi")])
    assert len(calls) == 1


def test_replay_is_bounded(monkeypatch, no_sleep):
    handler, calls = scripted([(503, {}, {"error": "unavailable"})])
    use_sync_transport(monkeypatch, handler)
    with pytest.raises(LLMError, match="503"):
        chat(CONFIG, [ChatMessage(role="user", content="hi")])
    assert len(calls) == 1 + connection_retry.MAX_STATUS_RETRIES
    assert no_sleep == [1.0, 2.0]


def test_grpc_gateway_and_exhausted_budget_are_never_replayed():
    busy = SimpleNamespace(status_code=529, headers={}, extensions={})
    assert status_retry_delay(busy, 0) == 1.0
    assert status_retry_delay(busy, 0, budget=0.5) is None
    grpc = SimpleNamespace(status_code=429, headers={}, extensions={"loci_transport": b"grpc"})
    assert status_retry_delay(grpc, 0) is None


def test_stream_request_replayed_after_upstream_busy(monkeypatch):
    handler, calls = scripted([(503, {"Retry-After": "0"}, b"overloaded"),
                               (200, {"Content-Type": "text/event-stream"}, SSE_BODY)])

    @contextmanager
    def mock_async_client(config):
        with asyncio.Runner() as runner:
            client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
            try:
                yield runner, client
            finally:
                runner.run(client.aclose())

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(stream_deadline, "_async_client", mock_async_client)
    monkeypatch.setattr(stream_deadline.asyncio, "sleep", no_wait)
    result = chat_stream(CONFIG, [ChatMessage(role="user", content="hi")])
    assert result.text == "hi"
    assert result.raw["finish_reason"] == "stop"
    assert len(calls) == 2
