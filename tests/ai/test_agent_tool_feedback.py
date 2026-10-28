"""普通工具错误回到模型，取消与整轮期限仍中止执行。"""
import json
import time
from concurrent.futures import CancelledError

import pytest

from src.ai.application import agent
from src.ai.infrastructure.client import ChatResponse, ProviderConfig, ToolCall
from src.ops.application.jobs.context import JobCancelled, JobTimedOut


def provider():
    return ProviderConfig("fixture", "openai_compatible", "https://example.invalid", "fixture", model="fixture")


def schema(name):
    return {"type": "function", "function": {"name": name,
            "parameters": {"type": "object", "properties": {}}}}


@pytest.mark.parametrize("failure", ["timeout", "wrapped_timeout", "value_error"])
@pytest.mark.parametrize("parallel", [False, True])
def test_tool_error_is_feedback_and_model_can_continue_other_tools(monkeypatch, failure, parallel):
    requests, executed = [], []

    def stream(_provider, messages, **_options):
        requests.append(messages)
        if len(requests) == 1:
            return ChatResponse("", tool_calls=[ToolCall("failed-1", "read_failed", {}),
                ToolCall("good-1", "read_good", {})], raw={"finish_reason": "tool_calls"})
        if len(requests) == 2:
            feedback = {message.tool_call_id: message.content for message in messages if message.role == "tool"}
            error = json.loads(feedback["failed-1"])
            assert error["recoverable"] and error["tool"] == "read_failed"
            assert "行情源未响应" in error["error"]
            assert feedback["good-1"] == "已取得其他证据"
            return ChatResponse("", tool_calls=[ToolCall("good-2", "read_good", {})], raw={"finish_reason": "tool_calls"})
        return ChatResponse("依据已有证据继续观察", raw={"finish_reason": "stop"})

    def execute(name, _arguments):
        executed.append(name)
        if name == "read_failed":
            if failure == "value_error":
                raise ValueError("行情源未响应")
            if failure == "wrapped_timeout":
                try:
                    raise TimeoutError("行情源未响应")
                except TimeoutError as exc:
                    raise RuntimeError("行情源未响应") from exc
            raise TimeoutError("行情源未响应")
        return {"text": "已取得其他证据"}

    monkeypatch.setattr(agent, "chat_stream", stream)
    result = agent.run_agent(provider(), system="fixture", user_prompt="fixture",
        tool_schemas=[schema("read_failed"), schema("read_good")], tool_executor=execute,
        deadline=time.monotonic() + 30, max_rounds=None, max_calls_per_round=None,
        max_parallel_tools=2 if parallel else 1,
        parallel_tool_names={"read_failed", "read_good"} if parallel else set())
    assert result.stopped_reason == "completed" and result.text == "依据已有证据继续观察"
    assert len(requests) == 3 and executed.count("read_failed") == 1 and executed.count("read_good") == 2
    assert [invocation.ok for invocation in result.invocations] == [False, True, True]


@pytest.mark.parametrize("stop", [JobCancelled("用户取消"), JobTimedOut("任务期限结束"), CancelledError("工具批次取消")])
@pytest.mark.parametrize("wrapped", [False, True])
def test_collaborative_stop_is_not_converted_to_tool_feedback(monkeypatch, stop, wrapped):
    requests = []

    def stream(_provider, _messages, **_options):
        requests.append(True)
        return ChatResponse("", tool_calls=[ToolCall("read", "read_failed", {})], raw={"finish_reason": "tool_calls"})

    def execute(_name, _arguments):
        if wrapped:
            try:
                raise stop
            except Exception as exc:
                raise RuntimeError("客户端包装错误") from exc
        raise stop

    monkeypatch.setattr(agent, "chat_stream", stream)
    with pytest.raises(type(stop)):
        agent.run_agent(provider(), system="fixture", user_prompt="fixture", tool_executor=execute,
                        deadline=time.monotonic() + 30)
    assert len(requests) == 1


@pytest.mark.parametrize("parallel", [False, True])
def test_real_agent_deadline_stops_after_tool_timeout_without_another_model_call(monkeypatch, parallel):
    clock = {"now": 10.0}
    requests = []

    def stream(_provider, _messages, **_options):
        requests.append(True)
        return ChatResponse("", tool_calls=[ToolCall("first", "read_failed", {}),
            ToolCall("second", "read_failed", {})], raw={"finish_reason": "tool_calls"})

    def execute(_name, _arguments):
        clock["now"] = 16.0
        raise TimeoutError("工具未响应")

    monkeypatch.setattr(agent.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(agent, "chat_stream", stream)
    with pytest.raises(TimeoutError, match="Agent 已超过本轮截止时间"):
        agent.run_agent(provider(), system="fixture", user_prompt="fixture", tool_executor=execute,
            deadline=15, max_parallel_tools=2 if parallel else 1,
            parallel_tool_names={"read_failed"} if parallel else set())
    assert len(requests) == 1
