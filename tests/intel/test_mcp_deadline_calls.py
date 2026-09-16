"""Public MCP callers keep quota and soft-failure contracts with optional deadlines."""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.intel import McpClient, McpError
from src.intel.application import fetch
from src.intel.infrastructure import mcp, mcp_deadline
from src.ops import JobCancelled, JobTimedOut


@pytest.fixture
def calls(monkeypatch):
    client = McpClient(name="wudao", url="https://example.invalid")
    call = Mock(return_value={"text": "ok", "structured": {"rows": [1]}, "is_error": False})
    client.call_tool = call
    build = Mock(return_value=client)
    acquired, charged = Mock(return_value={}), Mock(return_value={})
    monkeypatch.setattr("src.intel.infrastructure.registry.build_client", build)
    monkeypatch.setattr(fetch, "wudao_availability", lambda: {"available": True})
    monkeypatch.setattr(fetch, "acquire_quota", acquired)
    monkeypatch.setattr(fetch, "record_quota_call", charged)
    monkeypatch.setattr(fetch, "quota_snapshot", lambda: {})
    return SimpleNamespace(client=client, call=call, build=build, acquired=acquired, charged=charged)


def invoke(calls, entry, **kwargs):
    if entry == "direct":
        return fetch.call_mcp_tool("kline", {}, server="wudao", **kwargs)
    return fetch.guarded_client_call(calls.client, "kline", {}, **kwargs)


@pytest.mark.parametrize("entry", ["direct", "guarded"])
@pytest.mark.parametrize("deadline", [None, 5])
def test_public_call_forwards_only_supplied_deadline_and_charges_once(calls, entry, deadline):
    options = {"deadline": time.monotonic() + deadline} if deadline is not None else {}
    result = invoke(calls, entry, **options)
    calls.call.assert_called_once_with("kline", {}, **options)
    calls.acquired.assert_called_once_with("skill", **options)
    calls.charged.assert_called_once_with("skill")
    assert result["structured"] == {"rows": [1]} and result["quota_charged"]
    assert calls.client.timeout == 60


@pytest.mark.parametrize("entry", ["direct", "guarded"])
@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, CancelledError, asyncio.CancelledError])
def test_deadline_cancellation_is_not_softened_or_charged(calls, entry, error_type):
    stop = error_type("original cancellation")

    def fail(*_args, **_kwargs):
        raise stop

    calls.call.side_effect = fail
    with pytest.raises(error_type) as caught:
        invoke(calls, entry, deadline=time.monotonic() + 5)
    assert caught.value is stop
    calls.charged.assert_not_called()


@pytest.mark.parametrize("entry", ["direct", "guarded"])
def test_expired_deadline_does_not_acquire_quota_or_dispatch(calls, entry):
    with pytest.raises(TimeoutError):
        invoke(calls, entry, deadline=time.monotonic() - 1)
    calls.acquired.assert_not_called()
    calls.build.assert_not_called()
    calls.call.assert_not_called()


@pytest.mark.parametrize("entry", ["direct", "guarded"])
def test_budget_spent_in_quota_wait_does_not_dispatch_transport(calls, entry, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(mcp_deadline.time, "monotonic", lambda: clock[0])
    calls.acquired.side_effect = lambda _pool, **_kwargs: clock.__setitem__(0, 106.0)
    with pytest.raises(TimeoutError):
        invoke(calls, entry, deadline=105.0)
    calls.call.assert_not_called()
    calls.charged.assert_not_called()


def test_ordinary_wudao_failure_is_still_soft_and_not_charged(calls):
    calls.call.side_effect = McpError("ordinary upstream failure")
    result = invoke(calls, "direct", deadline=time.monotonic() + 5)
    assert result["unavailable"] and result["is_error"]
    calls.charged.assert_not_called()


def test_without_deadline_wudao_legacy_soft_failure_is_unchanged(calls):
    calls.call.side_effect = TimeoutError("legacy upstream timeout")
    result = invoke(calls, "direct")
    assert result["unavailable"] and result["is_error"]
    calls.call.assert_called_once_with("kline", {})


@pytest.mark.parametrize("entry", ["direct", "guarded"])
def test_rejected_arguments_still_do_not_charge_quota(calls, entry):
    calls.call.return_value = {"text": "INVALID_ARGUMENTS", "is_error": True}
    result = invoke(calls, entry, deadline=time.monotonic() + 5)
    assert result["is_error"] and not result["quota_charged"]
    calls.charged.assert_not_called()


def test_deadline_transport_keeps_ssrf_dns_validation(monkeypatch):
    monkeypatch.setattr(mcp.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    http = Mock()
    monkeypatch.setattr(mcp_deadline.httpx2, "AsyncClient", http)
    with pytest.raises(McpError, match="内网"):
        McpClient(name="test", url="https://example.invalid").call_tool("kline", {}, deadline=time.monotonic() + 5)
    http.assert_not_called()


def test_slow_system_dns_can_finish_late_but_cannot_dispatch_http(monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    http = Mock()

    def dns(_url):
        started.set()
        release.wait(3)
        finished.set()
        return False

    monkeypatch.setattr(mcp_deadline, "_validated_proxy", dns)
    monkeypatch.setattr(mcp_deadline.httpx2, "AsyncClient", http)
    try:
        with pytest.raises(TimeoutError):
            McpClient(name="test", url="https://example.invalid").call_tool("kline", {}, deadline=time.monotonic() + 0.3)
        assert started.is_set() and not finished.is_set()
        http.assert_not_called()
    finally:
        release.set()
        assert finished.wait(2)
    http.assert_not_called()
