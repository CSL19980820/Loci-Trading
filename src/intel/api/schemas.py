"""情报上下文的 HTTP 请求模型：MCP 服务器登记与探针。

从组合根 `app/legacy/quant_common.py` 搬入。字段名对外是契约，不得改名。
"""
from __future__ import annotations

from pydantic import Field

from src.shared.api_models import QuantModel


class McpServerCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=8, max_length=300)
    token: str | None = Field(default=None, max_length=500)
    proxy_url: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)
    expires_at: str | None = Field(default=None, max_length=32)
    verify: bool = True


class McpProbeRequest(QuantModel):
    """服务级 MCP 连通性探测不接受工具或工具参数。"""
