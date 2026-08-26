"""共享的 LLM tool schema 与无状态 MCP 调用包装。

Skill ``ToolBus`` 与助手 ``SystemToolBus`` 安全面不同，不合并总线；
仅复用 schema 形态与 ``guarded_client_call`` 的薄包装。
"""
from __future__ import annotations

from typing import Any


def tool_schema(
    protocol: str,
    name: str,
    description: str,
    parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    """统一 openai_compatible / anthropic 的 function-calling schema。"""
    desc = (description or name)[:1000]
    params = parameters or {"type": "object", "properties": {}}
    if protocol == "anthropic":
        return {"name": name, "description": desc, "input_schema": params}
    return {
        "type": "function",
        "function": {"name": name, "description": desc, "parameters": params},
    }


def mcp_tool_fullname(server: str, tool_name: str) -> str:
    """MCP 工具对外名：``server__tool``（无 server 时退回 tool）。"""
    return f"{server}__{tool_name}" if server else tool_name


# 权威实现在 intel 边界；此处再导出供既有测试/调用方兼容。
from src.intel import clamp_mcp_arguments as clamp_mcp_arguments


def invoke_mcp_tool(
    client: Any | None,
    *,
    server: str,
    full_name: str,
    arguments: dict[str, Any] | None = None,
    pool: str = "skill",
) -> dict[str, Any]:
    """无状态 MCP 调用：缺失 client 返回错误；``McpClient`` 走 guarded 池。"""
    if client is None:
        return {"text": f"MCP server {server} 不可用", "is_error": True}
    from src.intel import McpClient, guarded_client_call

    # clamp 已在 guarded_client_call / call_mcp_tool 再做一次；此处预裁便于非 McpClient 旁路
    args = clamp_mcp_arguments(arguments)
    if isinstance(client, McpClient):
        return guarded_client_call(client, full_name, args, pool=pool)
    return client.call_tool(full_name, args)
