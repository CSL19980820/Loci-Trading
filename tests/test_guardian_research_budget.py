"""Keep intraday delivery timely without reducing available research tools."""

import json
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.ai.application import agent
from src.ai.infrastructure.client import (
    ChatResponse, LLMGenerationInterrupted, ProviderConfig, ToolCall,
)
from src.ops.application import guardian_agent, guardian_completion, guardian_config
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_research_context import ResearchContext


def provider():
    return ProviderConfig("fixture", "openai_compatible", "https://example.invalid", "fixture", model="fixture")


def schema():
    return {"type": "function", "function": {"name": "read_probe",
            "parameters": {"type": "object", "properties": {}}}}


@pytest.mark.parametrize("remaining", [200, 121, 120, 91, 90, 1, 0])
def test_guardian_budget_tracks_remaining_time_and_delivery_stages(monkeypatch, remaining):
    monkeypatch.setattr(guardian_agent.time, "monotonic", lambda: 100)
    instruction = guardian_agent._research_budget_instruction(100 + remaining)
    assert f"剩余{remaining:.1f}秒" in instruction
    assert "全部工具保持可用" in instruction and "JSON" in instruction
    if remaining <= 90:
        assert "立即" in instruction
    elif remaining <= 120:
        assert "开始收束" in instruction
    else:
        assert "立即" not in instruction


def test_agent_refreshes_instruction_on_tool_rounds_and_generation_recovery(monkeypatch):
    offered = [schema()]
    prompts, budget_prompts, messages, executed = [], [], [], []
    instructions = iter(["budget-marker-200", "budget-marker-150", "budget-marker-145", "budget-marker-90"])

    def output_budget(_config, _messages, *, system, **_kwargs):
        budget_prompts.append(system)
        return 4096

    def stream(_config, current_messages, **options):
        prompts.append(options["system"])
        messages.append(deepcopy(current_messages))
        assert options["tools"] is offered
        if len(prompts) == 2:
            options["on_delta"]("token", "unfinished response")
            raise LLMGenerationInterrupted("injected interrupted stream")
        if len(prompts) in {1, 3}:
            return ChatResponse("", tool_calls=[ToolCall(f"read-{len(prompts)}", "read_probe", {})],
                                raw={"finish_reason": "tool_calls"})
        return ChatResponse('{"summary":"完成","orders":[]}', raw={"finish_reason": "stop"})

    def execute(name, _arguments):
        executed.append(name)
        return {"text": "completed evidence"}

    monkeypatch.setattr(agent, "output_budget", output_budget)
    monkeypatch.setattr(agent, "chat_stream", stream)
    result = agent.run_agent(provider(), system="base system", user_prompt="fixture",
        tool_schemas=offered, tool_executor=execute, max_rounds=None, max_calls_per_round=None,
        request_instruction=lambda: next(instructions), deadline=time.monotonic() + 30,
        retry_stream_failures=True, recover_interrupted_generation=True)

    assert result.text == '{"summary":"完成","orders":[]}'
    assert executed == ["read_probe", "read_probe"]
    assert prompts == budget_prompts
    assert len(prompts) == 4 and result.rounds == 3
    for prompt, marker in zip(prompts, ["200", "150", "145", "90"], strict=True):
        assert prompt.startswith("base system")
        assert prompt.count("budget-marker-") == 1
        assert f"budget-marker-{marker}" in prompt
    assert all("budget-marker-" not in message.content for request in messages for message in request)
    assert messages[1] == messages[2]  # The completed tool result survives the retry exactly once.


@pytest.mark.parametrize("stream", [True, False])
def test_default_agent_request_keeps_original_system_and_tools(monkeypatch, stream):
    offered = [schema()]
    seen = []

    def complete(_config, _messages, **options):
        seen.append(options)
        return ChatResponse("completed", raw={"finish_reason": "stop"})

    monkeypatch.setattr(agent, "chat_stream", complete)
    monkeypatch.setattr(agent, "chat", complete)
    result = agent.run_agent(provider(), system="original system", user_prompt="fixture",
                             tool_schemas=offered, stream=stream)
    assert result.text == "completed"
    assert len(seen) == 1
    assert seen[0]["system"] == "original system" and seen[0]["tools"] is offered


