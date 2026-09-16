"""MCP 之上的 agent 回路：API 错误映射、工具执行路由与调用轨迹。

从 `test_intel.py` 拆出（原 743 行）。
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.application.agent import (
    AgentResult,
    ToolInvocation,
    format_tool_trace,
    make_mcp_executor,
    run_agent,
)
from src.ai.infrastructure.client import ChatResponse, LLMError, ProviderConfig, ToolCall
from src.intel.infrastructure.mcp import McpError


class McpApiErrorTests(unittest.TestCase):
    def test_refresh_maps_external_failure_to_503(self) -> None:
        from src.intel.api.router import build_intel_router

        app = FastAPI()
        app.include_router(build_intel_router(write_dependency=lambda: None))
        with patch("src.intel.infrastructure.registry.refresh_tools", side_effect=McpError("network timeout")), TestClient(
            app, raise_server_exceptions=False
        ) as client:
            response = client.post("/api/mcp/demo/refresh")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "MCP 服务暂不可用")

    def test_probe_rejects_tool_payload_without_invoking_external_tool(self) -> None:
        from src.intel.api.router import build_intel_router

        app = FastAPI()
        app.include_router(build_intel_router(write_dependency=lambda: None))
        with patch("src.intel.infrastructure.registry.probe_mcp") as probe, TestClient(
            app,
            raise_server_exceptions=False,
        ) as client:
            response = client.post(
                "/api/mcp/demo/probe",
                json={"tool": "delete_everything", "arguments": {"force": True}},
            )

        self.assertEqual(response.status_code, 422)
        probe.assert_not_called()


@contextmanager
def _patched_chat(**chat_kwargs):
    """同时挡住流式与非流式两条出口。

    ``run_agent`` 默认 ``stream=True``：先打 ``chat_stream``，捕获 ``LLMError``
    才降级到 ``chat``。只 patch ``chat`` 会让每一轮都对着假 base_url 发真实
    HTTPS 请求、白等一次连接超时（本类曾因此跑 43s），也违反「外部 HTTP 必须
    mock」。样板见 tests/ai/test_agent_round_limit.py。
    """
    with patch("src.ai.application.agent.chat_stream", side_effect=LLMError("no stream")), patch(
        "src.ai.application.agent.chat", **chat_kwargs
    ):
        yield


class AgentLoopTests(unittest.TestCase):
    """无人值守场景下，一个陷入循环的 Agent 会安静地烧光配额与 token。"""

    config = ProviderConfig(
        name="p", protocol="openai_compatible", base_url="https://x/v1",
        api_key="k", model="m",
    )

    def test_returns_directly_when_no_tools_are_requested(self) -> None:
        with _patched_chat(return_value=ChatResponse(text="结论", model="m")):
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

        with _patched_chat(side_effect=responses):
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
        with _patched_chat(return_value=looping):
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
        executor = Mock(return_value={"text": "x"})
        with _patched_chat(side_effect=[many, done]):
            result = run_agent(
                self.config, system="s", user_prompt="q",
                tool_schemas=[{}], tool_executor=executor,
                max_calls_per_round=5,
            )
        self.assertEqual(executor.call_count, 5)
        # 超额请求仍须按原 ID 回复；预算限制实际执行，而不是抹去请求记录。
        self.assertEqual(len(result.invocations), 20)
        self.assertEqual([item.executed for item in result.invocations], [True] * 5 + [False] * 15)
        expected_ids = [f"c{i}" for i in range(20)]
        self.assertEqual([item.tool_call_id for item in result.invocations], expected_ids)
        replies = [message for message in result.messages if message["role"] == "tool"]
        self.assertEqual([message["tool_call_id"] for message in replies], expected_ids)
        for message in replies[:5]:
            self.assertEqual(message["content"], "x")
        for message in replies[5:]:
            self.assertIn("工具未执行", message["content"])

    def test_tool_failure_is_reported_to_the_model_not_swallowed(self) -> None:
        """返回空结果会让模型以为"查到了但没数据"，进而编造结论。"""
        responses = [
            ChatResponse(text="", model="m", tool_calls=[ToolCall(id="c", name="t", arguments={})]),
            ChatResponse(text="已说明取数失败", model="m"),
        ]
        def boom(name, args):
            raise RuntimeError("配额用尽")

        with _patched_chat(side_effect=responses):
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
        with _patched_chat(side_effect=responses):
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
