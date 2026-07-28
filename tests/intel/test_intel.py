from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.ai.application.agent import (
    AgentResult,
    ToolInvocation,
    format_tool_trace,
    make_mcp_executor,
    run_agent,
)
from src.ai.infrastructure.client import ChatResponse, ProviderConfig, ToolCall
from src.intel.infrastructure.mcp import McpClient, McpError, McpTool, _parse_response
from src.intel.infrastructure.registry import build_client, collect_tools, save_server
from src.ops.infrastructure.store import OpsError


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


class McpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = McpClient(name="demo", url="https://example.com/mcp", token="t")

    def _rpc_returns(self, payloads: list[dict]):
        return patch.object(self.client, "_rpc", side_effect=payloads)

    def test_lists_tools_across_pages(self) -> None:
        """分页必须走完，否则后面的工具会静默丢失。"""
        pages = [
            {"tools": [{"name": "a", "description": "A"}], "nextCursor": "c1"},
            {"tools": [{"name": "b", "description": "B"}]},
        ]
        with self._rpc_returns(pages):
            tools = self.client.list_tools()
        self.assertEqual([t.name for t in tools], ["a", "b"])
        self.assertTrue(all(t.server == "demo" for t in tools))

    def test_skips_malformed_tool_entries(self) -> None:
        with self._rpc_returns([{"tools": [{"description": "无名"}, {"name": "ok"}]}]):
            self.assertEqual([t.name for t in self.client.list_tools()], ["ok"])

    def test_call_tool_joins_text_blocks(self) -> None:
        payload = {"content": [{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}]}
        with self._rpc_returns([payload]):
            result = self.client.call_tool("demo__kline", {"code": "600519"})
        self.assertEqual(result["text"], "第一段\n第二段")
        self.assertFalse(result["is_error"])

    def test_call_tool_strips_the_server_prefix(self) -> None:
        """模型看到的是带前缀的名字，发给 server 的必须是原名。"""
        with patch.object(self.client, "_rpc", return_value={"content": []}) as rpc:
            self.client.call_tool("demo__kline", {"code": "600519"})
        self.assertEqual(rpc.call_args[0][1]["name"], "kline")

    def test_error_flag_is_preserved(self) -> None:
        payload = {"content": [{"type": "text", "text": "配额用尽"}], "isError": True}
        with self._rpc_returns([payload]):
            self.assertTrue(self.client.call_tool("x", {})["is_error"])


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.mcp_path = Path(self.temp.name) / "mcp.json"
        self._path_patch = patch("src.intel.infrastructure.mcp_config.mcp_json_path", return_value=self.mcp_path)
        self._path_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self.temp.cleanup()

    def _save(self, **overrides):
        params = {
            "name": "wudao",
            "url": "https://example.com/mcp",
            "token": "lb_secret_1234",
            "verify": False,
        }
        params.update(overrides)
        return save_server(**params)

    def test_token_is_stored_in_mcp_json_and_masked_in_api(self) -> None:
        record = self._save()
        self.assertTrue(str(record["token_last4"]).endswith("1234"))
        self.assertNotIn("token", record)
        self.assertTrue(record["has_token"])
        raw = json.loads(self.mcp_path.read_text(encoding="utf-8"))
        auth = raw["mcpServers"]["wudao"]["headers"]["Authorization"]
        self.assertEqual(auth, "Bearer lb_secret_1234")

    def test_client_is_rebuilt_with_the_token(self) -> None:
        self._save()
        client = build_client("wudao")
        self.assertEqual(client.token, "lb_secret_1234")

    def test_url_must_be_http(self) -> None:
        with self.assertRaises(OpsError):
            self._save(url="ftp://example.com")

    def test_updating_without_a_token_keeps_the_existing_one(self) -> None:
        self._save()
        self._save(token=None, url="https://example.com/mcp2")
        client = build_client("wudao")
        self.assertEqual(client.url, "https://example.com/mcp2")
        self.assertEqual(client.token, "lb_secret_1234")

    def test_collect_tools_narrows_to_the_allow_list(self) -> None:
        """一个 server 有 60+ 工具，全塞进 prompt 会占掉大量上下文。"""
        from src.intel.infrastructure.mcp_config import upsert_mcp_server_json

        upsert_mcp_server_json(
            name="wudao",
            url="https://example.com/mcp",
            token="",
            tools=[
                {"name": "kline", "description": "K线"},
                {"name": "limit_up_ladder", "description": "涨停梯队"},
                {"name": "sec_filings", "description": "海外披露"},
            ],
        )
        tools, routing = collect_tools(["wudao"], allow=["kline", "limit_up_ladder"])
        self.assertEqual(sorted(t.name for t in tools), ["kline", "limit_up_ladder"])
        self.assertEqual(routing["wudao__kline"], "wudao")

    def test_inactive_servers_are_excluded(self) -> None:
        from src.intel.infrastructure.mcp_config import upsert_mcp_server_json

        upsert_mcp_server_json(
            name="off",
            url="https://x/mcp",
            disabled=True,
            tools=[{"name": "t", "description": "d"}],
        )
        tools, _ = collect_tools(server_names=["off"])
        self.assertEqual(tools, [])


