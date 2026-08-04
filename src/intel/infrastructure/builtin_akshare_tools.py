"""把本机 AkShare 目录挂成内置 MCP 的单一调用入口。

不按接口枚举工具——四百多个 ``stock_*`` 会淹没模型。只暴露一个
``akshare_call``：参数 ``name`` 必须在本机目录里，执行走行情域受控探测
（子进程 + 超时 + 并发预算）。
"""
from __future__ import annotations

import json
from typing import Any

from src.intel.infrastructure.mcp import McpTool

TOOL_NAME = "akshare_call"
DEFAULT_SAMPLE_ROWS = 30


def is_akshare_tool(bare_name: str) -> bool:
    return bare_name == TOOL_NAME or bare_name.startswith("ak_")


def capability_name(bare_name: str) -> str:
    """兼容旧前缀 ``ak_<接口名>``：若仍有人用旧名，剥前缀后当 capability。"""
    if bare_name == TOOL_NAME:
        return ""
    if bare_name.startswith("ak_"):
        return bare_name[3:]
    return bare_name


def list_akshare_tools(*, server: str) -> list[McpTool]:
    """始终只挂一个通用调用工具（不依赖配置名单）。"""
    return [
        McpTool(
            name=TOOL_NAME,
            description=(
                "调用本机 AkShare 目录内任意 stock_* 接口（受控小样本）。"
                "参数 name 必填，须为目录中的接口名；其余参数按该接口签名传入。"
                f"最多返回 {DEFAULT_SAMPLE_ROWS} 行样本，rows 是全量行数。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "AkShare 接口名，如 stock_zh_a_hist",
                    }
                },
                "required": ["name"],
                "additionalProperties": True,
            },
            server=server,
        )
    ]


def call_akshare_tool(bare_name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """执行 ``akshare_call`` 或兼容旧 ``ak_<name>``。"""
    from src.market import MAX_MCP_SAMPLE_ROWS, probe_stock_capability

    args = dict(arguments or {})
    if bare_name == TOOL_NAME:
        name = str(args.pop("name", "") or "").strip()
    else:
        name = capability_name(bare_name).strip()
        args.pop("name", None)

    if not name or not name.startswith("stock_"):
        return _text("请提供目录内的 stock_* 接口名（参数 name）", is_error=True)

    rows = min(DEFAULT_SAMPLE_ROWS, MAX_MCP_SAMPLE_ROWS)
    try:
        result = probe_stock_capability(name, args, max_sample_rows=rows)
    except ValueError as exc:
        return _text(f"{name} 参数不合法：{exc}", is_error=True)
    except Exception as exc:
        return _text(f"{name} 调用失败：{type(exc).__name__}: {exc}", is_error=True)

    error = result.get("error")
    if error:
        return _text(f"{name} 取数失败：{error}", is_error=True)
    payload = {
        "capability": name,
        "rows": result.get("rows"),
        "columns": result.get("columns"),
        "truncated": result.get("truncated"),
        "elapsed_ms": result.get("elapsed_ms"),
        "sample": result.get("sample"),
    }
    return _text(json.dumps(payload, ensure_ascii=False, default=str))


def _text(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"text": text, "is_error": is_error, "raw": [{"type": "text", "text": text}]}
