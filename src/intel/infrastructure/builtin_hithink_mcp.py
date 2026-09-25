"""同花顺托管 MCP 的租户级共享凭据和固定服务地址。"""
from __future__ import annotations

from typing import Any

from src.intel.infrastructure.mcp_config import McpConfigError, get_mcp_server_from_json

HITHINK_A_SHARE = "hithink-finance-a-share"
HITHINK_INDEX = "hithink-finance-a-share-index"
HITHINK_META = "hithink-finance-meta"
HITHINK_FUND = "hithink-finance-fund"
HITHINK_FUTURES = "hithink-finance-futures"
HITHINK_OPTIONS = "hithink-finance-options"
HITHINK_ENDPOINTS = {
    HITHINK_A_SHARE: "https://fuyao.aicubes.cn/mcp/a-share",
    HITHINK_INDEX: "https://fuyao.aicubes.cn/mcp/a-share-index",
    HITHINK_META: "https://fuyao.aicubes.cn/mcp/meta",
    HITHINK_FUND: "https://fuyao.aicubes.cn/mcp/fund",
    HITHINK_FUTURES: "https://fuyao.aicubes.cn/mcp/futures",
    HITHINK_OPTIONS: "https://fuyao.aicubes.cn/mcp/options",
}


def hithink_api_key() -> str:
    """行情 REST 与 MCP 共用；未配置、停用、过期时返回空串。"""
    try:
        record = get_mcp_server_from_json(HITHINK_A_SHARE)
    except McpConfigError:
        return ""
    if not record or not record.get("is_active") or not record.get("is_usable"):
        return ""
    token = str(record.get("token") or "").strip()
    if token:
        return token
    headers = record.get("headers") if isinstance(record.get("headers"), dict) else {}
    return next((str(value).strip() for key, value in headers.items()
                 if str(key).casefold() == "x-api-key"), "")


def hithink_server_record(row: dict[str, Any] | None = None) -> dict[str, Any]:
    """运维页仅回传脱敏名片，六个端点使用同一份凭据。"""
    row = row or get_mcp_server_from_json(HITHINK_A_SHARE) or {}
    return {
        "id": f"BUILTIN-{HITHINK_A_SHARE}",
        "name": HITHINK_A_SHARE,
        "url": HITHINK_ENDPOINTS[HITHINK_A_SHARE],
        "token_last4": row.get("token_last4", ""),
        "has_token": bool(row.get("has_token")),
        "expires_at": row.get("expires_at", ""),
        "is_usable": bool(row.get("is_usable")),
        "skip_reason": row.get("skip_reason", "未配置 API Key"),
        "tools": row.get("tools") or [],
        "tools_synced_at": row.get("tools_synced_at", ""),
        "is_active": bool(row.get("is_active", True)),
        "note": row.get("note") or "同花顺金融数据 · A股、指数、标的检索、基金、期货、期权共用 API Key",
        "source": "builtin+hithink",
        "builtin": True,
        "resident": True,
    }