class AgentLoopTests(unittest.TestCase):
    """无人值守场景下，一个陷入循环的 Agent 会安静地烧光配额与 token。"""

    config = ProviderConfig(
        name="p", protocol="openai_compatible", base_url="https://x/v1",
        api_key="k", model="m",
    )

    def test_returns_directly_when_no_tools_are_requested(self) -> None:
        with patch("src.ai.application.agent.chat", return_value=ChatResponse(text="结论", model="m")):
            result = run_agent(self.config, system="s", user_prompt="q")
        self.assertEqual(result.text, "结论")
        self.assertEqual(result.rounds, 1)
        self.assertEqual(result.stopped_reason, "completed")

    def test_executes_tools_then_continues(self) -> None:
        responses = [
            ChatResponse(
                text="", model="m",
                tool_calls=[ToolCall(id="c1", name="wudao__kline", arguments={"code": "600519"})],
            ),
            ChatResponse(text="基于 K 线的结论", model="m"),
        ]
        calls: list[tuple[str, dict]] = []

        def executor(name, args):
            calls.append((name, args))
            return {"text": "日线数据", "is_error": False}

        with patch("src.ai.application.agent.chat", side_effect=responses):
            result = run_agent(
                self.config, system="s", user_prompt="q",
                tool_schemas=[{"type": "function"}], tool_executor=executor,
            )
        self.assertEqual(calls, [("wudao__kline", {"code": "600519"})])
        self.assertEqual(result.text, "基于 K 线的结论")
        self.assertEqual(len(result.invocations), 1)
        self.assertTrue(result.invocations[0].ok)

    def test_stops_at_the_round_limit_and_says_so(self) -> None:
        """撞上限时必须如实说明，不能假装分析完整。"""
        looping = ChatResponse(
            text="", model="m", tool_calls=[ToolCall(id="c", name="t", arguments={})]
        )
        with patch("src.ai.application.agent.chat", return_value=looping):
            result = run_agent(
                self.config, system="s", user_prompt="q",
                tool_schemas=[{}], tool_executor=lambda n, a: {"text": "x"},
                max_rounds=3,
            )
        self.assertEqual(result.rounds, 3)
        self.assertEqual(result.stopped_reason, "max_rounds")
        self.assertIn("轮数上限", result.text)

    def test_caps_tool_calls_per_round(self) -> None:
        many = ChatResponse(
            text="", model="m",
            tool_calls=[ToolCall(id=f"c{i}", name="t", arguments={}) for i in range(20)],
        )
        done = ChatResponse(text="好了", model="m")
        with patch("src.ai.application.agent.chat", side_effect=[many, done]):
            result = run_agent(
                self.config, system="s", user_prompt="q",
                tool_schemas=[{}], tool_executor=lambda n, a: {"text": "x"},
                max_calls_per_round=5,
            )
        self.assertEqual(len(result.invocations), 5)

    def test_tool_failure_is_reported_to_the_model_not_swallowed(self) -> None:
        """返回空结果会让模型以为"查到了但没数据"，进而编造结论。"""
        responses = [
            ChatResponse(text="", model="m", tool_calls=[ToolCall(id="c", name="t", arguments={})]),
            ChatResponse(text="已说明取数失败", model="m"),
        ]
        def boom(name, args):
            raise RuntimeError("配额用尽")

        with patch("src.ai.application.agent.chat", side_effect=responses):
            result = run_agent(
                self.config, system="s", user_prompt="q",
                tool_schemas=[{}], tool_executor=boom,
            )
        self.assertFalse(result.invocations[0].ok)
        self.assertIn("配额用尽", result.invocations[0].error)

    def test_accumulates_token_usage_across_rounds(self) -> None:
        responses = [
            ChatResponse(text="", model="m", input_tokens=100, output_tokens=20,
                         tool_calls=[ToolCall(id="c", name="t", arguments={})]),
            ChatResponse(text="done", model="m", input_tokens=300, output_tokens=50),
        ]
        with patch("src.ai.application.agent.chat", side_effect=responses):
            result = run_agent(
                self.config, system="s", user_prompt="q",
                tool_schemas=[{}], tool_executor=lambda n, a: {"text": "x"},
            )
        self.assertEqual(result.input_tokens, 400)
        self.assertEqual(result.output_tokens, 70)


