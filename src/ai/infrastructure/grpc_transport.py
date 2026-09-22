"""Optional real gRPC transport for the tenant-bound Loci model gateway.

Only the unbilled Check RPC may fall back to HTTP. Never replay Exchange after
submission, including an error before the first response header or SSE delta.
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

import grpc
import httpx2

from src.ai.infrastructure import grpc_wire_pb2 as wire
from src.ai.infrastructure.grpc_wire_pb2_grpc import ModelGatewayStub
from src.ai.infrastructure.client import LLMNoReplayError, LLMGenerationInterrupted
from src.shared.http_protocol import http_protocol_options

logger = logging.getLogger(__name__)
OPTIONS = (("grpc.max_send_message_length", 32 * 1024 * 1024),
           ("grpc.max_receive_message_length", 32 * 1024 * 1024),
           ("grpc.enable_retries", 0))
PREFLIGHT_UNAVAILABLE = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}


def channel_for(config, *, asynchronous=False):
    target = urlsplit(config.grpc_endpoint)
    if target.scheme not in {"http", "https"} or not target.hostname or not target.port:
        raise ValueError("gRPC endpoint requires http[s]://host:port")
    if target.username or target.password or target.path not in {"", "/"} or target.query or target.fragment:
        raise ValueError("gRPC endpoint must not contain credentials, path, query or fragment")
    api = grpc.aio if asynchronous else grpc
    if target.scheme == "http":
        if target.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Plaintext gRPC is restricted to loopback; use TLS remotely")
        return api.insecure_channel(target.netloc, options=OPTIONS)
    ca = Path(config.grpc_ca_file).read_bytes() if config.grpc_ca_file else None
    return api.secure_channel(target.netloc, grpc.ssl_channel_credentials(root_certificates=ca), options=OPTIONS)


def provider(config):
    return wire.Provider(name=config.name, model=config.model, protocol=config.protocol)


def request_metadata(config):
    from src.shared.tenancy import current_tenant
    metadata = (("authorization", "Bearer " + config.grpc_token),)
    if config.grpc_tenant:
        if current_tenant() != config.grpc_tenant:
            raise LLMNoReplayError("gRPC模型配置不属于当前租户")
        metadata += (("x-loci-tenant", config.grpc_tenant),)
    return metadata


def request_timeout(request, config):
    values = [v for v in request.extensions.get("timeout", {}).values() if isinstance(v, (int, float)) and v > 0]
    return min(values) if values else config.timeout


def native_only(request):
    return request.method != "POST" or not request.url.path.endswith(("/chat/completions", "/messages"))


def fail(exc):
    # Do not expose peer details: upstream gateways can put sensitive data there.
    code = exc.code().name if isinstance(exc, grpc.RpcError) else type(exc).__name__
    error = LLMGenerationInterrupted if code in {"UNAVAILABLE", "DEADLINE_EXCEEDED"} else LLMNoReplayError
    return error(f"gRPC模型链路失败（{code}）；本次传输未重放请求")


def response_from(first, stream):
    if first.WhichOneof("payload") != "headers":
        raise LLMNoReplayError("gRPC模型链路缺少响应头；未重放请求")
    return httpx2.Response(first.headers.status,
        headers={"content-type": first.headers.content_type}, stream=stream,
        extensions={"http_version": b"HTTP/2", "loci_transport": b"grpc",
                    "upstream_http_version": first.headers.upstream_http_version.encode()})


class _SyncBody(httpx2.SyncByteStream):
    def __init__(self, call):
        self.call = call

    def __iter__(self):
        try:
            for frame in self.call:
                if frame.WhichOneof("payload") != "body":
                    raise LLMNoReplayError("gRPC流返回了重复响应头")
                yield frame.body
        except grpc.RpcError as exc:
            raise fail(exc) from None

    def close(self):
        self.call.cancel()


class GrpcTransport(httpx2.BaseTransport):
    def __init__(self, config):
        self.config = config
        self.channel = channel_for(config)
        self.stub = ModelGatewayStub(self.channel)
        self.fallback = httpx2.HTTPTransport(proxy=config.proxy_url or None, **http_protocol_options())

    def handle_request(self, request):
        metadata = request_metadata(self.config)
        if native_only(request):
            return self.fallback.handle_request(request)
        timeout = request_timeout(request, self.config)
        try:
            ready = self.stub.Check(provider(self.config), timeout=min(2, timeout), metadata=metadata)
            if not ready.ready:
                raise LLMNoReplayError("gRPC网关未就绪")
        except grpc.RpcError as exc:
            if self.config.grpc_fallback and exc.code() in PREFLIGHT_UNAVAILABLE:
                logger.warning("grpc_preflight_unavailable fallback=http")
                return self.fallback.handle_request(request)
            raise fail(exc) from None
        call = self.stub.Exchange(wire.ModelRequest(provider=provider(self.config), json_body=request.read()),
                                  timeout=timeout, metadata=metadata)
        try:
            return response_from(next(call), _SyncBody(call))
        except (grpc.RpcError, StopIteration) as exc:
            call.cancel()
            raise fail(exc) from None
        except BaseException:
            call.cancel()
            raise

    def close(self):
        self.channel.close()
        self.fallback.close()


class _AsyncBody(httpx2.AsyncByteStream):
    def __init__(self, call):
        self.call = call

    async def __aiter__(self):
        try:
            while True:
                frame = await self.call.read()
                if frame is grpc.aio.EOF:
                    return
                if frame.WhichOneof("payload") != "body":
                    raise LLMNoReplayError("gRPC流返回了重复响应头")
                yield frame.body
        except grpc.RpcError as exc:
            raise fail(exc) from None

    async def aclose(self):
        self.call.cancel()


class AsyncGrpcTransport(httpx2.AsyncBaseTransport):
    def __init__(self, config):
        self.config = config
        self.channel = channel_for(config, asynchronous=True)
        self.stub = ModelGatewayStub(self.channel)
        self.fallback = httpx2.AsyncHTTPTransport(proxy=config.proxy_url or None, **http_protocol_options())

    async def handle_async_request(self, request):
        metadata = request_metadata(self.config)
        if native_only(request):
            return await self.fallback.handle_async_request(request)
        timeout = request_timeout(request, self.config)
        try:
            ready = await self.stub.Check(provider(self.config), timeout=min(2, timeout), metadata=metadata)
            if not ready.ready:
                raise LLMNoReplayError("gRPC网关未就绪")
        except grpc.RpcError as exc:
            if self.config.grpc_fallback and exc.code() in PREFLIGHT_UNAVAILABLE:
                logger.warning("grpc_preflight_unavailable fallback=http")
                return await self.fallback.handle_async_request(request)
            raise fail(exc) from None
        call = self.stub.Exchange(wire.ModelRequest(provider=provider(self.config), json_body=await request.aread()),
                                  timeout=timeout, metadata=metadata)
        try:
            first = await call.read()
            if first is grpc.aio.EOF:
                raise LLMNoReplayError("gRPC响应为空；未重放请求")
            return response_from(first, _AsyncBody(call))
        except grpc.RpcError as exc:
            call.cancel()
            raise fail(exc) from None
        except BaseException:
            call.cancel()
            raise

    async def aclose(self):
        await self.channel.close()
        await self.fallback.aclose()
