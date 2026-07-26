"""通用 MCP 客户端（Streamable HTTP + JSON-RPC 2.0）。

## 为什么自己写而不是上 LangChain

需要的只是"POST 一个 JSON-RPC 请求、解析回来的工具列表和调用结果"。
LangChain / LangGraph 带来的抽象层、状态机、依赖链，解决的是我们已经
自己解决过的问题（供应商抽象、密钥加密、工具循环、任务调度），而服务器
只剩约 1.1G 可用内存。这里 150 行就够。

## 为什么做 MCP 而不是只包 REST

对接的服务（如悟道 A 股）同时提供 REST，直接调也能用。但它有 67 个工具，
手工包一遍要写 67 份 schema，上游一改就全过时。MCP 的 ``tools/list`` 能
**自动发现**——接一个新 server 只是加一行配置，工具自动出现在 Agent 的
可用列表里。零维护成本换 150 行代码，很划算。

## 协议要点

- 传输是普通 HTTP POST，不是长连接。响应可能是 JSON，也可能是 SSE
  （``text/event-stream``），两种都要能解析。
- 会话要先 ``initialize``，服务端可能回一个 ``Mcp-Session-Id`` 头，
  之后每个请求都要带上。
- 工具调用结果在 ``result.content`` 里，是一个 content block 列表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

import httpx2

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT = 60.0

#: 一次 tools/list 最多接受多少个工具。防御性上限：某个 server 返回几千个
#: 工具会把 LLM 的上下文直接撑爆。
MAX_TOOLS = 200


class McpError(RuntimeError):
    """MCP 调用失败。消息可以给用户看，但不含任何凭据。"""


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server: str = ""

    def to_openai_schema(self) -> dict[str, Any]:
        """转成 OpenAI function calling 的格式。"""
        return {
            "type": "function",
            "function": {
                # 加 server 前缀避免多个 server 的同名工具互相覆盖。
                "name": f"{self.server}__{self.name}" if self.server else self.name,
                "description": self.description[:1000],
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": f"{self.server}__{self.name}" if self.server else self.name,
            "description": self.description[:1000],
            "input_schema": self.input_schema or {"type": "object", "properties": {}},
        }


def _parse_response(response: Any) -> dict[str, Any]:
    """解析 JSON 或 SSE 响应。

    Streamable HTTP 允许服务端用 text/event-stream 回复单次请求。
    只取最后一个带 data 的事件——那是最终结果，前面的是进度通知。
    """
    content_type = (response.headers.get("content-type") or "").lower()
    text = response.text or ""

    if "text/event-stream" in content_type:
        payload: dict[str, Any] | None = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                candidate = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and ("result" in candidate or "error" in candidate):
                payload = candidate
        if payload is None:
            raise McpError(f"SSE 响应里没有有效的 JSON-RPC 结果：{text[:200]}")
        return payload

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError(f"响应不是合法 JSON：{text[:200]}") from exc


class McpClient:
    """一个 MCP server 的连接。

    刻意做成"每次操作独立 POST"而不是维持长连接：定时任务是每天跑几次的
    低频场景，为它维护一个会随时断掉的长连接得不偿失。
    """

    def __init__(
        self,
        *,
        name: str,
        url: str,
        token: str = "",
        headers: dict[str, str] | None = None,
        proxy_url: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.token = token
        self.extra_headers = headers or {}
        self.proxy_url = proxy_url
        self.timeout = timeout
        self._session_id = ""
        self._request_id = 0

    # ---- 底层 -----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            # 两种都接受：服务端可能用 SSE 回复单次请求。
            "Accept": "application/json, text/event-stream",
            **self.extra_headers,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _client(self) -> httpx2.Client:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return httpx2.Client(**kwargs)

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._request_id += 1
        body = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            body["params"] = params

        with self._client() as client:
            try:
                response = client.post(self.url, headers=self._headers(), json=body)
            except Exception as exc:
                raise McpError(f"{self.name} 请求失败：{type(exc).__name__}: {exc}") from exc

        session = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if session:
            self._session_id = session

        if response.status_code >= 400:
            hint = {401: "（token 无效）", 403: "（无权限或配额用尽）", 429: "（触发限流）"}.get(
                response.status_code, ""
            )
            raise McpError(
                f"{self.name} 返回 {response.status_code}{hint}：{(response.text or '')[:300]}"
            )

        payload = _parse_response(response)
        if "error" in payload:
            error = payload["error"] or {}
            raise McpError(f"{self.name} 报错 {error.get('code')}：{error.get('message')}")
        return payload.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """通知没有 id，服务端不回结果。失败不该阻断主流程。"""
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        try:
            with self._client() as client:
                client.post(self.url, headers=self._headers(), json=body)
        except Exception as exc:
            logger.debug("%s 通知 %s 失败（可忽略）：%s", self.name, method, exc)

    # ---- 公开接口 -------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        """握手。拿到 server 信息并建立会话。"""
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "qianlong-palace", "version": "1.0.0"},
            },
        )
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> list[McpTool]:
        """自动发现工具。这正是选 MCP 而不是手包 REST 的理由。"""
        tools: list[McpTool] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params)
            for item in result.get("tools") or []:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                tools.append(
                    McpTool(
                        name=str(item["name"]),
                        description=str(item.get("description", "")),
                        input_schema=item.get("inputSchema") or {},
                        server=self.name,
                    )
                )
                if len(tools) >= MAX_TOOLS:
                    logger.warning(
                        "%s 的工具数超过 %s，已截断——过多的工具 schema 会撑爆模型上下文",
                        self.name, MAX_TOOLS,
                    )
                    return tools
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用一个工具。

        返回 ``{"text": 拼好的文本, "is_error": bool, "raw": 原始 content}``。
        大多数 MCP server 把结构化结果塞在 text block 里的 JSON 字符串中，
        这里不强行解析——交给模型读，避免猜错格式。
        """
        # 去掉可能带的 server 前缀。
        bare = name.split("__", 1)[1] if name.startswith(f"{self.name}__") else name
        result = self._rpc("tools/call", {"name": bare, "arguments": arguments or {}})

        blocks = result.get("content") or []
        chunks: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
            elif block.get("type") == "resource":
                resource = block.get("resource") or {}
                chunks.append(str(resource.get("text") or resource.get("uri") or ""))
        return {
            "text": "\n".join(chunk for chunk in chunks if chunk),
            "is_error": bool(result.get("isError")),
            "raw": blocks,
        }

    def ping(self) -> dict[str, Any]:
        """连通性与鉴权自检。配置时用来当场验证，而不是等定时任务半夜失败。"""
        info = self.initialize()
        tools = self.list_tools()
        server = info.get("serverInfo") or {}
        return {
            "ok": True,
            "server_name": str(server.get("name", "")),
            "server_version": str(server.get("version", "")),
            "protocol_version": str(info.get("protocolVersion", "")),
            "tool_count": len(tools),
            "sample_tools": [tool.name for tool in tools[:12]],
        }
