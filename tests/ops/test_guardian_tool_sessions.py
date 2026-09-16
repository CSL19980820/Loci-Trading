"""Real MCP handshake and mutable request state under guardian parallel execution."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest

from src.intel import McpClient, McpTool
from src.ai import ChatResponse, ProviderConfig, ToolCall
from src.ai.application import agent
from src.ops.application.guardian_completion import complete_decision
from src.ops import JobCancelled, JobTimedOut
from src.ops.application import guardian_tools
from src.shared.tenancy import current_tenant, submit_with_tenant, tenant_scope


@pytest.fixture
def wire(monkeypatch):
    clients, requests = [], []
    hook = SimpleNamespace(callback=lambda *_args: None)
    names = ["kline", "minute_data", "watchlist_remove", "opaque_lookup"]
    tools = [McpTool(name=name, description=name, server="test") for name in names]
    monkeypatch.setattr(guardian_tools, "data_source", lambda: {"server": "test", "wudao": True})
    monkeypatch.setattr("src.intel.collect_tools", lambda *_args: (tools, {f"test__{n}": "test" for n in names}))
    for name in ("acquire_quota", "record_quota_call", "quota_snapshot"):
        monkeypatch.setattr(f"src.intel.application.fetch.{name}", Mock(return_value={}))

    def build(_name):
        client = McpClient(name="test", url="https://example.invalid/mcp")
        clients.append((client, current_tenant()))
        return client

    def transport(client):
        owner = next(owner for item, owner in clients if item is client)
        session = f"session-{id(client)}"

        def handle(request):
            body = json.loads(request.content)
            assert current_tenant() == owner
            requests.append((client, owner, threading.get_ident(), body))
            if body["method"] == "initialize":
                assert not request.headers.get("Mcp-Session-Id")
                return httpx2.Response(200, headers={"Mcp-Session-Id": session}, json={"result": {"serverInfo": {"name": "test"}}})
            assert request.headers["Mcp-Session-Id"] == session
            if body["method"] == "notifications/initialized":
                return httpx2.Response(202)
            hook.callback(client, body)
            result = {"owner": owner, "session": session, "request_id": body["id"]}
            return httpx2.Response(200, json={"result": {"content": [{"type": "text", "text": "ok"}], "structuredContent": result}})

        return httpx2.Client(transport=httpx2.MockTransport(handle))

    monkeypatch.setattr("src.intel.build_client", build)
    monkeypatch.setattr(McpClient, "_client", transport)
    return SimpleNamespace(clients=clients, requests=requests, hook=hook)


def test_parallel_workers_do_not_share_mutable_session_or_request_ids(wire):
    barrier = threading.Barrier(2)
    wire.hook.callback = lambda _client, body: barrier.wait(3) if body["params"]["arguments"].get("first") else None
    with tenant_scope("session_alice"):
        _, execute, _ = guardian_tools.agent_tools("openai_compatible")

        def twice():
            return [json.loads(execute("test__kline", {"first": first})["text"]) for first in (True, False)]

        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [submit_with_tenant(pool, twice) for _ in range(2)]
            results = [task.result(timeout=5) for task in tasks]
    assert len({result[0]["session"] for result in results}) == 2
    for result in results:
        assert [row["request_id"] for row in result] == [2, 3]
        assert len({row["session"] for row in result}) == 1
        assert {row["owner"] for row in result} == {"session_alice"}
    assert all(client.timeout == 60 for client, _owner in wire.clients)


def test_worker_rebuilds_session_when_tenant_changes(wire):
    _, execute, _ = guardian_tools.agent_tools("anthropic")
    results = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        for tenant in ("session_alice", "session_bob", "session_bob", "session_alice"):
            with tenant_scope(tenant):
                results.append(submit_with_tenant(pool, execute, "test__minute_data", {}).result(timeout=5)["structured"])
    assert [row["owner"] for row in results] == ["session_alice", "session_bob", "session_bob", "session_alice"]
    assert [row["request_id"] for row in results] == [2, 2, 3, 2]
    assert results[1]["session"] == results[2]["session"]
    assert len({row["session"] for row in results}) == 3


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, CancelledError, asyncio.CancelledError])
def test_executor_preserves_wrapped_cancellation_identity(wire, error_type):
    stop = error_type("cancel tool")

    def cancel(*_args):
        raise stop

    wire.hook.callback = cancel
    _, execute, _ = guardian_tools.agent_tools("openai_compatible")
    with pytest.raises(error_type) as caught:
        execute("test__kline", {})
    assert caught.value is stop


def test_completion_whitelist_keeps_writes_and_unknown_reads_sequential(wire, monkeypatch, tmp_path):
    caller = threading.get_ident()
    barrier = threading.Barrier(2)
    seen = []
    lock = threading.Lock()
    active = 0

    def check(_client, body):
        nonlocal active
        name = body["params"]["name"]
        if name in {"kline", "minute_data"}:
            assert threading.get_ident() != caller
            with lock:
                active += 1
            barrier.wait(3)
            with lock:
                seen.append(name)
                active -= 1
        else:
            assert threading.get_ident() == caller and active == 0
            assert {"kline", "minute_data"}.issubset(seen)
            seen.append(name)

    wire.hook.callback = check
    schemas, execute, _ = guardian_tools.agent_tools("openai_compatible")
    names = ["kline", "minute_data", "watchlist_remove", "opaque_lookup"]
    responses = [ChatResponse(text="read", tool_calls=[ToolCall(id=str(i), name=f"test__{n}", arguments={}) for i, n in enumerate(names)]),
                 ChatResponse(text='{"summary":"hold","orders":[]}', raw={"finish_reason": "stop"})]
    chat = Mock(side_effect=responses)
    monkeypatch.setattr(agent, "chat_stream", chat)
    monkeypatch.setattr(agent, "chat", chat)
    monkeypatch.setattr("src.ai.record_llm_usage", Mock())
    provider = ProviderConfig("test", "openai_compatible", "https://example.invalid", "test", "test")
    complete_decision(provider, SimpleNamespace(db_path=tmp_path / "unused.db"), system="test", payload={},
                      schemas=schemas, execute=execute, archive=SimpleNamespace(receipts=[], documents={}),
                      checkpoint=lambda *_args: None, deadline=time.monotonic() + 270, config={"parallel_tools": 2})
    assert seen[-2:] == ["watchlist_remove", "opaque_lookup"]
    assert len({id(client) for client, _owner, _thread, body in wire.requests if body["method"] == "tools/call"}) == 3


def test_deadline_uses_public_guard_and_does_not_change_client_timeout(wire, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(guardian_tools.time, "monotonic", lambda: clock[0])
    guarded = Mock(return_value={"text": "ok"})
    monkeypatch.setattr("src.intel.guarded_client_call", guarded)
    _, execute, _ = guardian_tools.agent_tools("openai_compatible", deadline=105)
    assert execute("test__kline", {})["text"] == "ok"
    guarded.assert_called_once_with(wire.clients[0][0], "test__kline", {}, pool="skill", deadline=105)
    assert wire.clients[0][0].timeout == 60
    clock[0] = 105
    with pytest.raises(TimeoutError):
        execute("test__kline", {})
    assert guarded.call_count == 1 and wire.requests == []
