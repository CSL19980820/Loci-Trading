"""MCP 情报源 HTTP。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.app.legacy.quant_common import McpProbeRequest, McpServerCreate, missing_dependency, ops_store


def build_intel_router(*, write_dependency) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

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
            from src.intel.infrastructure.registry import probe_mcp
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
