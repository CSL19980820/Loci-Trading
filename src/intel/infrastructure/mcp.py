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
from ipaddress import ip_address, ip_network
import json
import logging
import os
import re
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx2
from src.shared.http_protocol import http_protocol_options
from src.intel.infrastructure.mcp_deadline import active_deadline, deadline_request, deadline_scope, reraise_stop

logger = logging.getLogger(__name__)

#: 与 Hermes Agent（``tools/mcp_tool.py``）一致：悟道 HTTP MCP 实测可用。
PROTOCOL_VERSION = "2025-03-26"
DEFAULT_TIMEOUT = 60.0

#: 一次 tools/list 最多接受多少个工具。防御性上限：某个 server 返回几千个
#: 工具会把 LLM 的上下文直接撑爆。
MAX_TOOLS = 200
MAX_TOOL_PAGES = 50
MAX_RESPONSE_BYTES = 512 * 1024
MAX_TOOL_SCHEMA_BYTES = 32 * 1024
MAX_TOOL_ARGUMENT_BYTES = 32 * 1024
MAX_TOOL_RESULT_CHARS = 12_000
_LOOPBACK_HTTP_ALLOWLIST_ENV = "PALACE_MCP_LOOPBACK_HTTP_HOSTS"
#: Clash / Surge Fake-IP 常用段（RFC 2544 基准测试网）。DNS 名经代理解析到
#: 这里时仍是出站公网 HTTPS，不能当 SSRF 内网拦掉，否则悟道等 MCP 全挂。
_PROXY_FAKE_IP_NETWORKS = (ip_network("198.18.0.0/15"),)


class McpError(RuntimeError):
    """MCP 调用失败。消息可以给用户看，但不含任何凭据。"""


def _loopback_http_allowlist() -> set[str]:
    raw = os.environ.get(_LOOPBACK_HTTP_ALLOWLIST_ENV, "")
    return {host.strip().casefold() for host in raw.split(",") if host.strip()}


def _parse_ip(host: str):
    try:
        return ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _is_allowlisted_loopback_http(host: str, address: Any | None = None) -> bool:
    if host.casefold() not in _loopback_http_allowlist():
        return False
    return address is None or bool(address.is_loopback)


def _is_proxy_fake_ip(address: Any) -> bool:
    """代理 Fake-IP：仅允许「DNS 主机名 → 198.18/15」，禁止用户直接填该段字面量。"""
    try:
        return any(address in network for network in _PROXY_FAKE_IP_NETWORKS)
    except TypeError:
        return False


