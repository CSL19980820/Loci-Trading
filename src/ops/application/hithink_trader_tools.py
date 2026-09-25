"""天才交易员按需发现和调用同花顺托管 MCP，不预装完整工具 schema。"""
from __future__ import annotations

import json
import hashlib
from collections import OrderedDict
from threading import Lock, local
from typing import Any

from src.ai.application.tool_schema import tool_schema
from src.intel import (
    HITHINK_ENDPOINTS, McpClient, McpError, clamp_mcp_arguments_with_notes,
    deadline_scope, hithink_api_key,
)
from src.shared.tenancy import current_tenant

SEARCH_NAME = "hithink_mcp_search"
CALL_NAME = "hithink_mcp_call"
SERVICES = {"a-share": "hithink-finance-a-share",
            "index": "hithink-finance-a-share-index", "meta": "hithink-finance-meta",
            "fund": "hithink-finance-fund", "futures": "hithink-finance-futures",
            "options": "hithink-finance-options"}
_MAX_RESULT_PAGE_CHARS = 10_000
_DEFAULT_FRAGMENT_CHARS = 7_000


def _complete_text(result: dict[str, Any]) -> str:
    """McpClient 的 text 有长度上限，raw 文本块仍保留完整上游回执。"""
    blocks = result.get("raw")
    if isinstance(blocks, list):
        text = "\n".join(
            str(block.get("text") or "") for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if text:
            return text
    return str(result.get("text") or "")


def _page_text(full_text: str, *, offset: int, limit: int,
               envelope: dict[str, Any] | None, notes: list[str]) -> str:
    """把超长响应作为有效 JSON 分页返回，避免截断在半个字段中。"""
    if offset >= len(full_text):
        return json.dumps({"is_error": True, "total_chars": len(full_text),
                           "message": "result_offset 超出结果长度"}, ensure_ascii=False)
    end = min(len(full_text), offset + limit)
    while True:
        page = {
            "code": envelope.get("code") if envelope else None,
            "message": envelope.get("message") if envelope else None,
            "request_id": envelope.get("request_id") if envelope else None,
            "result_page": {
                "offset": offset,
                "total_chars": len(full_text),
                "fragment": full_text[offset:end],
                "next_offset": end if end < len(full_text) else None,
            },
            "note": "这是同一份上游 JSON 的原文片段；用 next_offset 继续读取，不要把片段当完整数据。",
        }
        if notes:
            page["range_notes"] = notes
        rendered = json.dumps(page, ensure_ascii=False)
        if len(rendered) <= _MAX_RESULT_PAGE_CHARS or end <= offset + 1:
            return rendered
        end = offset + max(1, (end - offset) // 2)


def hithink_trader_tools(protocol: str, *, deadline: float, checkpoint: Any):
    """返回两个轻量工具；Key 不可用时完全不进入交易员工具面。"""
    if not hithink_api_key():
        return [], {}
    service_schema = {"type": "string", "enum": list(SERVICES)}
    schemas = [
        tool_schema(protocol, SEARCH_NAME,
            "按需查同花顺 MCP 工具。先选 a-share 行情/财务、index 指数板块、meta 标的检索、"
            "fund 基金、futures 期货或 options 期权；"
            "关键词只返回简表，填 name 可取单个工具的完整参数 schema。",
            {"type": "object", "properties": {
                "service": service_schema, "query": {"type": "string"},
                "name": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5}},
             "required": ["service"], "additionalProperties": False}),
        tool_schema(protocol, CALL_NAME,
            "调用已用 hithink_mcp_search 核对名称和参数的同花顺只读 MCP 数据工具；"
            "超长结果按 result_page.next_offset 分页读取同一份回执。"
            "数据须核对日期、时间和来源，限流时不要连续重试。",
            {"type": "object", "properties": {
                "service": service_schema, "name": {"type": "string"},
                "arguments": {"type": "object", "additionalProperties": True},
                "result_offset": {"type": "integer", "minimum": 0},
                "result_limit_chars": {"type": "integer", "minimum": 1, "maximum": _DEFAULT_FRAGMENT_CHARS}},
             "required": ["service", "name", "arguments"], "additionalProperties": False}),
    ]
    sessions = local()
    tenant = current_tenant()
    result_lock = Lock()
    result_pages: OrderedDict[tuple[str, str, str, str], tuple[str, bool, list[str]]] = OrderedDict()

    def _catalog(service: str):
        checkpoint()
        if current_tenant() != tenant:
            raise ValueError("同花顺 MCP 工具不可跨租户复用")
        name = SERVICES.get(service)
        key = hithink_api_key()
        if not name or not key:
            raise ValueError("同花顺 MCP 服务或 API Key 不可用")
        if getattr(sessions, "key", None) != key:
            sessions.key = key
            sessions.clients = {}
            sessions.catalogs = {}
        if name not in sessions.clients:
            sessions.clients[name] = McpClient(
                name=name, url=HITHINK_ENDPOINTS[name], headers={"X-api-key": key})
        if name not in sessions.catalogs:
            with deadline_scope(deadline):
                sessions.catalogs[name] = {
                    tool.name: tool for tool in sessions.clients[name].list_tools()
                    if tool.name.startswith("get_")
                }
        return sessions.clients[name], sessions.catalogs[name]

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        checkpoint()
        try:
            client, tools = _catalog(str(arguments.get("service") or ""))
            if name == SEARCH_NAME:
                exact = str(arguments.get("name") or "").strip()
                if exact:
                    tool = tools.get(exact)
                    if tool is None:
                        return {"is_error": True, "text": "同花顺 MCP 没有此工具，请按关键词重新搜索。"}
                    data = {"name": tool.name, "description": tool.description,
                            "input_schema": tool.input_schema}
                else:
                    query = str(arguments.get("query") or "").strip().casefold()
                    limit = max(1, min(5, int(arguments.get("limit") or 5)))
                    offset = max(0, int(arguments.get("offset") or 0))
                    matches = [tool for tool in tools.values()
                               if query in (tool.name + " " + tool.description).casefold()]
                    data = {"total": len(matches), "offset": offset,
                        "next_offset": offset + limit if offset + limit < len(matches) else None,
                        "tools": [
                        {"name": tool.name, "description": tool.description[:180]}
                        for tool in matches[offset:offset + limit]],
                        "hint": "用 next_offset 翻页，或填 name 获取单个完整参数定义"}
                return {"text": json.dumps(data, ensure_ascii=False)}
            if name == CALL_NAME:
                target = str(arguments.get("name") or "")
                if target not in tools:
                    return {"is_error": True, "text": "同花顺 MCP 没有此工具，请先搜索当前服务。"}
                raw_args = arguments.get("arguments")
                if not isinstance(raw_args, dict):
                    return {"is_error": True, "text": "arguments 必须是对象"}
                bounded, notes = clamp_mcp_arguments_with_notes(raw_args)
                offset = max(0, int(arguments.get("result_offset") or 0))
                limit = max(1, min(_DEFAULT_FRAGMENT_CHARS,
                                   int(arguments.get("result_limit_chars") or _DEFAULT_FRAGMENT_CHARS)))
                key_hash = hashlib.sha256(hithink_api_key().encode("utf-8")).hexdigest()
                cache_key = (key_hash, str(arguments.get("service")), target,
                             json.dumps(bounded, sort_keys=True, ensure_ascii=False, default=str))
                cached = None
                if offset:
                    with result_lock:
                        cached = result_pages.get(cache_key)
                if cached is None:
                    result = client.call_tool(target, bounded, deadline=deadline)
                    full_text = _complete_text(result)
                    envelope = result.get("structured")
                    if not isinstance(envelope, dict):
                        try:
                            envelope = json.loads(full_text)
                        except (TypeError, ValueError):
                            envelope = None
                    is_error = bool(result.get("is_error")) or (
                        isinstance(envelope, dict)
                        and type(envelope.get("code")) is int and envelope["code"] != 0
                    )
                    if len(full_text) > _MAX_RESULT_PAGE_CHARS and len(full_text) <= 1_000_000:
                        with result_lock:
                            result_pages[cache_key] = (full_text, is_error, notes)
                            result_pages.move_to_end(cache_key)
                            while len(result_pages) > 4:
                                result_pages.popitem(last=False)
                else:
                    full_text, is_error, notes = cached
                    try:
                        envelope = json.loads(full_text)
                    except (TypeError, ValueError):
                        envelope = None
                if offset >= len(full_text) and offset:
                    return {"is_error": True, "text": "result_offset 超出结果长度，请从 0 重新读取"}
                if len(full_text) > _MAX_RESULT_PAGE_CHARS:
                    return {"text": _page_text(full_text, offset=offset, limit=limit,
                                               envelope=envelope if isinstance(envelope, dict) else None,
                                               notes=notes), "is_error": is_error}
                if notes:
                    if isinstance(envelope, dict):
                        full_text = json.dumps({**envelope, "range_notes": notes}, ensure_ascii=False)
                    else:
                        full_text += "\n[取数范围提示] " + ", ".join(notes)
                return {"text": full_text, "is_error": is_error}
            return {"is_error": True, "text": "未知同花顺 MCP 工具"}
        except McpError as exc:
            return {"is_error": True, "text": str(exc)}
        except (ValueError, RuntimeError, OSError) as exc:
            from src.ai.application.agent_execution import reraise_stop
            reraise_stop(exc)
            return {"is_error": True, "text": f"同花顺 MCP 暂不可用：{type(exc).__name__}"}

    return schemas, {SEARCH_NAME: execute, CALL_NAME: execute}
