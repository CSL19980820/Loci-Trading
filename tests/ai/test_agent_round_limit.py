"""工具轮硬顶：撞上限时如何收口。"""
from __future__ import annotations

from unittest.mock import patch

from src.ai import ChatResponse, LLMError, ProviderConfig, ToolCall
from src.ai.application.agent import run_agent

_CONFIG = ProviderConfig(
    name="test",
    protocol="openai_compatible",
    base_url="https://example.test/v1",
    api_key="key",
    model="model",
)


def test_max_rounds_refusal_reports_completed_rounds_without_narration() -> None:
    """拒绝的那一轮不算已完成轮次，也不得把工具前旁白当终稿。"""
    calls = {"n": 0}

    def fake_chat(_config, _messages, **_kwargs):
        calls["n"] += 1
        return ChatResponse(
            text=f"我再查一轮资金流{calls['n']}。",
            model="model",
            tool_calls=[ToolCall(id=f"c{calls['n']}", name="qianlong_candidate_pool", arguments={})],
        )

    with (
        patch("src.ai.application.agent.chat_stream", side_effect=LLMError("no stream")),
        patch("src.ai.application.agent.chat", side_effect=fake_chat),
    ):
        result = run_agent(
            _CONFIG,
            system="system",
            user_prompt="平账",
            tool_schemas=[{"name": "qianlong_candidate_pool"}],
            tool_executor=lambda _n, _a: {"text": "ok"},
            max_rounds=2,
            emit_terminal_event=False,
            stream=True,
        )

    assert result.stopped_reason == "max_rounds"
    assert result.rounds == 2
    assert len(result.invocations) == 2
    assert "我再查一轮资金流" not in result.text
    assert "轮数上限" in result.text


def test_last_round_may_still_summarize_within_the_slack() -> None:
    """工具占满硬顶后仍给模型一次收口机会：拿到终稿就算 completed。"""
    calls = {"n": 0}

    def fake_chat(_config, _messages, **_kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            return ChatResponse(
                text="先查。",
                model="model",
                tool_calls=[ToolCall(id=f"c{calls['n']}", name="qianlong_candidate_pool", arguments={})],
            )
        return ChatResponse(text="两轮证据够了，结论如下。", model="model")

    with (
        patch("src.ai.application.agent.chat_stream", side_effect=LLMError("no stream")),
        patch("src.ai.application.agent.chat", side_effect=fake_chat),
    ):
        result = run_agent(
            _CONFIG,
            system="system",
            user_prompt="平账",
            tool_schemas=[{"name": "qianlong_candidate_pool"}],
            tool_executor=lambda _n, _a: {"text": "ok"},
            max_rounds=2,
            emit_terminal_event=False,
            stream=True,
        )

    assert result.stopped_reason == "completed"
    assert result.text == "两轮证据够了，结论如下。"
    assert "轮数上限" not in result.text
