"""MCP server 的注册、鉴权与工具解析。

唯一配置面：``data/mcp.json``（Cursor 兼容）。运维页增删改都写回该文件，
不再使用 ops.db 的 ``mcp_servers`` 表。
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from src.intel.infrastructure.builtin_market_mcp import (
    BUILTIN_MCP_NAME,
    InProcessMcpClient,
    builtin_server_record,
    is_builtin_mcp_server,
    list_builtin_tools,
)
from src.intel.infrastructure.mcp import McpClient, McpError, McpTool
from src.intel.infrastructure.mcp_config import (
    delete_mcp_server_json,
    get_mcp_server_from_json,
    list_mcp_servers_from_json,
    set_mcp_server_active_json,
    update_mcp_server_tools_json,
    upsert_mcp_server_json,
)
from src.ops import OpsError

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_server(
    *,
    name: str,
    url: str,
    token: str | None = None,
    proxy_url: str = "",
    note: str = "",
    verify: bool = True,
) -> dict[str, Any]:
    """注册或更新一个 MCP server 到 mcp.json。

    verify=True 时会当场握手并拉一次工具列表——配置错误应该在保存时暴露。
    token=None 表示保留原有 Authorization；传空字符串可清空。
    """
    name = name.strip()
    if not name:
        raise OpsError("server 名称不能为空")
    if is_builtin_mcp_server(name):
        raise OpsError(f"{BUILTIN_MCP_NAME} 为内置 server，不可通过 mcp.json 注册或覆盖")
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise OpsError("URL 必须以 http:// 或 https:// 开头")

    existing = get_mcp_server_from_json(name)
    plaintext = token.strip() if token else (existing.get("token") if existing else "")
    tools: list[dict[str, Any]] = list(existing.get("tools") or []) if existing else []
    synced_at = str(existing.get("tools_synced_at") or "") if existing else ""

    if verify:
        client = McpClient(
            name=name,
            url=url,
            token=str(plaintext or ""),
            proxy_url=proxy_url,
        )
        try:
            discovered = client.list_tools()
        except McpError as exc:
            raise OpsError(f"MCP server 连接失败，未保存：{exc}") from exc
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in discovered
        ]
        synced_at = _now()

    saved = upsert_mcp_server_json(
        name=name,
        url=url,
        token=token,
        proxy_url=proxy_url,
        note=note,
        tools=tools,
        tools_synced_at=synced_at,
    )
    return _public(saved)


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in record.items()
        if k not in {"token", "encrypted_token", "raw", "headers"}
    }


def build_client(name_or_id: str) -> McpClient | InProcessMcpClient:
    if is_builtin_mcp_server(name_or_id):
        return InProcessMcpClient()
    record = get_mcp_server_from_json(name_or_id)
    if record is None:
        raise OpsError(f"未注册的 MCP server：{name_or_id}（检查 data/mcp.json）")
    if not record.get("is_active", True):
        raise OpsError(f"MCP server {record['name']} 已停用（mcp.json）")
    return McpClient(
        name=record["name"],
        url=record["url"],
        token=str(record.get("token") or ""),
        proxy_url=record.get("proxy_url", ""),
    )


def refresh_tools(name_or_id: str) -> list[dict[str, Any]]:
    """重新发现工具并写回 mcp.json。"""
    if is_builtin_mcp_server(name_or_id):
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in list_builtin_tools()
        ]
    client = build_client(name_or_id)
    record = get_mcp_server_from_json(name_or_id)
    if record is None:
        raise OpsError(f"未注册的 MCP server：{name_or_id}")
    tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in client.list_tools()
    ]
    update_mcp_server_tools_json(record["name"], tools, tools_synced_at=_now())
    return tools


def set_server_active(name: str, active: bool) -> dict[str, Any]:
    if is_builtin_mcp_server(name):
        raise OpsError(f"内置 MCP server {BUILTIN_MCP_NAME} 不可停用")
    try:
        return _public(set_mcp_server_active_json(name, active))
    except KeyError as exc:
        raise OpsError(f"未注册的 MCP server：{name}") from exc


def delete_server(name: str) -> bool:
    if is_builtin_mcp_server(name):
        raise OpsError(f"内置 MCP server {BUILTIN_MCP_NAME} 不可删除")
    return delete_mcp_server_json(name)


def list_effective_mcp_servers(*, active_only: bool = True) -> list[dict[str, Any]]:
    rows = [
        row
        for row in list_mcp_servers_from_json()
        if row.get("name") != BUILTIN_MCP_NAME
    ]
    if active_only:
        rows = [row for row in rows if row.get("is_active", True)]
    builtin = _public(builtin_server_record())
    merged = [builtin] + rows
    return sorted(merged, key=lambda item: str(item["name"]))


def collect_tools(
    server_names: list[str] | None = None,
    *,
    allow: list[str] | None = None,
) -> tuple[list[McpTool], dict[str, str]]:
    """汇总可用工具，并给出「带前缀的工具名 → server 名」的路由表。"""
    wanted = set(allow or [])
    tools: list[McpTool] = []
    routing: dict[str, str] = {}

    for record in list_effective_mcp_servers(active_only=True):
        if server_names and record["name"] not in server_names:
            continue
        for item in record.get("tools", []) or []:
            name = str(item.get("name", ""))
            if not name or (wanted and name not in wanted):
                continue
            tool = McpTool(
                name=name,
                description=str(item.get("description", "")),
                input_schema=item.get("input_schema") or {},
                server=record["name"],
            )
            tools.append(tool)
            routing[f"{record['name']}__{name}"] = record["name"]
    return tools, routing
