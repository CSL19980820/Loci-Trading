"""Tenant-bound gRPC -> provider HTTP/2 gateway; no client-supplied URLs/keys.

Run standalone with LOCI_GRPC_LISTEN / LOCI_GRPC_TOKEN / LOCI_GRPC_TENANT,
through `python -m src.ai.infrastructure.grpc_gateway`, or use start_from_env
inside the ASGI lifespan. The gateway itself never executes tools or trades.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from pathlib import Path

import grpc
import httpx2

from src.ai.infrastructure import grpc_wire_pb2 as wire
from src.ai.infrastructure.grpc_wire_pb2_grpc import ModelGatewayServicer, add_ModelGatewayServicer_to_server
from src.ai.infrastructure.grpc_transport import OPTIONS
from src.ai.infrastructure.grpc_routing import tenant_gateway_token
from src.shared.http_protocol import http_protocol_options, record_http_protocol

logger = logging.getLogger(__name__)


class Gateway(ModelGatewayServicer):
    def __init__(self, token, resolve, *, client_factory=None, tenant_scoped=False):
        if len(token) < 32 or not token.isascii():
            raise ValueError("gRPC token must contain at least 32 ASCII characters")
        self.token = token
        self.resolve = resolve
        self.tenant_scoped = tenant_scoped
        self.client_factory = client_factory or httpx2.AsyncClient

    async def configuration(self, provider, context):
        metadata = list(context.invocation_metadata())
        supplied = [v for k, v in metadata if k == "authorization"]
        tenants = [v for k, v in metadata if k == "x-loci-tenant"]
        expected, tenant = self.token, None
        valid = len(supplied) == 1
        if self.tenant_scoped:
            valid = valid and len(tenants) == 1
            if valid:
                try:
                    tenant = tenants[0]
                    expected = tenant_gateway_token(self.token, tenant)
                except (ValueError, TypeError):
                    valid = False
        elif tenants:
            valid = False
        if not valid or not isinstance(supplied[0], str) or not supplied[0].isascii() or not hmac.compare_digest(supplied[0], "Bearer " + expected):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid gateway credential")
        try:
            args = (provider.name, provider.model, tenant) if self.tenant_scoped else (provider.name, provider.model)
            config = await asyncio.to_thread(self.resolve, *args)
            if config.protocol != provider.protocol or config.model != provider.model:
                raise ValueError("Provider contract mismatch")
            return config
        except Exception:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Provider configuration is unavailable or incompatible")

    async def Check(self, request, context):
        await self.configuration(request, context)
        return wire.Ready(ready=True)

    async def Exchange(self, request, context):
        config = await self.configuration(request.provider, context)
        try:
            body = json.loads(request.json_body)
            if not isinstance(body, dict) or body.get("model") != config.model:
                raise ValueError("Invalid model request")
            if not isinstance(body.get("messages"), list):
                raise ValueError("Messages are required")
        except (ValueError, TypeError, UnicodeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid generation payload")
        remaining = context.time_remaining()
        timeout = config.timeout if remaining is None else remaining
        if timeout <= 0:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Request deadline expired")
        kwargs = {"timeout": timeout, **http_protocol_options()}
        if config.proxy_url:
            kwargs["proxy"] = config.proxy_url
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
        if config.protocol == "anthropic":
            path = "/messages"
            headers.update({"x-api-key": config.api_key, "anthropic-version": "2023-06-01"})
        else:
            path = "/chat/completions"
            headers["Authorization"] = "Bearer " + config.api_key
        try:
            # aio cancellation unwinds both context managers, closing upstream even
            # while it is waiting for its first byte. No orphan model worker thread.
            async with self.client_factory(**kwargs) as client:
                async with client.stream("POST", config.base_url + path, headers=headers, json=body) as response:
                    record_http_protocol(response)
                    yield wire.Frame(headers=wire.ResponseHeaders(status=response.status_code,
                        content_type=response.headers.get("content-type", "application/json"),
                        upstream_http_version=response.http_version))
                    async for chunk in response.aiter_bytes():
                        # Keep individual gRPC messages bounded while preserving SSE bytes.
                        for offset in range(0, len(chunk), 65536):
                            yield wire.Frame(body=chunk[offset:offset + 65536])
        except httpx2.TimeoutException as exc:
            logger.warning("model_gateway_failure boundary=provider_http error_type=%s", type(exc).__name__)
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Provider timeout")
        except httpx2.TransportError as exc:
            logger.warning("model_gateway_failure boundary=provider_http error_type=%s", type(exc).__name__)
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Provider transport failed; do not replay")


async def start_gateway(listen, token, resolve, *, cert=None, key=None, client_factory=None, tenant_scoped=False):
    host = listen.rsplit(":", 1)[0].strip("[]")
    if not cert and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Unencrypted gRPC listener must be loopback")
    service = Gateway(token, resolve, client_factory=client_factory, tenant_scoped=tenant_scoped)
    server = grpc.aio.server(options=OPTIONS, maximum_concurrent_rpcs=16)
    add_ModelGatewayServicer_to_server(service, server)
    if cert and key:
        port = server.add_secure_port(listen, grpc.ssl_server_credentials(((key, cert),)))
    elif cert or key:
        raise ValueError("Both certificate and private key are required")
    else:
        port = server.add_insecure_port(listen)
    if not port:
        raise RuntimeError("gRPC listener failed to bind")
    await server.start()
    logger.info("gRPC gateway listening on %s (port %s)", listen, port)
    return server, port


async def start_from_env():
    listen = os.getenv("LOCI_GRPC_LISTEN", "").strip()
    if not listen:
        return None
    tenant = os.getenv("LOCI_GRPC_TENANT", "__primary__")
    tenant_scoped = os.getenv("LOCI_GRPC_MULTI_TENANT", "0") == "1"

    def resolve(name, model, authenticated_tenant=None):
        return resolve_tenant_provider(name, model, authenticated_tenant if tenant_scoped else tenant)

    cert_path, key_path = os.getenv("LOCI_GRPC_CERT", ""), os.getenv("LOCI_GRPC_KEY", "")
    server, _ = await start_gateway(listen, os.getenv("LOCI_GRPC_TOKEN", ""), resolve,
        tenant_scoped=tenant_scoped,
        cert=Path(cert_path).read_bytes() if cert_path else None,
        key=Path(key_path).read_bytes() if key_path else None)
    return server


def resolve_tenant_provider(name, model, tenant):
    from src.ai.infrastructure.providers import resolve_config
    from src.ops import OpsStore
    from src.shared.tenancy import tenant_scope
    from src.shared.paths import ops_db
    # This function is called only after tenant authentication. No empty DB creation.
    with tenant_scope(tenant):
        if not ops_db().is_file():
            raise ValueError("Tenant store does not exist")
        with OpsStore(None) as store:
            return resolve_config(store, name, model=model, use_grpc=False)


async def main():
    server = await start_from_env()
    if server is None:
        raise ValueError("Set LOCI_GRPC_LISTEN, LOCI_GRPC_TOKEN and LOCI_GRPC_TENANT first")
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
