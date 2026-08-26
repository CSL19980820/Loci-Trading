"""悟道 A 股 MCP — 内置常驻外部情报源（与 loci-market 并列）。

凭据仍走 ``data/mcp.json``（Cursor 兼容）；配额 / 日 K 优先走 ``loci.config.json``。
未配 Key 或已过期时仍展示在列表，但 ``is_usable=false``、工具不参与 Agent。
"""
from __future__ import annotations

from typing import Any

from src.intel.infrastructure.mcp_config import (
    WUDAO_LEGACY_NAMES,
    WUDAO_MCP_URL,
    WUDAO_PRESET_NAME,
    WUDAO_PRESET_NOTE,
    assess_server_usability,
    get_mcp_server_from_json,
    migrate_wudao_server_name,
    upsert_mcp_server_json,
)
from src.intel.infrastructure.wudao_settings import public_wudao_settings

BUILTIN_WUDAO_NAME = WUDAO_PRESET_NAME


def is_resident_wudao_server(name: str) -> bool:
    return str(name).strip() in {BUILTIN_WUDAO_NAME, *WUDAO_LEGACY_NAMES}


def ensure_resident_wudao(*, verify: bool = False) -> dict[str, Any]:
    """保证 mcp.json 存在唯一 ``wudao`` 条目（不覆盖已有 token）。"""
    migrate_wudao_server_name()
    existing = get_mcp_server_from_json(BUILTIN_WUDAO_NAME)
    if existing is None:
        upsert_mcp_server_json(
            name=BUILTIN_WUDAO_NAME,
            url=WUDAO_MCP_URL,
            token=None,
            note=WUDAO_PRESET_NOTE,
            disabled=False,
        )
        existing = get_mcp_server_from_json(BUILTIN_WUDAO_NAME)
    if verify and existing and existing.get("is_usable"):
        from src.intel.infrastructure.registry import refresh_tools

        refresh_tools(BUILTIN_WUDAO_NAME)
        existing = get_mcp_server_from_json(BUILTIN_WUDAO_NAME)
    return resident_wudao_record(existing)


def wudao_availability() -> dict[str, Any]:
    """悟道是否可用于扫描。未配 Key / 已过期 / 已停用都算不可用。

    调用方据此降级，而不是等到 ``call_tool`` 抛错才发现。
    """
    try:
        record = resident_wudao_record()
    except Exception as exc:  # noqa: BLE001 — 配置损坏不该拖垮扫描调用方
        return {"available": False, "reason": f"悟道 MCP 配置读取失败：{type(exc).__name__}"}
    if not record.get("is_active", True):
        return {"available": False, "reason": "悟道 MCP 已停用"}
    if not record.get("is_usable"):
        return {
            "available": False,
            "reason": str(record.get("skip_reason") or "悟道 MCP 未配置 API Key"),
        }
    if not record.get("tools"):
        return {"available": False, "reason": "悟道 MCP 尚未同步工具列表，请先在运维页探测"}
    return {"available": True, "reason": ""}


def resident_wudao_record(row: dict[str, Any] | None = None) -> dict[str, Any]:
    """运维 / Agent 列表用的内置悟道名片。"""
    if row is None:
        row = get_mcp_server_from_json(BUILTIN_WUDAO_NAME) or {}
    cfg = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    if cfg:
        usability = assess_server_usability(BUILTIN_WUDAO_NAME, cfg)
    else:
        usability = {
            "usable": bool(row.get("is_usable")),
            "skip_reason": str(row.get("skip_reason") or "未配置 API Key"),
        }
    settings = public_wudao_settings()
    tools = row.get("tools") or []
    return {
        "id": f"BUILTIN-{BUILTIN_WUDAO_NAME}",
        "name": BUILTIN_WUDAO_NAME,
        "url": str(row.get("url") or WUDAO_MCP_URL),
        "token_last4": str(row.get("token_last4") or ""),
        "has_token": bool(row.get("has_token")),
        "expires_at": str(row.get("expires_at") or ""),
        "is_usable": bool(usability.get("usable")),
        "skip_reason": str(usability.get("skip_reason") or ""),
        "tools": tools,
        "tools_synced_at": str(row.get("tools_synced_at") or ""),
        "is_active": bool(row.get("is_active", True)),
        "note": str(row.get("note") or WUDAO_PRESET_NOTE),
        "source": "builtin+wudao",
        "builtin": True,
        "resident": True,
        "hist_daily_primary": settings["hist_daily_primary"],
        "quota": settings["quota"],
    }
