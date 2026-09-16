"""请求剩余超时和真实配置容量预检，不通过删除推理或工具记录适配窗口。"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.ai import ChatMessage, ChatResponse, LLMError, ProviderConfig, ToolCall
from src.ai.application import agent, agent_budget
from src.ops import JobCancelled

CONFIG = ProviderConfig(
    name="test", protocol="openai_compatible", base_url="https://example.test/v1",
    api_key="test", model="test", timeout=90,
)


@pytest.mark.parametrize("capacity, expected", [(None, 328000), (2048, 2048)])
def test_unknown_context_window_never_invents_a_capacity(
    monkeypatch: pytest.MonkeyPatch, capacity: int | None, expected: int,
) -> None:
    chat = Mock(return_value=ChatResponse(text="完成"))
    monkeypatch.setattr(agent, "chat", chat)
    config = replace(CONFIG, max_output_tokens=capacity)
    message = ChatMessage(role="assistant", content="正文", reasoning_content="推理" * 10000)
    agent.run_agent(config, system="系统", messages=[message], max_tokens=328000, stream=False)
    assert chat.call_args.kwargs["max_tokens"] == expected
    assert chat.call_args.args[1][0].reasoning_content == message.reasoning_content
    assert config.context_window is None


def test_known_context_recomputes_output_budget_after_tool_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(CONFIG, context_window=1000, max_output_tokens=900)
    budgets: list[int] = []
    prompts: list[list[ChatMessage]] = []
    calls = [ToolCall(id="read-1", name="read", arguments={})]

    def chat(_config: ProviderConfig, messages: list[ChatMessage], **kwargs: Any) -> ChatResponse:
        budgets.append(kwargs["max_tokens"])
        prompts.append(list(messages))
        if len(budgets) == 1:
            return ChatResponse(text="查证", tool_calls=calls, reasoning_content="完整推理" * 10)
        return ChatResponse(text="完成")

    monkeypatch.setattr(agent, "chat", chat)
    result = agent.run_agent(
        config, system="系统", user_prompt="请求", tool_schemas=[{"name": "read"}],
        tool_executor=lambda _name, _args: {"text": "数" * 300},
        max_tokens=328000, stream=False,
    )
    assert result.stopped_reason == "completed"
    assert len(budgets) == 2 and 0 < budgets[1] < budgets[0] <= 900
    for messages, budget in zip(prompts, budgets):
        estimated = agent_budget.estimate_input_tokens(messages, system="系统",
                                                       tools=[{"name": "read"}])
        assert estimated + budget <= 1000
    assert prompts[1][1].reasoning_content == "完整推理" * 10
    assert prompts[1][2].content == "数" * 300
    assert config.max_output_tokens == 900 and config.timeout == 90


@pytest.mark.parametrize("large_part", ["system", "content", "reasoning", "schema", "arguments"])
def test_input_preflight_counts_all_textual_protocol_context(
    monkeypatch: pytest.MonkeyPatch, large_part: str,
) -> None:
    huge = "数" * 2000
    message = ChatMessage(role="assistant", content=huge if large_part == "content" else "正文",
                          reasoning_content=huge if large_part == "reasoning" else "推理")
    if large_part == "arguments":
        message.tool_calls = [ToolCall(id="id", name="read", arguments={"query": huge})]
    chat = Mock(return_value=ChatResponse(text="不该发送"))
    monkeypatch.setattr(agent, "chat", chat)
    with pytest.raises(LLMError, match="上下文容量不足"):
        agent.run_agent(
            replace(CONFIG, context_window=1000),
            system=huge if large_part == "system" else "系统", messages=[message],
            tool_schemas=[{"description": huge}] if large_part == "schema" else None,
            stream=False,
        )
    chat.assert_not_called()
    assert message.reasoning_content == (huge if large_part == "reasoning" else "推理")


def test_tool_growth_stops_with_evidence_intact_instead_of_silently_compacting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = Mock(return_value=ChatResponse(text="查证", reasoning_content="完整推理",
                                         tool_calls=[ToolCall(id="id", name="read")]))
    monkeypatch.setattr(agent, "chat", chat)
    result = agent.run_agent(
        replace(CONFIG, context_window=1000), system="系统", user_prompt="请求",
        tool_executor=lambda _name, _args: {"text": "数" * 2000},
        max_tool_result_chars=None, stream=False,
    )
    assert chat.call_count == 1
    assert result.stopped_reason.startswith("llm_error")
    assert "上下文容量不足" in result.text
    assert result.messages[-1]["content"] == "数" * 2000
    assert result.messages[-2]["reasoning_content"] == "完整推理"


def test_stream_fallback_recalculates_remaining_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(agent_budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    received: list[float] = []

    def stream(config: ProviderConfig, _messages: Any, **_kwargs: Any) -> ChatResponse:
        received.append(config.timeout)
        clock[0] = 120.0
        raise LLMError("stream unsupported")

    def chat(config: ProviderConfig, _messages: Any, **_kwargs: Any) -> ChatResponse:
        received.append(config.timeout)
        return ChatResponse(text="完成")

    monkeypatch.setattr(agent, "chat_stream", stream)
    monkeypatch.setattr(agent, "chat", chat)
    result = agent.run_agent(CONFIG, system="系统", deadline=150.0)
    assert result.stopped_reason == "completed"
    assert received == [50.0, 30.0]
    assert CONFIG.timeout == 90.0


def test_shorter_provider_timeout_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_budget, "time", SimpleNamespace(monotonic=lambda: 100.0))
    chat = Mock(return_value=ChatResponse(text="完成"))
    monkeypatch.setattr(agent, "chat", chat)
    agent.run_agent(replace(CONFIG, timeout=12.0), system="系统", deadline=150.0, stream=False)
    assert chat.call_args.args[0].timeout == 12.0


@pytest.mark.parametrize("limits", [{"context_window": 5000}, {"max_output_tokens": 5000}])
def test_anthropic_thinking_cannot_expand_output_past_known_capacity(
    monkeypatch: pytest.MonkeyPatch, limits: dict[str, int],
) -> None:
    chat = Mock(return_value=ChatResponse(text="不该发送"))
    monkeypatch.setattr(agent, "chat", chat)
    with pytest.raises(LLMError, match="输出容量不足"):
        agent.run_agent(replace(CONFIG, protocol="anthropic", **limits), system="系统",
                        thinking="high", max_tokens=4096, stream=False)
    chat.assert_not_called()


def test_anthropic_reserves_the_existing_thinking_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.infrastructure.client import _apply_anthropic_thinking

    chat = Mock(return_value=ChatResponse(text="完成"))
    monkeypatch.setattr(agent, "chat", chat)
    agent.run_agent(replace(CONFIG, protocol="anthropic", context_window=20000),
                    system="系统", thinking="high", max_tokens=4096, stream=False)
    kwargs = chat.call_args.kwargs
    assert kwargs["thinking"] == "high"
    assert kwargs["max_tokens"] == _apply_anthropic_thinking({}, "high", 4096)


def test_expired_deadline_never_calls_the_model_or_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_budget, "time", SimpleNamespace(monotonic=lambda: 100.0))
    chat, execute = Mock(), Mock()
    monkeypatch.setattr(agent, "chat", chat)
    with pytest.raises(TimeoutError, match="截止时间"):
        agent.run_agent(CONFIG, system="系统", deadline=100.0, stream=False, tool_executor=execute)
    chat.assert_not_called()
    execute.assert_not_called()


@pytest.mark.parametrize("wrapped_error", [False, True])
def test_llm_expiring_deadline_cannot_start_tools_or_retry(
    monkeypatch: pytest.MonkeyPatch, wrapped_error: bool,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(agent_budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    attempts: list[float] = []

    def chat(config: ProviderConfig, _messages: Any, **_kwargs: Any) -> ChatResponse:
        attempts.append(config.timeout)
        clock[0] = 160.0
        if wrapped_error:
            raise LLMError("request timed out")
        return ChatResponse(text="", tool_calls=[ToolCall(id="id", name="write")])

    execute = Mock()
    monkeypatch.setattr(agent, "chat", chat)
    with pytest.raises(TimeoutError, match="截止时间"):
        agent.run_agent(CONFIG, system="系统", deadline=150.0, stream=False, tool_executor=execute)
    assert attempts == [50.0]
    execute.assert_not_called()


def test_stream_wrapping_callback_cancellation_still_propagates_original_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = JobCancelled("用户取消")

    def on_event(event: dict[str, Any]) -> None:
        if event["type"] == "token":
            raise stopped

    def stream(_config: Any, _messages: Any, **kwargs: Any) -> ChatResponse:
        try:
            kwargs["on_delta"]("token", "正文")
        except Exception as exc:
            raise LLMError("流式请求失败") from exc
        raise AssertionError("取消回调未执行")

    chat = Mock()
    monkeypatch.setattr(agent, "chat_stream", stream)
    monkeypatch.setattr(agent, "chat", chat)
    with pytest.raises(JobCancelled) as captured:
        agent.run_agent(CONFIG, system="系统", on_event=on_event)
    assert captured.value is stopped
    chat.assert_not_called()
