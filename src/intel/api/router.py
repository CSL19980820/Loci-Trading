"""MCP 情报源 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.intel.api.schemas import McpProbeRequest, McpServerCreate
from src.shared.api_deps import market_store, missing_dependency


def build_intel_router(
    *,
    write_dependency,
    market_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    @router.get("/api/intel/brief", tags=["intel"])
    def get_intel_brief(
        trade_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """盘面短线情报摘要：只读 ``intel_snapshots``，不调外部 MCP。

        可选能力：库异常 / 无缓存一律返回 ``available=false``，不 5xx，不拖垮盘面。
        """
        try:
            from src.intel.application.brief import build_intel_brief, empty_intel_brief
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            with market_store(market_db) as store:
                return build_intel_brief(store, trade_date=trade_date)
        except Exception:
            return empty_intel_brief(
                trade_date=trade_date,
                note="情报服务暂不可用（已忽略）；不影响盘面/账本/选股主体功能。",
            )

    @router.get("/api/mcp", tags=["mcp"])
    def list_mcp_servers() -> list[dict[str, Any]]:
        """列出 MCP server（仅 data/mcp.json；不返回 token 明文）。"""
        try:
            from src.intel.infrastructure.registry import list_effective_mcp_servers
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            rows = list_effective_mcp_servers(active_only=False)
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            item = {
                k: v
                for k, v in row.items()
                if k not in {"token", "encrypted_token", "raw", "headers"}
            }
            cleaned.append(item)
        return cleaned

    @router.get("/api/mcp/quota", tags=["mcp"])
    def get_mcp_quota() -> dict[str, Any]:
        from src.intel.infrastructure.quota import quota_snapshot

        return quota_snapshot()

    @router.patch("/api/mcp/wudao/settings", tags=["mcp"])
    def patch_wudao_quota_settings(
        payload: dict[str, Any],
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            from src.intel.infrastructure.registry import patch_wudao_settings
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return patch_wudao_settings(payload)

    @router.put("/api/mcp/wudao", tags=["mcp"])
    def save_wudao_mcp(payload: dict[str, Any], _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.intel.infrastructure.registry import save_wudao_resident
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            return save_wudao_resident(
                url=payload.get("url"),
                token=payload.get("token"),
                expires_at=payload.get("expires_at"),
                note=payload.get("note"),
                disabled=not bool(payload.get("is_active", True)) if "is_active" in payload else None,
                verify=bool(payload.get("verify", True)),
            )
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/mcp", tags=["mcp"], status_code=201)
    def save_mcp_server(payload: McpServerCreate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.intel.infrastructure.registry import save_server
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            return save_server(
                name=payload.name,
                url=payload.url,
                token=payload.token,
                proxy_url=payload.proxy_url,
                note=payload.note,
                expires_at=payload.expires_at,
                verify=payload.verify,
            )
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/mcp/{name}/refresh", tags=["mcp"])
    def refresh_mcp_tools(name: str, _write: None = write_guard) -> dict[str, Any]:
        """重新发现工具并写回 mcp.json。"""
        try:
            from src.intel.infrastructure.registry import refresh_tools
            from src.intel.infrastructure.mcp import McpError
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            tools = refresh_tools(name)
        except McpError as exc:
            raise HTTPException(status_code=503, detail="MCP 服务暂不可用") from exc
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"tools": tools, "count": len(tools)}

    @router.post("/api/mcp/{name}/probe", tags=["mcp"])
    def probe_mcp_server(
        name: str,
        _payload: McpProbeRequest | None = None,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """服务级连通性探测：握手、列工具并刷新清单，不执行任意工具。"""
        try:
            from src.intel import probe_mcp
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return probe_mcp(name)

    @router.patch("/api/mcp/{name}", tags=["mcp"])
    def toggle_mcp_server(
        name: str,
        payload: dict[str, Any],
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """启用/停用 MCP server（写 mcp.json 的 disabled 字段）。"""
        try:
            from src.intel.infrastructure.registry import set_server_active
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            return set_server_active(name, bool(payload.get("is_active", True)))
        except OpsError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/api/mcp/{name}", tags=["mcp"])
    def delete_mcp_server(name: str, _write: None = write_guard) -> dict[str, bool]:
        try:
            from src.intel.infrastructure.registry import delete_server
            from src.ops import OpsError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            removed = delete_server(name)
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail=f"未注册的 MCP server：{name}")
        return {"removed": True}

    return router
