"""Use a real local RPC stream to distinguish inactivity from total lifetime."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import grpc
import httpx2
import pytest

from src.ai.infrastructure import grpc_wire_pb2 as wire
from src.ai.infrastructure.grpc_wire_pb2_grpc import ModelGatewayServicer, add_ModelGatewayServicer_to_server
from src.ai.infrastructure.client import ChatMessage, LLMError, ProviderConfig
from src.ai.infrastructure.client_stream import chat_stream
from src.ai.infrastructure.grpc_transport import request_timeout
from src.ai.infrastructure.stream_deadline import FirstResponseTimeout


@contextmanager
def gateway(mode="normal"):
    class Gateway(ModelGatewayServicer):
        calls = 0
        remaining = 0

        def Check(self, request, context):
            return wire.Ready(ready=True)

        def Exchange(self, request, context):
            self.calls += 1
            self.remaining = context.time_remaining()
            yield wire.Frame(headers=wire.ResponseHeaders(status=200, content_type="text/event-stream"))
            for index in range(12):
                if not context.is_active():
                    return
                if mode == "idle" and index == 1:
                    time.sleep(0.4)
                else:
                    time.sleep(0.04)
                if mode == "heartbeat":
                    yield wire.Frame(body=b": heartbeat\n\n")
                else:
                    row = {"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
                    yield wire.Frame(body=("data: " + json.dumps(row) + "\n\n").encode())
            yield wire.Frame(body=b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')

    service = Gateway()
    with ThreadPoolExecutor(max_workers=2) as pool:
        server = grpc.server(pool)
        add_ModelGatewayServicer_to_server(service, server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            yield ProviderConfig(name="fixture", protocol="openai_compatible", base_url="http://fixture.invalid/v1",
                                 api_key="fixture", model="fixture", timeout=0.2,
                                 grpc_endpoint=f"http://127.0.0.1:{port}"), service
        finally:
            server.stop(0).wait()


def causes(exc):
    chain = []
    while exc and exc not in chain:
        chain.append(exc)
        exc = exc.__cause__
    return chain


def test_active_stream_outlives_read_timeout_without_replay():
    with gateway() as (config, service):
        started = time.monotonic()
        result = chat_stream(config, [ChatMessage(role="user", content="test")],
                             first_response_timeout=0.3, deadline=started + 2)
        assert result.text == "x" * 12
        assert time.monotonic() - started > config.timeout
        assert service.remaining > 1
        assert service.calls == 1


def test_heartbeat_does_not_satisfy_first_response_deadline():
    with gateway("heartbeat") as (config, service):
        with pytest.raises(LLMError) as error:
            chat_stream(config, [ChatMessage(role="user", content="test")],
                        first_response_timeout=0.15, deadline=time.monotonic() + 2)
        assert any(isinstance(e, FirstResponseTimeout) for e in causes(error.value))
        assert service.calls == 1


def test_total_deadline_is_terminal_even_with_active_stream():
    from src.ai.application.agent import run_agent
    with gateway() as (config, service):
        with pytest.raises(TimeoutError):
            run_agent(config, system="test", user_prompt="test", retry_stream_failures=True,
                      recover_interrupted_generation=True, deadline=time.monotonic() + 0.25)
        assert service.calls == 1


def test_read_inactivity_still_times_out():
    with gateway("idle") as (config, service):
        with pytest.raises(LLMError) as error:
            chat_stream(config, [ChatMessage(role="user", content="test")],
                        first_response_timeout=0.15, deadline=time.monotonic() + 2)
        assert any(isinstance(e, httpx2.ReadTimeout) for e in causes(error.value))
        assert service.calls == 1


def test_rpc_without_run_deadline_preserves_configured_timeout():
    config = ProviderConfig(name="fixture", protocol="openai_compatible", base_url="http://fixture.invalid", api_key="", timeout=120)
    request = httpx2.Request("POST", config.base_url, extensions={"timeout": {"read": 90, "connect": 30}})
    assert request_timeout(request, config) == 30
    request.extensions["loci_deadline"] = time.monotonic() - 1
    with pytest.raises(TimeoutError):
        request_timeout(request, config)
