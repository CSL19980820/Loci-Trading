"""MCP路由与工具轨迹格式化，保留agent模块的公开兼容导出。"""
from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from src.ai.application.agent_execution import ToolInvocation

def make_mcp_executor(
    clients: dict[str, Any], routing: dict[str, str]
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """把「带 server 前缀的工具名」路由到对应的 MCP 客户端。"""

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = routing.get(name)
        if server is None:
            available = ", ".join(sorted(routing)[:15])
            return {
                "text": f"没有名为 {name} 的工具。可用工具：{available}",
                "is_error": True,
            }
        client = clients.get(server)
        if client is None:
            return {"text": f"MCP server {server} 不可用", "is_error": True}
        from src.intel import McpClient, guarded_client_call

        if isinstance(client, McpClient):
            return guarded_client_call(client, name, arguments, pool="skill")
        return client.call_tool(name, arguments)

    return execute


def format_tool_trace(invocations: list[ToolInvocation]) -> str:
    """把工具调用过程压成可读文本，放进执行记录。"""
    if not invocations:
        return "（本次未调用任何工具）"
    lines = []
    for index, call in enumerate(invocations, 1):
        mark = "✓" if call.ok else "✗"
        args = json.dumps(call.arguments, ensure_ascii=False)[:160]
        lines.append(f"{index}. {mark} {call.name}({args}) {call.elapsed_ms}ms")
        if not call.ok:
            lines.append(f"   错误：{call.error[:200]}")
    return "\n".join(lines)
