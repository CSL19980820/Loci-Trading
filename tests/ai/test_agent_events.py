from __future__ import annotations

from unittest.mock import patch

from src.ai.application.agent import run_agent
from src.ai.infrastructure.client import ChatResponse, ProviderConfig


def test_outer_lifecycle_can_suppress_agent_terminal_event() -> None:
    events: list[dict] = []
    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )

    with patch(
        "src.ai.application.agent.chat",
        return_value=ChatResponse(text="完成", model="model"),
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="hello",
            on_event=events.append,
            emit_terminal_event=False,
        )

    assert result.stopped_reason == "completed"
    assert [event["type"] for event in events] == ["round_start"]


def test_agent_done_event_includes_final_text() -> None:
    events: list[dict] = []
    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )

    with patch(
        "src.ai.application.agent.chat",
        return_value=ChatResponse(text="终稿答复", model="model"),
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="hello",
            on_event=events.append,
            emit_terminal_event=True,
        )

    assert result.text == "终稿答复"
    done = next(event for event in events if event["type"] == "done")
    assert done["text"] == "终稿答复"
    assert done["content"] == "终稿答复"
