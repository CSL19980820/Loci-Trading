"""把 data/mcp.json（及内置行情 MCP）默认挂进全局助手工具面。"""
from __future__ import annotations

import logging
import os
from typing import Any

from src.ai.application.system_toolbus import ToolSpec, _object
from src.ai.application.tool_schema import invoke_mcp_tool, mcp_tool_fullname
from src.shared.observability import current as current_observation
from src.shared.observability import span as observation_span

logger = logging.getLogger(__name__)

MAX_MCP_TOOLS = 48


def _mcp_timeout_seconds() -> float | None:
    raw = os.environ.get("LOCI_MCP_TOOL_TIMEOUT_SEC", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return min(max(value, 0.1), 600.0)


def mount_default_mcp(bus: Any) -> dict[str, str]:
    """向 ``bus._specs`` 追加 MCP 工具；返回 full_name → server 路由。"""
    routing: dict[str, str] = {}
    try:
        from src.intel import build_client, collect_tools
    except ImportError as exc:
        logger.warning("MCP 不可用：%s", exc)
        return routing

    try:
        tools, tool_routing = collect_tools(None, allow=None)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        logger.warning("收集 MCP 工具失败：%s", exc)
        return routing

    clients: dict[str, Any] = {}
    for server in {tool.server for tool in tools if tool.server}:
        try:
            clients[server] = build_client(server)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            logger.warning("MCP server %s 不可用：%s", server, exc)

    attached = 0
    for tool in tools:
        if attached >= MAX_MCP_TOOLS:
            break
        server = tool.server or ""
        if not server or server not in clients:
            continue
        full = mcp_tool_fullname(server, tool.name)
        if full in bus._specs or tool.name in bus._specs:
            continue

        def make_handler(fname: str = full, srv: str = server) -> Any:
            def _run(arguments: dict[str, Any]) -> dict[str, Any]:
                inherited = current_observation()
                with observation_span(
                    "mcp.invoke",
                    trace_id=inherited.trace_id,
                    run_id=inherited.run_id,
                    job_id=inherited.job_id,
                    tool_receipt_id=inherited.tool_receipt_id,
                    source_id=srv,
                    labels={"component": "mcp", "operation": "call", "protocol": "mcp"},
                ):
                    return invoke_mcp_tool(
                        clients.get(srv),
                        server=srv,
                        full_name=fname,
                        arguments=arguments,
                    )

            return _run

        schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
        if schema.get("type") != "object":
            schema = _object(
                schema.get("properties") if isinstance(schema.get("properties"), dict) else {},
                schema.get("required") if isinstance(schema.get("required"), list) else None,
            )
        elif "additionalProperties" not in schema:
            schema = {**schema, "additionalProperties": False}
        bus._specs[full] = ToolSpec(
            full,
            (tool.description or f"MCP {server}/{tool.name}")[:400],
            schema,
            False,
            make_handler(),
            allow_urls=True,
            timeout_seconds=_mcp_timeout_seconds(),
        )
        routing[full] = tool_routing.get(full, server)
        attached += 1

    bus._mcp_attached = attached
    bus._mcp_routing = routing
    return routing
