"""HTTPX2 streams exercise the opt-in total deadline and transport release."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import anyio
import httpx2
import pytest

from src.intel import McpClient, McpError
from src.intel.infrastructure import mcp, mcp_deadline
from src.ops import JobCancelled, JobTimedOut
from src.shared.tenancy import current_tenant, tenant_scope


@pytest.fixture
def transport(monkeypatch):
    requests, clients, closed = [], [], []
    hook = SimpleNamespace(callback=None, stream=None)
    real_client = httpx2.AsyncClient
    monkeypatch.setattr(mcp, "validate_mcp_url", lambda url, **_kwargs: url)
    monkeypatch.setattr(mcp, "needs_system_proxy", lambda _url: False)

    async def handle(request):
        body = json.loads(request.content)
        requests.append((body, dict(request.headers), current_tenant()))
        if hook.callback:
            await hook.callback(body)
        if body["method"] == "initialize":
            return httpx2.Response(200, headers={"Mcp-Session-Id": "private-session"},
                                   json={"result": {"serverInfo": {"name": "test"}}})
        assert request.headers["Mcp-Session-Id"] == "private-session"
        if body["method"] == "notifications/initialized":
            return httpx2.Response(202)
        if hook.stream:
            return httpx2.Response(200, stream=hook.stream)
        return httpx2.Response(200, json={"result": {"content": [{"type": "text", "text": "ok"}],
                                                    "structuredContent": {"complete": True}}})

    class TrackedTransport(httpx2.MockTransport):
        async def aclose(self):
            closed.append(self)
            await super().aclose()

    def create(**kwargs):
        client = real_client(transport=TrackedTransport(handle), **kwargs)
        clients.append((client, kwargs))
        return client

    monkeypatch.setattr(mcp_deadline.httpx2, "AsyncClient", create)
    return SimpleNamespace(requests=requests, clients=clients, closed=closed, hook=hook)


def test_budget_reaches_all_posts_without_changing_shared_timeout(transport):
    client = McpClient(name="test", url="https://example.invalid", headers={"X-Workspace": "local"})
    with tenant_scope("deadline_alice"):
        result = client.call_tool("test__kline", {}, deadline=time.monotonic() + 5)
    assert result["text"] == "ok" and result["structured"] == {"complete": True}
    assert [body["method"] for body, _headers, _tenant in transport.requests] == ["initialize", "notifications/initialized", "tools/call"]
    assert [body.get("id") for body, _headers, _tenant in transport.requests] == [1, None, 2]
    assert {tenant for _body, _headers, tenant in transport.requests} == {"deadline_alice"}
    assert all(headers["x-workspace"] == "local" for _body, headers, _tenant in transport.requests)
    budgets = [kwargs["timeout"] for _http, kwargs in transport.clients]
    assert 0 < budgets[-1] <= budgets[0] <= 5
    assert all(not kwargs["trust_env"] and not kwargs["follow_redirects"] for _http, kwargs in transport.clients)
    assert len(transport.closed) == 3 and all(http.is_closed for http, _kwargs in transport.clients)
    assert client.timeout == 60 and mcp_deadline.active_deadline() is None


@pytest.mark.parametrize("stage", ["initialize", "notifications/initialized", "tools/call"])
def test_deadline_aborts_stalled_headers_and_closes_transport(transport, stage):
    cancelled = threading.Event()

    async def stall(body):
        if body["method"] == stage:
            try:
                await anyio.sleep(2)
            finally:
                cancelled.set()

    transport.hook.callback = stall
    client = McpClient(name="test", url="https://example.invalid")
    with pytest.raises(TimeoutError):
        client.call_tool("kline", {}, deadline=time.monotonic() + 0.3)
    assert cancelled.is_set()
    assert transport.requests[-1][0]["method"] == stage
    assert len(transport.closed) == len(transport.clients)
    assert all(http.is_closed for http, _kwargs in transport.clients)
    assert client.timeout == 60 and mcp_deadline.active_deadline() is None


def test_trickling_body_cannot_extend_deadline_and_stream_is_closed(transport):
    class Trickle(httpx2.AsyncByteStream):
        closed = False
        chunks = 0

        async def __aiter__(self):
            for _ in range(100):
                await anyio.sleep(0.01)
                self.chunks += 1
                yield b" "
            yield b'{"result":{"content":[]}}'

        async def aclose(self):
            self.closed = True

    stream = Trickle()
    transport.hook.stream = stream
    client = McpClient(name="test", url="https://example.invalid")
    with pytest.raises(TimeoutError):
        client.call_tool("kline", {}, deadline=time.monotonic() + 0.3)
    assert 1 < stream.chunks < 100 and stream.closed
    assert all(http.is_closed for http, _kwargs in transport.clients)
    assert mcp_deadline.active_deadline() is None


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, CancelledError, asyncio.CancelledError])
def test_deadline_branch_preserves_original_stop_object(transport, error_type):
    stop = error_type("original stop")

    async def fail(_body):
        raise stop

    transport.hook.callback = fail
    with pytest.raises(error_type) as caught:
        McpClient(name="test", url="https://example.invalid").call_tool("kline", {}, deadline=time.monotonic() + 5)
    assert caught.value is stop
    assert len(transport.closed) == 1


def test_expired_budget_starts_no_transport_and_default_path_still_works(transport, monkeypatch):
    client = McpClient(name="test", url="https://example.invalid")
    with pytest.raises(TimeoutError):
        client.call_tool("kline", {}, deadline=time.monotonic() - 1)
    assert transport.clients == [] and mcp_deadline.active_deadline() is None
    rpc = Mock(return_value={"content": [{"type": "text", "text": "legacy"}]})
    monkeypatch.setattr(client, "_rpc", rpc)
    monkeypatch.setattr(client, "_notify", Mock())
    assert client.call_tool("kline", {})["text"] == "legacy"
    assert all(not call.kwargs for call in rpc.call_args_list)
    assert transport.clients == []


def test_synchronous_call_inside_active_event_loop(transport):
    async def call():
        return McpClient(name="test", url="https://example.invalid").call_tool("kline", {}, deadline=time.monotonic() + 5)

    assert asyncio.run(call())["text"] == "ok"
    assert len(transport.closed) == 3


def test_deadline_body_keeps_response_size_cap(transport):
    class Oversized(httpx2.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"x" * (mcp.MAX_RESPONSE_BYTES + 1)

        async def aclose(self):
            self.closed = True

    stream = Oversized()
    transport.hook.stream = stream
    with pytest.raises(McpError, match="响应过大"):
        McpClient(name="test", url="https://example.invalid").call_tool("kline", {}, deadline=time.monotonic() + 5)
    assert stream.closed and len(transport.closed) == 3


@pytest.mark.parametrize("close_mode", ["slow", "error"])
def test_cleanup_is_bounded_and_preserves_original_stop(transport, monkeypatch, close_mode):
    stop = JobCancelled("keep this original cancellation")
    attempts, finished = [], []

    class BrokenClose(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b" "
            raise stop

        async def aclose(self):
            attempts.append("body")
            if close_mode == "slow":
                await anyio.sleep(0.6)
                finished.append("body")
            else:
                raise RuntimeError("body close failed")

    transport.hook.stream = BrokenClose()
    create = mcp_deadline.httpx2.AsyncClient

    def slow_client(**kwargs):
        http = create(**kwargs)
        original = http.aclose

        async def close():
            attempts.append("client")
            try:
                if close_mode == "slow":
                    await anyio.sleep(0.6)
                    finished.append("client")
                else:
                    raise RuntimeError("client close failed")
            finally:
                await original()

        http.aclose = close
        return http

    monkeypatch.setattr(mcp_deadline.httpx2, "AsyncClient", slow_client)
    client = McpClient(name="test", url="https://example.invalid")
    client._initialized, client._session_id = True, "private-session"
    with pytest.raises(JobCancelled) as caught:
        client.call_tool("kline", {}, deadline=time.monotonic() + 5)
    assert caught.value is stop
    assert attempts == ["body", "client"]
    assert finished == [], "cleanup may use a short grace, not wait for a slow close to finish"


def test_timeout_remains_timeout_when_closing_the_body_raises(transport):
    class BrokenClose(httpx2.AsyncByteStream):
        attempted = False

        async def __aiter__(self):
            await anyio.sleep(2)
            yield b" "

        async def aclose(self):
            self.attempted = True
            raise RuntimeError("cleanup must not replace deadline")

    stream = BrokenClose()
    transport.hook.stream = stream
    with pytest.raises(TimeoutError):
        McpClient(name="test", url="https://example.invalid").call_tool("kline", {}, deadline=time.monotonic() + 0.3)
    assert stream.attempted and len(transport.closed) == 3