def _resolved_addresses(url: str) -> set[Any]:
    """解析主机 A/AAAA；供 SSRF 校验与「是否必须走系统代理」共用。"""
    parts = urlsplit(str(url or "").strip().rstrip("/"))
    host = (parts.hostname or "").casefold()
    if not host:
        raise McpError("MCP URL 缺少主机名")
    local_http = parts.scheme == "http"
    try:
        port = parts.port
    except ValueError as exc:
        raise McpError("MCP URL 端口不合法") from exc
    try:
        resolved = socket.getaddrinfo(
            host, port or (80 if local_http else 443), type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise McpError("MCP 主机名无法解析") from exc
    addresses = {_parse_ip(str(item[4][0])) for item in resolved}
    addresses.discard(None)
    if not addresses:
        raise McpError("MCP 主机名没有可用地址")
    return addresses


def needs_system_proxy(url: str) -> bool:
    """Clash/Surge Fake-IP 段只有经系统代理才能出站；直连 198.18 必挂。

    与 Cursor / Node 默认读 ``HTTPS_PROXY`` 同理：DNS 名落到 Fake-IP 时才开
    ``trust_env``，其余公网 HTTPS 仍禁用环境代理（防 SSRF 把流量拐进恶意代理）。
    """
    parts = urlsplit(str(url or "").strip().rstrip("/"))
    if parts.scheme != "https" or _parse_ip(parts.hostname or ""):
        return False
    try:
        addresses = _resolved_addresses(url)
    except McpError:
        return False
    return any(_is_proxy_fake_ip(address) for address in addresses)


def validate_mcp_url(url: str, *, resolve: bool = False) -> str:
    """只允许直连公网 HTTPS；本地 HTTP 必须显式按主机白名单放行。"""
    normalized = str(url or "").strip().rstrip("/")
    try:
        parts = urlsplit(normalized)
        # urlsplit 不校验端口；只有读 .port 才会对 :99999 这类值抛 ValueError。
        _ = parts.port
    except ValueError as exc:
        raise McpError("MCP URL 端口不合法") from exc
    host = (parts.hostname or "").casefold()
    if not host:
        raise McpError("MCP URL 缺少主机名")
    if parts.username is not None or parts.password is not None:
        raise McpError("MCP URL 不允许包含用户信息")
    if parts.scheme not in {"https", "http"}:
        raise McpError("MCP URL 必须使用 HTTPS")
    local_http = parts.scheme == "http"
    if local_http and not _is_allowlisted_loopback_http(host):
        raise McpError(
            f"MCP URL 默认只允许 HTTPS；本地 HTTP 请通过 {_LOOPBACK_HTTP_ALLOWLIST_ENV} 显式放行"
        )

    literal = _parse_ip(host)
    if literal is not None:
        if local_http and literal.is_loopback and _is_allowlisted_loopback_http(host, literal):
            return normalized
        if not literal.is_global:
            raise McpError("MCP URL 不允许指向内网、回环或保留地址")
        if local_http:
            raise McpError("MCP URL 必须使用 HTTPS")
        return normalized

    if not resolve:
        return normalized

    addresses = _resolved_addresses(normalized)
    for address in addresses:
        if local_http and address.is_loopback and _is_allowlisted_loopback_http(host, address):
            continue
        # HTTPS + DNS 名落到 Fake-IP：交给系统代理出站，不当内网 SSRF
        if (not local_http) and _is_proxy_fake_ip(address):
            continue
        if not address.is_global:
            raise McpError("MCP 主机名解析到了内网、回环或保留地址")
        if local_http:
            raise McpError("MCP URL 必须使用 HTTPS")
    return normalized


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _bounded_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    values = arguments or {}
    if not isinstance(values, dict):
        raise McpError("MCP 工具参数必须是对象")
    try:
        size = _json_size(values)
    except (TypeError, ValueError) as exc:
        raise McpError("MCP 工具参数无法序列化") from exc
    if size > MAX_TOOL_ARGUMENT_BYTES:
        raise McpError(f"MCP 工具参数超过 {MAX_TOOL_ARGUMENT_BYTES} 字节上限")
    return values


def _read_response_text(response: Any, *, server: str) -> str:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise McpError(f"{server} 响应过大，超过 {MAX_RESPONSE_BYTES} 字节上限")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _redact_detail(text: str, *, secrets: tuple[str, ...] = ()) -> str:
    """保留有限诊断；先脱敏再限长，避免凭据出现在日志或模型输入中。"""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "***")
    text = re.sub(r"https?://[^\s\"'<>]+", "[URL已隐藏]", text, flags=re.I)
    value = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+|bearer\s+)[^\s,;]+",
        r"\1***",
        text,
    )
    value = re.sub(
        r'''(?i)["']?(api[_-]?key|(?:(?:access|refresh)[_-]?)?token|secret|password|cookie|authorization)["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
        r"\1=***",
        value,
    )
    return value[:300]


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server: str = ""

    def __post_init__(self) -> None:
        if "__" in self.name or "__" in self.server:
            raise McpError("MCP server 与工具名称不允许包含 __")

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
            raise McpError("SSE 响应里没有有效的 JSON-RPC 结果")
        return payload

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError("响应不是合法 JSON") from exc


@dataclass(frozen=True)
class _BufferedResponse:
    status_code: int
    headers: dict[str, str]
    text: str


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
        if "__" in name:
            raise McpError("MCP server 名称不允许包含 __")
        self.name = name
        self.url = validate_mcp_url(url)
        self.token = token
        self.extra_headers = headers or {}
        if proxy_url.strip():
            raise McpError("MCP 不支持配置代理；请使用直连 HTTPS 服务")
        self.timeout = timeout
        self._session_id = ""
        self._request_id = 0
        self._initialized = False
        self._initialize_result: dict[str, Any] = {}

    # ---- 底层 -----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            # 两种都接受：服务端可能用 SSE 回复单次请求。
            "Accept": "application/json, text/event-stream",
            **self.extra_headers,
        }
        # Hermes：部分远端要求会话外 POST 也带协议版本，否则握手被拒。
        if not any(key.casefold() == "mcp-protocol-version" for key in headers):
            headers["Mcp-Protocol-Version"] = PROTOCOL_VERSION
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _client(self) -> httpx2.Client:
        validate_mcp_url(self.url, resolve=True)
        # Fake-IP 必须读系统代理；真公网 IP 仍 trust_env=False，防恶意 HTTPS_PROXY。
        return httpx2.Client(
            timeout=self.timeout,
            trust_env=needs_system_proxy(self.url),
            follow_redirects=False,
            **http_protocol_options(),
        )

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._request_id += 1
        body = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            body["params"] = params

        try:
            if active_deadline() is not None:
                response = deadline_request(self, body)
            else:
                with self._client() as client:
                    with client.stream("POST", self.url, headers=self._headers(), json=body) as upstream:
                        response = _BufferedResponse(
                            status_code=upstream.status_code,
                            headers={str(key).lower(): str(value) for key, value in upstream.headers.items()},
                            text=_read_response_text(upstream, server=self.name),
                        )
        except McpError:
            raise
        except Exception as exc:
            if active_deadline() is not None:
                reraise_stop(exc)
            logger.warning("%s MCP 请求失败：%s", self.name, type(exc).__name__)
            raise McpError(f"{self.name} 请求失败（{type(exc).__name__}）") from exc

        session = response.headers.get("mcp-session-id")
        if session:
            self._session_id = session
        secrets = (self.token, self._session_id, *self.extra_headers.values())

        if response.status_code >= 400:
            hint = {401: "（token 无效）", 403: "（无权限或配额用尽）", 429: "（触发限流）"}.get(
                response.status_code, ""
            )
            logger.warning(
                "%s MCP 返回 HTTP %s：%s",
                self.name,
                response.status_code,
                _redact_detail(response.text, secrets=secrets),
            )
            raise McpError(f"{self.name} 返回 {response.status_code}{hint}")

        try:
            payload = _parse_response(response)
        except McpError:
            logger.warning("%s MCP 响应无效：%s", self.name, _redact_detail(response.text, secrets=secrets))
            raise
        if "error" in payload:
            error = payload["error"] if isinstance(payload["error"], dict) else {}
            code = error.get("code")
            code = code if type(code) is int else "unknown"
            detail = _redact_detail(str(error.get("message") or "未提供原因"), secrets=secrets)
            # 仅透传可用于恢复的字段，不把上游任意 data（可能含凭据）交给模型。
            data = error.get("data")
            hints = []
            if isinstance(data, dict):
                if type(data.get("retryable")) is bool:
                    hints.append("可重试" if data["retryable"] else "不可直接重试")
                delay = data.get("retryAfterMs")
                if type(delay) is int and delay >= 0:
                    hints.append(f"建议等待 {delay} 毫秒")
            recovery = "；" + "；".join(hints) if hints else ""
            logger.warning(
                "%s MCP JSON-RPC 报错 %s：%s",
                self.name,
                code,
                detail,
            )
            raise McpError(f"{self.name} 返回 MCP 协议错误（{code}）：{detail}{recovery}")
        return payload.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """通知没有 id，服务端不回结果。失败不该阻断主流程。"""
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        try:
            if active_deadline() is not None:
                deadline_request(self, body, read_body=False)
            else:
                with self._client() as client:
                    with client.stream("POST", self.url, headers=self._headers(), json=body):
                        pass
        except Exception as exc:
            if active_deadline() is not None:
                reraise_stop(exc)
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
        self._initialized = True
        self._initialize_result = result
        self._notify("notifications/initialized")
        return result

    def ensure_initialized(self) -> dict[str, Any]:
        """首次发现或调用前完成握手，复用本 client 的会话标识。"""
        if not self._initialized:
            return self.initialize()
        return self._initialize_result

    def list_tools(self) -> list[McpTool]:
        """自动发现工具。这正是选 MCP 而不是手包 REST 的理由。"""
        self.ensure_initialized()
        tools: list[McpTool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            if cursor:
                if cursor in seen_cursors:
                    raise McpError(f"{self.name} tools/list 返回重复分页游标")
                seen_cursors.add(cursor)
            page_count += 1
            if page_count > MAX_TOOL_PAGES:
                raise McpError(f"{self.name} tools/list 分页超过 {MAX_TOOL_PAGES} 页")
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params)
            for item in result.get("tools") or []:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                name = str(item["name"])
                if "__" in name:
                    raise McpError("MCP 工具名称不允许包含 __")
                schema = item.get("inputSchema") or {}
                if not isinstance(schema, dict):
                    raise McpError(f"{self.name} 工具 {name} 的 inputSchema 必须是对象")
                if _json_size(schema) > MAX_TOOL_SCHEMA_BYTES:
                    raise McpError(
                        f"{self.name} 工具 {name} 的 inputSchema 超过 {MAX_TOOL_SCHEMA_BYTES} 字节上限"
                    )
                tools.append(
                    McpTool(
                        name=name,
                        description=str(item.get("description", "")),
                        input_schema=schema,
                        server=self.name,
                    )
                )
                if len(tools) >= MAX_TOOLS:
                    logger.warning(
                        "%s 的工具数超过 %s，已截断——过多的工具 schema 会撑爆模型上下文",
                        self.name, MAX_TOOLS,
                    )
                    return tools
            next_cursor = result.get("nextCursor")
            if next_cursor in (None, ""):
                break
            if not isinstance(next_cursor, str):
                raise McpError(f"{self.name} tools/list 返回非法分页游标")
            cursor = next_cursor
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None, *,
                  deadline: float | None = None) -> dict[str, Any]:
        """调用一个工具。

        返回 ``{"text": 拼好的文本, "is_error": bool, "raw": 原始 content}``。
        大多数 MCP server 把结构化结果塞在 text block 里的 JSON 字符串中，
        这里不强行解析——交给模型读，避免猜错格式。
        """
        if deadline is not None:
            with deadline_scope(deadline):
                return self.call_tool(name, arguments)
        # 去掉可能带的 server 前缀。
        self.ensure_initialized()
        bare = name.split("__", 1)[1] if name.startswith(f"{self.name}__") else name
        if "__" in bare:
            raise McpError("MCP 工具名称不允许包含 __")
        result = self._rpc("tools/call", {"name": bare, "arguments": _bounded_arguments(arguments)})

        blocks = result.get("content") or []
        if not isinstance(blocks, list):
            raise McpError(f"{self.name} tools/call 返回了非法 content")
        chunks: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
            elif block.get("type") == "resource":
                resource = block.get("resource") or {}
                chunks.append(str(resource.get("text") or resource.get("uri") or ""))
        text = "\n".join(chunk for chunk in chunks if chunk)
        # MCP 2025：结构化结果优先走 structuredContent，避免只剩中文 headline 无法算闸门
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            structured = None
        return {
            "text": text[:MAX_TOOL_RESULT_CHARS],
            "is_error": bool(result.get("isError")),
            "raw": blocks,
            "structured": structured,
            "truncated": len(text) > MAX_TOOL_RESULT_CHARS,
        }

    def ping(self, *, list_tools: bool = True) -> dict[str, Any]:
        """连通性与鉴权自检。

        ``list_tools=False`` 只做 initialize——数据源页「探测」用，避免为 60+ 工具
        再拉一整页把 UI 卡死；保存配置 / 运维整服探测仍默认拉工具列表。
        """
        info = self.ensure_initialized()
        tools = self.list_tools() if list_tools else []
        server = info.get("serverInfo") or {}
        return {
            "ok": True,
            "server_name": str(server.get("name", "")),
            "server_version": str(server.get("version", "")),
            "protocol_version": str(info.get("protocolVersion", "")),
            "tool_count": len(tools),
            "sample_tools": [tool.name for tool in tools[:12]],
        }
