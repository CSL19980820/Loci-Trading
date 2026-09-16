"""Completed responses remain metered when an agent is interrupted."""
from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai import ChatResponse, LLMError, ProviderConfig, ToolCall
from src.ai.application import agent, agent_budget
from src.ops import JobCancelled, JobTimedOut

CONFIG = ProviderConfig(
    name="test", protocol="openai_compatible", base_url="https://example.invalid",
    api_key="test", model="requested-model",
)


def _response(*, tools: bool = False, tokens_in: int = 123, tokens_out: int = 45) -> ChatResponse:
    return ChatResponse(
        text="finished", model="actual-model", input_tokens=tokens_in, output_tokens=tokens_out, raw={"finish_reason": "stop"},
        tool_calls=[ToolCall(id=name, name=name, arguments={}) for name in ("read_a", "read_b")] if tools else [],
    )


def _usage(error: BaseException) -> dict:
    return getattr(error, "usage", {})


@pytest.mark.parametrize("stream", [False, True])
def test_normal_rounds_are_added_once(monkeypatch: pytest.MonkeyPatch, stream: bool) -> None:
    chat = Mock(side_effect=[_response(tools=True), _response(tokens_in=7, tokens_out=3)])
    monkeypatch.setattr(agent, "chat_stream" if stream else "chat", chat)
    result = agent.run_agent(CONFIG, system="test", stream=stream,
                             tool_executor=lambda *_: {"text": "evidence"})
    assert (result.input_tokens, result.output_tokens, result.rounds) == (130, 48, 2)
    assert result.model == "actual-model" and chat.call_count == 2


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, CancelledError, asyncio.CancelledError])
@pytest.mark.parametrize("parallel", [False, True])
def test_tool_stop_keeps_completed_usage_and_exception_identity(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException], parallel: bool,
) -> None:
    stop = error_type("stop now")
    chat = Mock(return_value=_response(tools=True))
    monkeypatch.setattr(agent, "chat", chat)
    with pytest.raises(error_type) as caught:
        agent.run_agent(CONFIG, system="test", stream=False, tool_executor=Mock(side_effect=stop),
                        max_parallel_tools=2 if parallel else 1, parallel_tool_names={"read_a", "read_b"})
    assert caught.value is stop
    assert _usage(stop) == {"model": "actual-model", "input_tokens": 123, "output_tokens": 45, "rounds": 1}
    assert chat.call_count == 1


@pytest.mark.parametrize("transport", ["chat", "stream", "fallback"])
def test_response_is_counted_before_post_request_cancellation(
    monkeypatch: pytest.MonkeyPatch, transport: str,
) -> None:
    stop = JobCancelled("cancel after response")
    returned = False

    def chat(*_args: object, **_kwargs: object) -> ChatResponse:
        nonlocal returned
        returned = True
        return _response()

    def checkpoint() -> None:
        if returned:
            raise stop

    stream = Mock(side_effect=LLMError("stream unavailable")) if transport == "fallback" else chat
    monkeypatch.setattr(agent, "chat", chat)
    monkeypatch.setattr(agent, "chat_stream", stream)
    with pytest.raises(JobCancelled) as caught:
        agent.run_agent(CONFIG, system="test", stream=transport != "chat", check_cancelled=checkpoint)
    assert caught.value is stop
    assert (_usage(stop).get("input_tokens"), _usage(stop).get("output_tokens")) == (123, 45)


@pytest.mark.parametrize("stream", [False, True])
def test_deadline_after_response_keeps_usage(monkeypatch: pytest.MonkeyPatch, stream: bool) -> None:
    clock = [100.0]
    monkeypatch.setattr(agent_budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def chat(*_args: object, **_kwargs: object) -> ChatResponse:
        clock[0] = 120.0
        return _response(tools=True)

    execute = Mock()
    monkeypatch.setattr(agent, "chat_stream" if stream else "chat", chat)
    with pytest.raises(TimeoutError) as caught:
        agent.run_agent(CONFIG, system="test", stream=stream, deadline=110.0, tool_executor=execute)
    assert (_usage(caught.value).get("input_tokens"), _usage(caught.value).get("output_tokens")) == (123, 45)
    execute.assert_not_called()


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, asyncio.CancelledError])
def test_wrapped_llm_stop_preserves_prior_usage(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException],
) -> None:
    stop = error_type("cancelled in callback")
    calls = 0

    def stream(*_args: object, **_kwargs: object) -> ChatResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(tools=True)
        raise LLMError("callback wrapped") from stop

    fallback = Mock(side_effect=AssertionError("must not retry a cancellation"))
    monkeypatch.setattr(agent, "chat_stream", stream)
    monkeypatch.setattr(agent, "chat", fallback)
    with pytest.raises(error_type) as caught:
        agent.run_agent(CONFIG, system="test", tool_executor=lambda *_: {"text": "evidence"})
    assert caught.value is stop
    assert _usage(stop) == {"model": "actual-model", "input_tokens": 123, "output_tokens": 45, "rounds": 1}
    assert calls == 2
    fallback.assert_not_called()


def test_plain_llm_error_keeps_only_known_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "chat", Mock(side_effect=[_response(tools=True), LLMError("failed")]))
    result = agent.run_agent(CONFIG, system="test", stream=False, tool_executor=lambda *_: {"text": "evidence"})
    assert result.stopped_reason.startswith("llm_error")
    assert (result.input_tokens, result.output_tokens) == (123, 45)


def test_nested_and_following_calls_do_not_share_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = JobCancelled("outer cancelled")
    monkeypatch.setattr(agent, "chat", Mock(side_effect=[_response(tools=True), _response(tokens_in=7, tokens_out=3)]))

    def execute(*_args: object) -> dict:
        inner = agent.run_agent(CONFIG, system="nested", stream=False)
        assert (inner.input_tokens, inner.output_tokens) == (7, 3)
        raise stop

    with pytest.raises(JobCancelled):
        agent.run_agent(CONFIG, system="outer", stream=False, tool_executor=execute)
    assert (_usage(stop).get("input_tokens"), _usage(stop).get("output_tokens")) == (123, 45)
    failure = LLMError("next invocation never completed a response")
    monkeypatch.setattr(agent, "chat", Mock(side_effect=failure))
    with pytest.raises(LLMError) as caught:
        agent.run_agent(CONFIG, system="next", stream=False)
    assert caught.value is failure
    assert _usage(failure) == {"model": "requested-model", "input_tokens": 0, "output_tokens": 0, "rounds": 0}
