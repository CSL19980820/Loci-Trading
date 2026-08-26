"""agent 事件流：终态事件抑制、工具轮后的空回复与重试。

后半部分（推理指令 / nudge 复位 / 边界）在 `test_agent_events_recovery.py`。
"""
from __future__ import annotations

from unittest.mock import patch

from src.ai.application.agent import run_agent
from src.ai.infrastructure.client import ChatResponse, LLMError, ProviderConfig, ToolCall


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
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
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
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
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


def test_agent_recovers_when_post_tool_round_returns_empty_text() -> None:
    """Hermes 对齐：工具后空正文 → assistant(empty)+user nudge，tools 仍可用。"""
    from src.ai.application.agent import POST_TOOL_EMPTY_NUDGE

    events: list[dict] = []
    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    saw_tools_on_nudge = {"ok": False}
    nudge_tail: list[dict] = []

    def fake_chat(_config, messages, **kwargs):
        calls["n"] += 1
        # 催办轮必须仍带 tools，禁止禁工具
        if calls["n"] >= 3:
            saw_tools_on_nudge["ok"] = kwargs.get("tools") is not None
            nudge_tail.clear()
            nudge_tail.extend(
                {"role": m.role, "content": m.content}
                for m in messages[-2:]
            )
        if calls["n"] == 1:
            return ChatResponse(
                text="先读取账本再决定。",
                model="model",
                tool_calls=[ToolCall(id="c1", name="qianlong_candidate_pool", arguments={})],
            )
        if calls["n"] == 2:
            return ChatResponse(text="", model="model")
        return ChatResponse(text="账已核对：建议补记卖出 400 股。", model="model")

    with patch(
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
        "src.ai.application.agent.chat",
        side_effect=fake_chat,
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="平账",
            tool_schemas=[{"name": "qianlong_candidate_pool"}],
            tool_executor=lambda _n, _a: {"text": "持仓 1 只"},
            on_event=events.append,
            emit_terminal_event=True,
            stream=True,
        )

    assert result.text == "账已核对：建议补记卖出 400 股。"
    assert result.stopped_reason == "completed"
    assert calls["n"] == 3
    assert saw_tools_on_nudge["ok"] is True
    assert nudge_tail == [
        {"role": "assistant", "content": "(empty)"},
        {"role": "user", "content": POST_TOOL_EMPTY_NUDGE},
    ]
    # 终稿不是工具前计划句
    assert "先读取账本" not in result.text
    done = next(event for event in events if event["type"] == "done")
    assert "补记卖出" in done["text"]


