"""MCP 响应解析与 tool schema 约束。

从 `test_intel.py` 拆出（原 743 行）。客户端与注册表用例仍在原文件，
agent 回路在 `test_intel_agent_loop.py`。
"""
from __future__ import annotations

import unittest

from src.intel.infrastructure.mcp import McpError, McpTool, _parse_response


class FakeResponse:
    def __init__(self, *, text: str, status: int = 200, content_type: str = "application/json"):
        self.text = text
        self.status_code = status
        self.headers = {"content-type": content_type}


class ResponseParsingTests(unittest.TestCase):
    def test_parses_plain_json(self) -> None:
        payload = _parse_response(FakeResponse(text='{"jsonrpc":"2.0","id":1,"result":{"ok":1}}'))
        self.assertEqual(payload["result"], {"ok": 1})

    def test_parses_sse_and_takes_the_final_result(self) -> None:
        """Streamable HTTP 允许用 SSE 回复单次请求，前面的事件是进度通知。"""
        body = (
            'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
            'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
        )
        payload = _parse_response(FakeResponse(text=body, content_type="text/event-stream"))
        self.assertEqual(payload["result"], {"tools": []})

    def test_sse_without_a_result_is_an_error(self) -> None:
        with self.assertRaises(McpError):
            _parse_response(
                FakeResponse(text="data: [DONE]\n\n", content_type="text/event-stream")
            )

    def test_non_json_body_is_reported_clearly(self) -> None:
        with self.assertRaises(McpError) as ctx:
            _parse_response(FakeResponse(text="<html>502 Bad Gateway</html>"))
        self.assertIn("不是合法 JSON", str(ctx.exception))


class ToolSchemaTests(unittest.TestCase):
    def test_server_prefix_prevents_name_collisions(self) -> None:
        """两个 server 都有 kline 时，不加前缀就会互相覆盖。"""
        a = McpTool(name="kline", description="A 的 K 线", server="alpha")
        b = McpTool(name="kline", description="B 的 K 线", server="beta")
        self.assertEqual(a.to_openai_schema()["function"]["name"], "alpha__kline")
        self.assertEqual(b.to_anthropic_schema()["name"], "beta__kline")

    def test_empty_schema_falls_back_to_an_object(self) -> None:
        """没有 inputSchema 时不能给 None，两家 API 都会拒绝。"""
        tool = McpTool(name="ping", description="x", server="s")
        self.assertEqual(
            tool.to_openai_schema()["function"]["parameters"],
            {"type": "object", "properties": {}},
        )

    def test_reserved_separator_cannot_appear_in_server_or_tool_name(self) -> None:
        with self.assertRaisesRegex(McpError, "不允许包含 __"):
            McpTool(name="bad__tool", description="x", server="demo")
        with self.assertRaisesRegex(McpError, "不允许包含 __"):
            McpTool(name="tool", description="x", server="bad__server")
