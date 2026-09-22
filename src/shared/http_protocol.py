"""HTTP/2 preferred, HTTP/1.1 negotiated compatibility; never replay a request."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def http_protocol_options() -> dict[str, bool]:
    # Operational rollback only; TLS verification and proxy policy stay unchanged.
    return {"http1": True, "http2": os.getenv("LOCI_HTTP2", "1").strip().lower() not in {"0", "false", "off"}}


def record_http_protocol(response) -> None:
    request = response.request
    logger.info("upstream_http host=%s version=%s status=%s transport=%s gateway_upstream=%s", request.url.host,
                response.http_version, response.status_code,
                response.extensions.get("loci_transport", b"http").decode(),
                response.extensions.get("upstream_http_version", b"direct").decode())


async def record_async_http_protocol(response) -> None:
    record_http_protocol(response)
