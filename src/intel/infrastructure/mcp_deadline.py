"""Optional wall-clock MCP transport budget without mutating client defaults."""
from __future__ import annotations

import math
import time
from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

import anyio
import httpx2
from anyio.from_thread import start_blocking_portal

_DEADLINE: ContextVar[float | None] = ContextVar("mcp_transport_deadline", default=None)
_CLOSE_GRACE_SECONDS = 0.125


def active_deadline() -> float | None:
    return _DEADLINE.get()


def remaining_seconds(deadline: float) -> float:
    if isinstance(deadline, bool) or not math.isfinite(deadline):
        raise ValueError("MCP deadline must be a finite monotonic timestamp")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("MCP transport deadline exceeded")
    return remaining


def check_deadline(deadline: float | None) -> None:
    if deadline is not None:
        remaining_seconds(deadline)


@contextmanager
def deadline_scope(deadline: float) -> Iterator[None]:
    outer = active_deadline()
    effective = min(outer, deadline) if outer is not None else deadline
    remaining_seconds(effective)
    token = _DEADLINE.set(effective)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def reraise_stop(error: BaseException) -> None:
    from src.ops import JobCancelled, JobTimedOut

    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, (TimeoutError, CancelledError, AsyncCancelledError, JobCancelled, JobTimedOut)):
            raise cause
        seen.add(id(cause))
        cause = cause.__cause__


def _validated_proxy(url: str) -> bool:
    from src.intel.infrastructure.mcp import needs_system_proxy, validate_mcp_url

    validate_mcp_url(url, resolve=True)
    return needs_system_proxy(url)


async def _close_transport(upstream: Any, http: Any) -> BaseException | None:
    failure = None
    for resource in (upstream, http):
        if resource is None:
            continue
        try:
            with anyio.move_on_after(_CLOSE_GRACE_SECONDS, shield=True) as scope:
                await resource.aclose()
            if scope.cancel_called and failure is None:
                failure = TimeoutError("MCP transport cleanup exceeded its grace period")
        except BaseException as exc:
            if failure is None:
                failure = exc
    return failure


async def _request(client: Any, body: dict[str, Any], deadline: float, read_body: bool) -> Any:
    from src.intel.infrastructure.mcp import MAX_RESPONSE_BYTES, McpError, _BufferedResponse

    with anyio.fail_after(remaining_seconds(deadline)):
        # DNS can block in the system resolver; abandon only that read, never dispatch HTTP afterwards.
        trust_env = await anyio.to_thread.run_sync(_validated_proxy, client.url, abandon_on_cancel=True)
        timeout = min(client.timeout, remaining_seconds(deadline))
        http = httpx2.AsyncClient(timeout=timeout, trust_env=trust_env, follow_redirects=False)
        upstream = None
        failure = None
        try:
            request = http.build_request("POST", client.url, headers=client._headers(), json=body)
            upstream = await http.send(request, stream=True)
            chunks: list[bytes] = []
            size = 0
            if read_body:
                async for chunk in upstream.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise McpError(f"{client.name} 响应过大，超过 {MAX_RESPONSE_BYTES} 字节上限")
                    chunks.append(chunk)
            return _BufferedResponse(upstream.status_code,
                                     {str(k).lower(): str(v) for k, v in upstream.headers.items()},
                                     b"".join(chunks).decode("utf-8", errors="replace"))
        except BaseException as exc:
            failure = exc
            raise
        finally:
            # Close both resources with at most 250ms of grace; a cleanup error cannot replace a stop.
            cleanup_failure = await _close_transport(upstream, http)
            if failure is None and cleanup_failure is not None:
                raise cleanup_failure


async def _request_outcome(client: Any, body: dict[str, Any], deadline: float, read_body: bool) -> Any:
    try:
        return await _request(client, body, deadline, read_body)
    except BaseException as exc:
        # A portal otherwise replaces asyncio cancellation with a new Future cancellation object.
        return exc


def deadline_request(client: Any, body: dict[str, Any], *, read_body: bool = True) -> Any:
    deadline = active_deadline()
    if deadline is None:
        raise RuntimeError("MCP deadline transport requires a scoped deadline")
    remaining_seconds(deadline)
    # A short-lived portal also works when this synchronous API is called from an active event loop.
    with start_blocking_portal(name="mcp-deadline") as portal:
        result = portal.call(_request_outcome, client, body, deadline, read_body)
    if isinstance(result, BaseException):
        raise result
    remaining_seconds(deadline)
    return result