@pytest.mark.parametrize("enabled", [True, False])
def test_completion_forwards_instruction_only_when_enabled(monkeypatch, enabled):
    calls = []
    instruction = lambda: "current research budget"

    def complete(_provider, _store, _usage, **options):
        calls.append(options)
        text = '{"summary":' if len(calls) == 1 else '{"summary":"完成","orders":[]}'
        return SimpleNamespace(text=text, finish_reason="stop",
                               stopped_reason="completed", input_tokens=0, output_tokens=0, messages=[])

    monkeypatch.setattr(guardian_completion, "run_accounted_agent", complete)
    options = {"request_instruction": instruction} if enabled else {}
    guardian_completion.complete_decision(
        SimpleNamespace(model="fixture", context_window=None, max_output_tokens=None), None,
        system="fixture", payload={}, schemas=[], execute=lambda *_: {}, archive=ResearchContext(),
        checkpoint=lambda *_: None, deadline=time.monotonic() + 30, config={}, **options)
    assert len(calls) == 2
    for call in calls:
        assert call["max_rounds"] is None and call["max_calls_per_round"] is None
        if enabled:
            assert call["request_instruction"] is instruction
        else:
            assert "request_instruction" not in call


def test_guardian_enables_request_budget_for_current_cycle(monkeypatch):
    import src.ai

    captured, deadlines = {}, []
    monkeypatch.setattr(src.ai, "resolve_config", lambda *_args, **_kwargs:
                        SimpleNamespace(model="fixture", protocol="openai_compatible"))
    monkeypatch.setattr(guardian_agent, "compose_research_tools", lambda *_args, **_kwargs:
                        ([], lambda *_: {}, {}))

    def instruction(deadline):
        deadlines.append(deadline)
        return f"budget-{len(deadlines)}"

    def complete(_provider, _store, **options):
        captured.update(options)
        return GuardianDecision(summary="完成", orders=[]), {"tools": []}

    monkeypatch.setattr(guardian_agent, "_research_budget_instruction", instruction)
    monkeypatch.setattr(guardian_agent, "complete_decision", complete)
    deadline = time.monotonic() + 230
    guardian_agent.decide(None, {**guardian_config.DEFAULTS, "model": "fixture"},
        {"as_of": "2026-10-13T11:20:00+08:00", "portfolio": {"positions": [], "watchlist": []}},
        deadline=deadline)
    assert captured["request_instruction"]() == "budget-1"
    assert captured["request_instruction"]() == "budget-2"
    assert deadlines == [deadline, deadline]


def test_stock_agent_does_not_inherit_intraday_budget_instructions(monkeypatch):
    from src.ops.application import stock_agent_decide

    captured = {}
    monkeypatch.setattr(stock_agent_decide, "resolve_config", lambda *_args, **_kwargs:
                        SimpleNamespace(model="fixture", protocol="openai_compatible"))
    monkeypatch.setattr(stock_agent_decide, "stock_agent_tools", lambda *_args, **_kwargs:
                        ([], lambda *_: {}, {}))

    def complete(_provider, _store, **options):
        captured.update(options)
        result = options["decision_parser"](json.dumps({"summary": "观察", "orders": []}),
                                            require_execution_terms=True)
        return result, {"model": "fixture", "context_documents": {}}

    monkeypatch.setattr(stock_agent_decide, "complete_decision", complete)
    config = {"kind": "falcon", "provider": "fixture", "model": "fixture", "prompt": "研判",
              "common_prompt": "", "daily_selection_limit": 0, "watch_limit": 0,
              "position_limit": 0, "temporary_position_limit": 0, "max_position_pct": 100}
    stock_agent_decide.decide_stock_agent(None, {"config": config},
        {"phase": "research", "research_date": "2026-10-13", "portfolio": {"positions": [], "watchlist": []},
         "candidate_scope": {"research_codes": []}}, palace_path="unused",
        checkpoint=lambda *_: None, deadline=time.monotonic() + 30)
    assert "request_instruction" not in captured
