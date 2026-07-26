"""MCP server 的注册、鉴权与工具解析。

token 与 LLM API Key 走同一套加密：主密钥在环境变量、密文在 ops.db，
AAD 绑定 server id，密文被搬到另一行就解不开。
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from src.ai.crypto import decrypt_secret, encrypt_secret, mask_secret
from src.intel.mcp import McpClient, McpError, McpTool
from src.ops.store import OpsError, OpsStore, new_id

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_server(
    store: OpsStore,
    *,
    name: str,
    url: str,
    token: str | None = None,
    proxy_url: str = "",
    note: str = "",
    verify: bool = True,
    master_key: str | None = None,
) -> dict[str, Any]:
    """注册或更新一个 MCP server。

    verify=True 时会当场握手并拉一次工具列表——配置错误应该在保存时暴露，
    而不是等到某个半夜的定时任务失败。
    """
    name = name.strip()
    if not name:
        raise OpsError("server 名称不能为空")
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise OpsError("URL 必须以 http:// 或 https:// 开头")

    existing = store.get_mcp_server(name, include_secret=True)
    server_id = existing["id"] if existing else new_id("MCP")

    encrypted: bytes | None = None
    last4 = ""
    if token:
        encrypted = encrypt_secret(token.strip(), aad=server_id, master_key=master_key)
        last4 = mask_secret(token.strip())
    plaintext = token.strip() if token else _decrypt(existing, master_key)

    tools: list[dict[str, Any]] = existing.get("tools", []) if existing else []
    synced_at = existing.get("tools_synced_at", "") if existing else ""
    if verify:
        client = McpClient(name=name, url=url, token=plaintext, proxy_url=proxy_url)
        try:
            discovered = client.list_tools()
        except McpError as exc:
            # 校验不过绝不落库：宁可当场让人改，也别留一个半死的配置。
            raise OpsError(f"MCP server 连接失败，未保存：{exc}") from exc
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in discovered
        ]
        synced_at = _now()

    store.upsert_mcp_server(
        {
            "id": server_id, "name": name, "url": url,
            "encrypted_token": encrypted, "token_last4": last4,
            "proxy_url": proxy_url, "tools": tools, "tools_synced_at": synced_at,
            "is_active": True, "note": note,
        }
    )
    saved = store.get_mcp_server(name)
    if saved is None:  # pragma: no cover
        raise OpsError("保存后读取失败")
    return saved


def _decrypt(existing: dict[str, Any] | None, master_key: str | None) -> str:
    """没有 token 的 server 也允许存在——有些 MCP server 是公开的。"""
    if not existing or not existing.get("encrypted_token"):
        return ""
    return decrypt_secret(
        existing["encrypted_token"], aad=existing["id"], master_key=master_key
    )


def build_client(
    store: OpsStore, name_or_id: str, *, master_key: str | None = None
) -> McpClient:
    record = store.get_mcp_server(name_or_id, include_secret=True)
    if record is None:
        raise OpsError(f"未注册的 MCP server：{name_or_id}")
    if not record.get("is_active"):
        raise OpsError(f"MCP server {record['name']} 已停用")
    return McpClient(
        name=record["name"],
        url=record["url"],
        token=_decrypt(record, master_key),
        proxy_url=record.get("proxy_url", ""),
    )


def refresh_tools(
    store: OpsStore, name_or_id: str, *, master_key: str | None = None
) -> list[dict[str, Any]]:
    """重新发现工具。上游上新工具后不必删了重配。"""
    client = build_client(store, name_or_id, master_key=master_key)
    record = store.get_mcp_server(name_or_id)
    if record is None:
        raise OpsError(f"未注册的 MCP server：{name_or_id}")
    tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in client.list_tools()
    ]
    store.upsert_mcp_server(
        {
            "id": record["id"], "name": record["name"], "url": record["url"],
            "encrypted_token": None, "proxy_url": record.get("proxy_url", ""),
            "tools": tools, "tools_synced_at": _now(),
            "is_active": record["is_active"], "note": record.get("note", ""),
        }
    )
    return tools


def collect_tools(
    store: OpsStore,
    server_names: list[str] | None = None,
    *,
    allow: list[str] | None = None,
) -> tuple[list[McpTool], dict[str, str]]:
    """汇总可用工具，并给出"带前缀的工具名 → server 名"的路由表。

    allow 用来把工具面收窄到技能包声明的那几个：一个 server 有 63 个工具，
    全塞进 system prompt 会占掉大量上下文，而多数技能只需要三五个。
    """
    wanted = set(allow or [])
    tools: list[McpTool] = []
    routing: dict[str, str] = {}

    for record in store.list_mcp_servers(active_only=True):
        if server_names and record["name"] not in server_names:
            continue
        for item in record.get("tools", []):
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