def test_agent_nudge_round_can_still_call_tools() -> None:
    """Hermes：催办后模型仍可调工具，再给出终稿。"""
    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    tool_hits = {"n": 0}

    def fake_chat(_config, _messages, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ChatResponse(
                text="先查。",
                model="model",
                tool_calls=[ToolCall(id="c1", name="qianlong_candidate_pool", arguments={})],
            )
        if calls["n"] == 2:
            return ChatResponse(text="", model="model")  # 空 → Hermes post-tool nudge
        if calls["n"] == 3:
            return ChatResponse(
                text="",
                model="model",
                tool_calls=[ToolCall(id="c2", name="qianlong_pool_evidence", arguments={})],
            )
        return ChatResponse(text="已用仪表盘核对完毕。", model="model")

    def executor(name: str, _arguments: dict) -> dict:
        tool_hits["n"] += 1
        return {"text": f"{name} ok"}

    with patch(
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
        "src.ai.application.agent.chat",
        side_effect=fake_chat,
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="平账",
            tool_schemas=[{"name": "qianlong_candidate_pool"}, {"name": "qianlong_pool_evidence"}],
            tool_executor=executor,
            emit_terminal_event=False,
            stream=True,
        )

    assert result.text == "已用仪表盘核对完毕。"
    assert tool_hits["n"] == 2
    assert result.stopped_reason == "completed"


def test_agent_marks_empty_completion_when_recovery_also_blank() -> None:
    """OpenClaw：空回复重试耗尽后显式失败，不伪装 completed。"""
    from src.ai.application.agent import EMPTY_RESPONSE_RETRY_INSTRUCTION

    events: list[dict] = []
    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    saw_openclaw_nudge = {"ok": False}

    def fake_chat(_config, messages, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            saw_openclaw_nudge["ok"] = any(
                m.role == "user" and m.content == EMPTY_RESPONSE_RETRY_INSTRUCTION
                for m in messages
            )
        return ChatResponse(text="", model="model")

    with patch(
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
        "src.ai.application.agent.chat",
        side_effect=fake_chat,
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="你好",
            on_event=events.append,
            emit_terminal_event=True,
        )

    assert calls["n"] == 2
    assert saw_openclaw_nudge["ok"] is True
    assert result.stopped_reason == "empty_completion"
    assert "未产出可读终稿" in result.text
    err = next(event for event in events if event["type"] == "error")
    assert err["stopped_reason"] == "empty_completion"
    assert not any(event["type"] == "done" for event in events)


def test_agent_post_tool_empty_does_not_promote_plan_narration() -> None:
    """Hermes：实质工具后空跟进不得把「先读取…」旁白当终稿。"""
    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}

    def fake_chat(_config, _messages, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ChatResponse(
                text="先读取账本核实当前状态，再决定怎么平。",
                model="model",
                tool_calls=[ToolCall(id="c1", name="qianlong_candidate_pool", arguments={})],
            )
        return ChatResponse(text="", model="model")

    with patch(
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
        "src.ai.application.agent.chat",
        side_effect=fake_chat,
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="平账",
            tool_schemas=[{"name": "qianlong_candidate_pool"}],
            tool_executor=lambda _n, _a: {"text": "持仓 1 只"},
            emit_terminal_event=False,
            stream=True,
        )

    assert result.stopped_reason == "empty_completion"
    assert "先读取账本" not in result.text
    assert "未产出可读终稿" in result.text
    # tools → empty(Hermes nudge) → empty(OpenClaw retry) → empty fail
    assert calls["n"] == 4
    # Hermes：收口 transcript 不含合成 (empty)/nudge
    assert all(
        not (
            m.get("role") == "assistant"
            and m.get("content") == "(empty)"
        )
        for m in result.messages
    )


def test_agent_post_tool_then_openclaw_empty_retry_recovers() -> None:
    """Hermes post-tool 催完仍空时，再走 OpenClaw empty retry（工具保持）。"""
    from src.ai.application.agent import (
        EMPTY_RESPONSE_RETRY_INSTRUCTION,
        POST_TOOL_EMPTY_NUDGE,
    )

    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    saw = {"hermes": False, "openclaw": False, "tools": False}

    def fake_chat(_config, messages, **kwargs):
        calls["n"] += 1
        contents = [m.content for m in messages if m.role == "user"]
        if POST_TOOL_EMPTY_NUDGE in contents:
            saw["hermes"] = True
        if EMPTY_RESPONSE_RETRY_INSTRUCTION in contents:
            saw["openclaw"] = True
        if calls["n"] >= 3:
            saw["tools"] = kwargs.get("tools") is not None
        if calls["n"] == 1:
            return ChatResponse(
                text="先查。",
                model="model",
                tool_calls=[ToolCall(id="c1", name="qianlong_candidate_pool", arguments={})],
            )
        if calls["n"] in {2, 3}:
            return ChatResponse(text="", model="model")
        return ChatResponse(text="核对完毕。", model="model")

    with patch(
        "src.ai.application.agent.chat_stream",
        side_effect=LLMError("no stream"),
    ), patch(
        "src.ai.application.agent.chat",
        side_effect=fake_chat,
    ):
        result = run_agent(
            config,
            system="system",
            user_prompt="平账",
            tool_schemas=[{"name": "qianlong_candidate_pool"}],
            tool_executor=lambda _n, _a: {"text": "ok"},
            emit_terminal_event=False,
            stream=True,
        )

    assert result.text == "核对完毕。"
    assert result.stopped_reason == "completed"
    assert calls["n"] == 4
    assert saw == {"hermes": True, "openclaw": True, "tools": True}
