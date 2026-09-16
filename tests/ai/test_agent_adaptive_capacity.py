"""Removing arbitrary call-count ceilings does not remove cancellation or real deadlines."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai import ChatResponse, ProviderConfig, ToolCall
from src.ai.application import agent, agent_budget

PROVIDER = ProviderConfig("test", "openai_compatible", "https://example.invalid", "test", "test")


def test_more_than_sixteen_rounds_and_twelve_calls_are_executed(monkeypatch):
    responses = [ChatResponse(text="research", tool_calls=[ToolCall(id=f"r{i}-c{j}", name="read", arguments={})
                 for j in range(20)]) for i in range(18)]
    responses.append(ChatResponse(text="complete", raw={"finish_reason": "stop"}))
    monkeypatch.setattr(agent, "chat", Mock(side_effect=responses))
    tools = Mock(return_value={"text": "evidence"})
    result = agent.run_agent(PROVIDER, system="test", stream=False, tool_executor=tools,
                             max_rounds=None, max_calls_per_round=None, deadline=time.monotonic() + 30)
    assert result.stopped_reason == "completed" and result.text == "complete"
    assert result.rounds == 19 and tools.call_count == 360
    assert len(result.invocations) == 360 and all(call.executed for call in result.invocations)
    assert len({call.tool_call_id for call in result.invocations}) == 360


def test_deadline_still_stops_an_open_ended_research_loop(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(agent_budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def chat(*args, **kwargs):
        clock[0] += 1
        return ChatResponse(text="research", tool_calls=[ToolCall(id=str(clock[0]), name="read", arguments={})])
    monkeypatch.setattr(agent, "chat", chat)
    tools = Mock(return_value={"text": "evidence"})
    with pytest.raises(TimeoutError):
        agent.run_agent(PROVIDER, system="test", stream=False, tool_executor=tools,
                        max_rounds=None, max_calls_per_round=None, deadline=15)
    assert clock[0] == 15 and tools.call_count == 4


def test_open_ended_mode_requires_a_real_deadline():
    with pytest.raises(ValueError, match="截止"):
        agent.run_agent(PROVIDER, system="test", max_rounds=None, deadline=None)
