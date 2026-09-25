"""Bound streaming waits by wall time while keeping callbacks on the caller thread."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import time

import httpx2

from src.ai.infrastructure.client_session import borrow_client
from src.ai.infrastructure.connection_retry import status_retry_delay
from src.shared.http_protocol import http_protocol_options, record_http_protocol


@contextmanager
def _async_client(config):
    # AsyncClient 与 Runner 同寿命，不能把连接带到另一个事件循环。
    with asyncio.Runner() as runner:
        kwargs = {"timeout": config.timeout, **http_protocol_options()}
        if config.grpc_endpoint:
            from src.ai.infrastructure.grpc_transport import AsyncGrpcTransport
            kwargs.update(transport=AsyncGrpcTransport(config), trust_env=False)
        elif config.proxy_url:
            kwargs["proxy"] = config.proxy_url
        client = httpx2.AsyncClient(**kwargs)
        try:
            yield runner, client
        finally:
            runner.run(client.aclose())


class FirstResponseTimeout(httpx2.ReadTimeout):
    """No text, reasoning or tool-call delta arrived before the first-response deadline."""


class DeadlineStreamClient:
    def __init__(self, config, seconds, deadline, on_delta):
        self.config = config
        self.started = time.monotonic()
        self.first_deadline = self.started + seconds if seconds is not None else None
        self.deadline = deadline
        self.on_delta = on_delta
        self.received = False

    def status(self, phase, **details):
        if self.on_delta and self.first_deadline is not None:
            self.on_delta("stream_status", json.dumps({"phase": phase,
                "request_elapsed_ms": int((time.monotonic() - self.started) * 1000), **details}))

    def delta(self, kind, value):
        if value and kind in {"think", "token", "tool_delta"} and not self.received:
            self.received = True
            self.status("first_semantic", kind=kind)
        if self.on_delta:
            self.on_delta(kind, value)

    async def bounded(self, awaitable):
        end = self.deadline
        first = (not self.received and self.first_deadline is not None
                 and (end is None or self.first_deadline < end))
        if first:
            end = self.first_deadline
        try:
            async with asyncio.timeout(None if end is None else max(0, end - time.monotonic())):
                return await awaitable
        except TimeoutError as exc:
            self.status("first_response_timeout" if first else "request_deadline")
            if first:
                raise FirstResponseTimeout("no semantic stream response before deadline") from None
            raise TimeoutError("agent request deadline exceeded") from exc

    def __enter__(self):
        self._lease = borrow_client(self.config, lambda: _async_client(self.config), kind="async")
        self.runner, self.client = self._lease.__enter__()
        return self

    def __exit__(self, *args):
        return self._lease.__exit__(*args)

    @contextmanager
    def stream(self, *args, **kwargs):
        kwargs.setdefault("timeout", self.config.timeout)
        if self.deadline is not None:
            # HTTP read timeout measures inactivity; an RPC deadline covers the
            # entire stream. Carry the run deadline separately across the adapter.
            kwargs["extensions"] = {**kwargs.get("extensions", {}), "loci_deadline": self.deadline}
        async def open_response():
            connect_failures = 0
            status_retries = 0
            while True:
                try:
                    response = await self.client.send(self.client.build_request(*args, **kwargs), stream=True)
                except (httpx2.ConnectError, httpx2.ConnectTimeout):
                    connect_failures += 1
                    if connect_failures > 2:
                        raise
                    await asyncio.sleep(connect_failures)
                    continue
                # 429/503/529 表示上游拒收、未开始生成；有限重放，且不把剩余期限睡光。
                budget = None if self.deadline is None else self.deadline - time.monotonic() - 5
                delay = status_retry_delay(response, status_retries, budget=budget)
                if delay is None:
                    return response
                status_retries += 1
                await response.aclose()
                self.status("upstream_retry", status_code=response.status_code, attempt=status_retries + 1)
                await asyncio.sleep(delay)
        response = self.runner.run(self.bounded(open_response()))
        try:
            self.status_code = response.status_code
            self.response = response
            self.extensions = response.extensions
            record_http_protocol(response)
            self.status("response_headers", status_code=response.status_code, http_version=response.http_version)
            yield self
        finally:
            self.runner.run(response.aclose())

    def read(self):
        return self.runner.run(self.bounded(self.response.aread()))

    def iter_lines(self):
        iterator = self.response.aiter_lines()
        first_line = True
        try:
            while True:
                try:
                    line = self.runner.run(self.bounded(anext(iterator)))
                except StopAsyncIteration:
                    return
                if first_line:
                    self.status("first_stream_line")
                    first_line = False
                yield line
        finally:
            async def finish():
                # SSE [DONE] can precede the HTTP terminator. Exhaust the iterator,
                # or cancel its active read, before Runner closes nested generators.
                try:
                    async with asyncio.timeout(0.1):
                        async for _ in iterator:
                            pass
                except (TimeoutError, httpx2.TransportError):
                    pass
                finally:
                    await iterator.aclose()
            self.runner.run(finish())
