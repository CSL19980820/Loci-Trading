"""供应商强制校验原样推理回传；覆盖流式、长工具链与HITL续跑。"""
import json
from unittest.mock import patch

import httpx2
import pytest

from src.ai import ChatMessage, ProviderConfig
from src.ai.application.agent import run_agent, messages_from_json, apply_hitl_tool_result
from src.ai.infrastructure.client import _openai_messages
from src.ai.infrastructure.connection_retry import ConnectionRetryClient


def config():
    return ProviderConfig(name="test", protocol="openai_compatible", base_url="https://model.invalid", api_key="test", model="deepseek")


def reply(data, streaming):
    if streaming:
        chunks = []
        message = data["choices"][0]["message"]
        if "reasoning_content" in message:
            reason = message["reasoning_content"]
            for part in [reason[:7], reason[7:]]:
                chunks.append({"choices": [{"delta": {"reasoning_content": part}}]})
        delta = {k: v for k, v in message.items() if k != "reasoning_content"}
        for index, call in enumerate(delta.get("tool_calls", [])):
            call["index"] = index
        chunks.append({"choices": [{"delta": delta}], "model": "deepseek", "usage": data["usage"]})
        return httpx2.Response(200, text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n")
    return httpx2.Response(200, json=data)


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("reason", ["", "完整推理片段" * 3000], ids=["empty", "long"])
def test_six_tool_rounds_preserve_exact_reasoning_and_usage(streaming, reason):
    requests = []
    calls = []

    def handle(request):
        body = json.loads(request.content)
        for m in body["messages"]:
            if m.get("tool_calls"):
                assert "reasoning_content" in m and m["reasoning_content"] == reason
        requests.append(body)
        count = len(requests)
        message = {"content": "done", "reasoning_content": reason}
        if count <= 6:
            message = {"content": "", "reasoning_content": reason, "tool_calls": [
                {"id": f"{count}-{i}", "type": "function", "function": {"name": "read", "arguments": json.dumps({"round": count, "index": i})}}
                for i in range(2)]}
        return reply({"choices": [{"message": message}], "model": "deepseek", "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, streaming)

    def execute(name, arguments):
        calls.append(arguments)
        return {"text": json.dumps(arguments)}

    with patch("src.ai.infrastructure.client.ConnectionRetryClient",
               side_effect=lambda **kw: ConnectionRetryClient(transport=httpx2.MockTransport(handle), **kw)):
        result = run_agent(config(), system="test", user_prompt="read", tool_executor=execute, max_rounds=8, stream=streaming)
    assert result.stopped_reason == "completed" and result.text == "done"
    assert len(requests) == 7 and len(calls) == 12
    assert result.input_tokens == 70 and result.output_tokens == 14
    stored = [m for m in result.messages if m.get("tool_calls")]
    assert len(stored) == 6 and all(m["reasoning_content"] == reason for m in stored)
    restored = messages_from_json(result.messages)
    assert all(m.reasoning_content == reason for m in restored if m.tool_calls)


def test_reasoning_survives_hitl_snapshot_and_resume():
    requests = []

    def handle(request):
        body = json.loads(request.content); requests.append(body)
        if len(requests) == 1:
            msg = {"content": "", "reasoning_content": "retain-through-pause", "tool_calls": [
                {"id": "ask", "type": "function", "function": {"name": "ask", "arguments": "{}"}}]}
        else:
            assistant = next(m for m in body["messages"] if m.get("tool_calls"))
            assert assistant["reasoning_content"] == "retain-through-pause"
            assert body["messages"][-1]["content"] == "continue"
            msg = {"content": "done"}
        return reply({"choices": [{"message": msg}], "usage": {}}, True)

    with patch("src.ai.infrastructure.client.ConnectionRetryClient",
               side_effect=lambda **kw: ConnectionRetryClient(transport=httpx2.MockTransport(handle), **kw)):
        first = run_agent(config(), system="test", user_prompt="ask", allow_hitl=True,
                          tool_executor=lambda *a: {"text": "pending", "meta": {"pause": True}})
        assert first.stopped_reason == "waiting_user"
        messages = apply_hitl_tool_result(first.messages, "continue")
        second = run_agent(config(), system="test", messages=messages)
    assert second.stopped_reason == "completed" and second.text == "done"


def test_other_providers_do_not_receive_an_invented_reasoning_field():
    wire = _openai_messages([ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="hello")], "")
    assert all("reasoning_content" not in m for m in wire)
    wire = _openai_messages([ChatMessage(role="assistant", content="", reasoning_content="")], "")
    assert wire[0]["reasoning_content"] == ""


def test_final_and_reasoning_only_turns_are_retained_when_tools_continue():
    requests = []

    def handle(request):
        body = json.loads(request.content); requests.append(body)
        count = len(requests)
        if count == 1:
            msg = {"content": "", "reasoning_content": "thinking-without-tools"}
        elif count == 2:
            assert any(m.get("reasoning_content") == "thinking-without-tools" for m in body["messages"])
            msg = {"content": "first-answer", "reasoning_content": "final-thinking"}
        else:
            reasons = [m.get("reasoning_content") for m in body["messages"] if m["role"] == "assistant"]
            assert reasons == ["thinking-without-tools", "final-thinking"]
            msg = {"content": "second-answer", "reasoning_content": "second-thinking"}
        return reply({"choices": [{"message": msg}], "usage": {}}, True)

    tools = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object", "properties": {}}}}]
    with patch("src.ai.infrastructure.client.ConnectionRetryClient",
               side_effect=lambda **kw: ConnectionRetryClient(transport=httpx2.MockTransport(handle), **kw)):
        first = run_agent(config(), system="test", user_prompt="first", tool_schemas=tools)
        assert first.stopped_reason == "completed" and first.text == "first-answer"
        messages = messages_from_json(first.messages) + [ChatMessage(role="user", content="next question")]
        second = run_agent(config(), system="test", messages=messages, tool_schemas=tools)
    assert second.stopped_reason == "completed" and second.text == "second-answer"
