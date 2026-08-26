"""MCP server 的注册、鉴权与工具解析。

唯一配置面：``data/mcp.json``（Cursor 兼容）。运维页增删改都写回该文件，
不再使用 ops.db 的 ``mcp_servers`` 表。
"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
import logging
import time
from typing import Any

from src.intel.infrastructure.builtin_wudao_mcp import (
    BUILTIN_WUDAO_NAME,
    is_resident_wudao_server,
    resident_wudao_record,
)
from src.intel.infrastructure.mcp import McpClient, McpError, McpTool, validate_mcp_url
from src.intel.infrastructure.mcp_config import (
    McpConfigError,
    delete_mcp_server_json,
    get_mcp_server_from_json,
    list_mcp_servers_from_json,
    set_mcp_server_active_json,
    update_mcp_server_tools_json,
    upsert_mcp_server_json,
)
from src.intel.infrastructure.builtin_market_mcp import (
    BUILTIN_MCP_NAME,
    InProcessMcpClient,
    builtin_server_record,
    is_builtin_mcp_server,
    list_builtin_tools,
)
from src.intel.infrastructure.wudao_settings import public_wudao_settings, save_wudao_settings
from src.ops import OpsError

logger = logging.getLogger(__name__)


def save_wudao_resident(
    *,
    url: str | None = None,
    token: str | None = None,
    expires_at: str | None = None,
    note: str | None = None,
    disabled: bool | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    """更新内置悟道 MCP（Cursor 式：改 URL/Key/到期/启停）。"""
    from src.intel.infrastructure.mcp_config import WUDAO_MCP_URL

    try:
        existing = get_mcp_server_from_json(
            BUILTIN_WUDAO_NAME,
            decrypt_secrets=verify and token is None,
        )
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    target_url = (url or (existing or {}).get("url") or WUDAO_MCP_URL).strip()
    try:
        target_url = validate_mcp_url(target_url)
    except McpError as exc:
        raise OpsError(str(exc)) from exc

    tools: list[dict[str, Any]] = list((existing or {}).get("tools") or [])
    synced_at = str((existing or {}).get("tools_synced_at") or "")

    if verify and (token or (existing or {}).get("has_token")):
        plaintext = token.strip() if token is not None else str((existing or {}).get("token") or "")
        client = McpClient(name=BUILTIN_WUDAO_NAME, url=target_url, token=plaintext)
        try:
            discovered = client.list_tools()
        except McpError as exc:
            raise OpsError("悟道 MCP 连接校验失败，未保存") from exc
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in discovered
        ]
        synced_at = _now()

    try:
        upsert_kwargs: dict[str, Any] = {
            "name": BUILTIN_WUDAO_NAME,
            "url": target_url,
            "token": token,
            "expires_at": expires_at,
            "tools": tools if verify else None,
            "tools_synced_at": synced_at if verify else "",
            "disabled": disabled if disabled is not None else None,
        }
        if note is not None:
            upsert_kwargs["note"] = note
        saved = upsert_mcp_server_json(**upsert_kwargs)
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    return _public(resident_wudao_record(saved))


def patch_wudao_settings(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"hist_daily_primary", "note", "quota"}
    updates = {k: payload[k] for k in allowed if k in payload}
    if not updates:
        return public_wudao_settings()
    save_wudao_settings(updates)
    return public_wudao_settings()


def save_server(
    *,
    name: str,
    url: str,
    token: str | None = None,
    proxy_url: str = "",
    note: str = "",
    expires_at: str | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    """注册或更新一个 MCP server 到 mcp.json。

    verify=True 时会当场握手并拉一次工具列表——配置错误应该在保存时暴露。
    token=None 表示保留原有 Authorization；传空字符串可清空。
    """
    name = name.strip()
    if not name:
        raise OpsError("server 名称不能为空")
    if "__" in name:
        raise OpsError("server 名称不允许包含 __")
    if is_builtin_mcp_server(name):
        raise OpsError(f"{BUILTIN_MCP_NAME} 为内置 server，不可通过 mcp.json 注册或覆盖")
    if is_resident_wudao_server(name):
        raise OpsError(f"{BUILTIN_WUDAO_NAME} 为内置常驻 server，请用 PATCH /api/mcp/wudao 配置")
    try:
        url = validate_mcp_url(url)
    except McpError as exc:
        raise OpsError(str(exc)) from exc
    if proxy_url.strip():
        raise OpsError("MCP 不支持配置代理；请使用直连 HTTPS 服务")

    try:
        existing = get_mcp_server_from_json(
            name, decrypt_secrets=verify and token is None
        )
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    plaintext = token.strip() if token is not None else (existing.get("token") if existing else "")
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
            logger.warning("MCP server %s 保存校验失败：%s", name, exc)
            raise OpsError("MCP server 连接校验失败，未保存") from exc
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in discovered
        ]
        synced_at = _now()

    try:
        saved = upsert_mcp_server_json(
            name=name,
            url=url,
            token=token,
            proxy_url=proxy_url,
            note=note,
            expires_at=expires_at,
            tools=tools,
            tools_synced_at=synced_at,
        )
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    return _public(saved)


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in record.items()
        if k not in {"token", "encrypted_token", "raw", "headers"}
    }


def build_client(name_or_id: str, *, allow_inactive: bool = False) -> McpClient | InProcessMcpClient:
    if is_builtin_mcp_server(name_or_id):
        return InProcessMcpClient()
    if is_resident_wudao_server(name_or_id):
        name_or_id = BUILTIN_WUDAO_NAME
    try:
        record = get_mcp_server_from_json(name_or_id, decrypt_secrets=True)
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    if record is None:
        raise OpsError(f"未注册的 MCP server：{name_or_id}（检查 data/mcp.json）")
    if not allow_inactive and not record.get("is_active", True):
        raise OpsError(f"MCP server {record['name']} 已停用（mcp.json）")
    if not allow_inactive and not record.get("is_usable", True):
        reason = str(record.get("skip_reason") or "不可用")
        raise OpsError(f"MCP server {record['name']} {reason}，已自动跳过")
    return McpClient(
        name=record["name"],
        url=record["url"],
        token=str(record.get("token") or ""),
        headers=record.get("headers") if isinstance(record.get("headers"), dict) else None,
        proxy_url=record.get("proxy_url", ""),
    )


def refresh_tools(name_or_id: str) -> list[dict[str, Any]]:
    """重新发现工具并写回 mcp.json。"""
    if is_resident_wudao_server(name_or_id):
        name_or_id = BUILTIN_WUDAO_NAME
    if is_builtin_mcp_server(name_or_id):
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in list_builtin_tools()
        ]
    client = build_client(name_or_id, allow_inactive=True)
    try:
        record = get_mcp_server_from_json(name_or_id)
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    if record is None:
        raise OpsError(f"未注册的 MCP server：{name_or_id}")
    tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in client.list_tools()
    ]
    try:
        update_mcp_server_tools_json(record["name"], tools, tools_synced_at=_now())
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    return tools


def probe_mcp(name: str, *, refresh: bool = True) -> dict[str, Any]:
    """验证 MCP 服务级连通性，不执行第三方业务工具。

    ``refresh=True``（运维整服探测）：initialize + 拉工具并写回 mcp.json。
    ``refresh=False``（数据源页探测）：只握手，工具数回落本地缓存，避免双倍 list 卡 UI。
    """
    t0 = time.perf_counter()

    def _ms() -> int:
        return max(0, int((time.perf_counter() - t0) * 1000))

    try:
        client = build_client(name, allow_inactive=True)
    except OpsError as exc:
        return {"ok": False, "scope": "server", "rtt_ms": _ms(), "error": str(exc)}

    cached_tools = 0
    try:
        record = get_mcp_server_from_json(name, decrypt_secrets=False)
        if isinstance(record, dict):
            cached_tools = len(record.get("tools") or [])
    except McpConfigError:
        cached_tools = 0

    try:
        info = client.ping(list_tools=refresh)
    except TypeError:
        # 测试桩若仍是 ping() 无关键字参数，退回默认
        try:
            info = client.ping()  # type: ignore[call-arg]
        except McpError as exc:
            logger.warning("MCP server %s 连通性探测失败：%s", name, exc)
            return {
                "ok": False,
                "scope": "server",
                "rtt_ms": _ms(),
                "error": "MCP 服务暂不可用",
            }
    except McpError as exc:
        logger.warning("MCP server %s 连通性探测失败：%s", name, exc)
        return {
            "ok": False,
            "scope": "server",
            "rtt_ms": _ms(),
            "error": "MCP 服务暂不可用",
        }

    tools_updated = int(info.get("tool_count") or 0)
    if refresh and not is_builtin_mcp_server(name):
        try:
            tools = refresh_tools(name)
        except (McpError, OpsError) as exc:
            logger.warning("MCP server %s 探测后刷新失败：%s", name, exc)
            return {
                "ok": False,
                "scope": "server",
                "rtt_ms": _ms(),
                "error": "MCP 服务暂不可用",
            }
        tools_updated = len(tools)
        info = {**info, "tool_count": tools_updated}
    elif not refresh:
        tools_updated = tools_updated or cached_tools
        info = {**info, "tool_count": tools_updated}

    return {
        "ok": True,
        "scope": "server",
        "rtt_ms": _ms(),
        "tools_updated": tools_updated if refresh else 0,
        "server_name": str(info.get("server_name") or ""),
        "server_version": str(info.get("server_version") or ""),
        "protocol_version": str(info.get("protocol_version") or ""),
        "tool_count": int(info.get("tool_count") or 0),
        "sample_tools": list(info.get("sample_tools") or [])[:12],
    }


def set_server_active(name: str, active: bool) -> dict[str, Any]:
    if is_builtin_mcp_server(name):
        raise OpsError(f"内置 MCP server {BUILTIN_MCP_NAME} 不可停用")
    if is_resident_wudao_server(name):
        name = BUILTIN_WUDAO_NAME
    try:
        return _public(set_mcp_server_active_json(name, active))
    except (KeyError, McpConfigError) as exc:
        raise OpsError(f"未注册的 MCP server：{name}") from exc


def delete_server(name: str) -> bool:
    if is_builtin_mcp_server(name):
        raise OpsError(f"内置 MCP server {BUILTIN_MCP_NAME} 不可删除")
    if is_resident_wudao_server(name):
        raise OpsError(f"内置常驻 {BUILTIN_WUDAO_NAME} 不可删除，可在配置中停用")
    try:
        return delete_mcp_server_json(name)
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc


def list_effective_mcp_servers(*, active_only: bool = True) -> list[dict[str, Any]]:
    try:
        from src.intel.infrastructure.builtin_wudao_mcp import is_resident_wudao_server
        from src.intel.infrastructure.mcp_config import migrate_wudao_server_name

        migrate_wudao_server_name()
        rows = [
            row
            for row in list_mcp_servers_from_json()
            if row.get("name") != BUILTIN_MCP_NAME
            and not is_resident_wudao_server(str(row.get("name") or ""))
        ]
        wudao_row = get_mcp_server_from_json(BUILTIN_WUDAO_NAME)
    except McpConfigError as exc:
        raise OpsError(str(exc)) from exc
    if active_only:
        rows = [
            row
            for row in rows
            if row.get("is_active", True) and row.get("is_usable", True)
        ]
    wudao = _public(resident_wudao_record(wudao_row))
    merged: list[dict[str, Any]] = [_public(builtin_server_record())]
    show_wudao = (not active_only) or (wudao.get("is_active") and wudao.get("is_usable"))
    if show_wudao:
        merged.append(wudao)
    merged.extend(rows)
    return sorted(merged, key=lambda item: (0 if item.get("builtin") else 1, str(item["name"])))


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