class ExecutorRoutingTests(unittest.TestCase):
    def test_routes_by_prefix(self) -> None:
        class FakeClient:
            def __init__(self):
                self.seen = None

            def call_tool(self, name, args):
                self.seen = (name, args)
                return {"text": "ok", "is_error": False}

        client = FakeClient()
        execute = make_mcp_executor({"wudao": client}, {"wudao__kline": "wudao"})
        result = execute("wudao__kline", {"code": "1"})
        self.assertEqual(result["text"], "ok")
        self.assertEqual(client.seen, ("wudao__kline", {"code": "1"}))

    def test_unknown_tool_tells_the_model_what_exists(self) -> None:
        """模型偶尔会凭空发明工具名。如实告诉它，别静默返回空。"""
        execute = make_mcp_executor({}, {"wudao__kline": "wudao"})
        result = execute("made_up_tool", {})
        self.assertTrue(result["is_error"])
        self.assertIn("wudao__kline", result["text"])


class TraceTests(unittest.TestCase):
    def test_formats_a_readable_trace(self) -> None:
        """定时任务出问题时，"它查了什么、拿到什么"是第一个要看的东西。"""
        trace = format_tool_trace(
            [
                ToolInvocation(name="wudao__kline", arguments={"code": "600519"},
                               ok=True, result_preview="…", elapsed_ms=210),
                ToolInvocation(name="wudao__ladder", arguments={}, ok=False,
                               result_preview="", error="配额用尽", elapsed_ms=90),
            ]
        )
        self.assertIn("✓ wudao__kline", trace)
        self.assertIn("✗ wudao__ladder", trace)
        self.assertIn("配额用尽", trace)

    def test_empty_trace_is_explicit(self) -> None:
        self.assertIn("未调用", format_tool_trace([]))

    def test_agent_result_serialises_for_the_run_record(self) -> None:
        result = AgentResult(text="t", rounds=2, model="m", input_tokens=1, output_tokens=2)
        payload = result.to_dict()
        self.assertEqual(payload["output"], "t")
        self.assertEqual(payload["rounds"], 2)
        self.assertEqual(json.loads(json.dumps(payload))["model"], "m")


if __name__ == "__main__":
    unittest.main()
