"""研究 HTTP 写入接口的默认权限边界。"""
from __future__ import annotations

from fastapi import HTTPException


def require_configured_research_write_access() -> None:
    """拒绝未由组合根显式装配权限依赖的写入请求。"""
    raise HTTPException(status_code=503, detail="研究写权限未配置")


__all__ = ["require_configured_research_write_access"]
