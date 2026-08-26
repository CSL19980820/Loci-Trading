"""agent 空回复恢复：推理指令、nudge 复位、轮次边界与错误后不编造。

从 `test_agent_events.py` 拆出（原 670 行）。
"""
from __future__ import annotations

from unittest.mock import patch

from src.ai.application.agent import run_agent
from src.ai.infrastructure.client import ChatResponse, LLMError, ProviderConfig, ToolCall


def test_agent_uses_reasoning_only_instruction_when_think_streamed() -> None:
    """OpenClaw：本轮只流式 think、无正文时用 REASONING_ONLY_RETRY_INSTRUCTION。"""
    from src.ai.application.agent import REASONING_ONLY_RETRY_INSTRUCTION
    from src.ai.application import agent as agent_mod

    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    saw_reasoning_nudge = {"ok": False}

    def fake_stream(_config, _messages, *, on_delta, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            on_delta("think", "先推一步")
            return ChatResponse(text="", model="model")
        saw_reasoning_nudge["ok"] = any(
            m.role == "user" and m.content == REASONING_ONLY_RETRY_INSTRUCTION
            for m in _messages
        )
        return ChatResponse(text="可见终稿。", model="model")

    with patch.object(agent_mod, "chat_stream", side_effect=fake_stream):
        result = run_agent(
            config,
            system="system",
            user_prompt="你好",
            emit_terminal_event=False,
            stream=True,
        )

    assert result.text == "可见终稿。"
    assert saw_reasoning_nudge["ok"] is True
    assert calls["n"] == 2


def test_agent_resets_post_tool_nudge_after_later_tool_round() -> None:
    """Hermes：后续工具轮成功后，再空可再次 post-tool nudge。"""
    from src.ai.application.agent import POST_TOOL_EMPTY_NUDGE

    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    hermes_hits = {"n": 0}

    def fake_chat(_config, messages, **_kwargs):
        calls["n"] += 1
        # 仅统计「本轮请求以 Hermes nudge 结尾」——说明刚触发过 post-tool 催办
        if (
            messages
            and messages[-1].role == "user"
            and messages[-1].content == POST_TOOL_EMPTY_NUDGE
        ):
            hermes_hits["n"] += 1
        # 1: tools A → 2: empty (nudge#1) → 3: tools B → 4: empty (nudge#2) → 5: final
        if calls["n"] == 1:
            return ChatResponse(
                text="先查仓。",
                model="model",
                tool_calls=[ToolCall(id="c1", name="qianlong_candidate_pool", arguments={})],
            )
        if calls["n"] == 2:
            return ChatResponse(text="", model="model")
        if calls["n"] == 3:
            return ChatResponse(
                text="再查盘。",
                model="model",
                tool_calls=[ToolCall(id="c2", name="qianlong_pool_evidence", arguments={})],
            )
        if calls["n"] == 4:
            return ChatResponse(text="", model="model")
        return ChatResponse(text="两轮都核对完了。", model="model")

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
            tool_executor=lambda _n, _a: {"text": "ok"},
            emit_terminal_event=False,
            stream=True,
        )

    assert result.text == "两轮都核对完了。"
    assert result.stopped_reason == "completed"
    assert hermes_hits["n"] == 2
    assert calls["n"] == 5


def test_agent_recovery_survives_max_rounds_boundary() -> None:
    """max_rounds 最后一格空回复仍可走 Hermes/OpenClaw 恢复（RECOVERY_ROUND_SLACK）。"""
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
                text="先查。",
                model="model",
                tool_calls=[ToolCall(id="c1", name="qianlong_candidate_pool", arguments={})],
            )
        if calls["n"] == 2:
            return ChatResponse(text="", model="model")
        return ChatResponse(text="边界恢复成功。", model="model")

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
            max_rounds=2,  # 工具占满硬顶后仍应能 nudge
            emit_terminal_event=False,
            stream=True,
        )

    assert result.text == "边界恢复成功。"
    assert result.stopped_reason == "completed"
    assert calls["n"] == 3


def test_agent_think_tags_only_count_as_empty() -> None:
    """Hermes strip think blocks：仅标签无可见正文 → 走 empty recovery。"""
    from src.ai.application.agent import EMPTY_RESPONSE_RETRY_INSTRUCTION

    config = ProviderConfig(
        name="test",
        protocol="openai_compatible",
        base_url="https://example.test/v1",
        api_key="key",
        model="model",
    )
    calls = {"n": 0}
    saw = {"ok": False}

    def fake_chat(_config, messages, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ChatResponse(text="<think>only reasoning</think>", model="model")
        saw["ok"] = any(
            m.role == "user" and m.content == EMPTY_RESPONSE_RETRY_INSTRUCTION
            for m in messages
        )
        return ChatResponse(text="可见答案。", model="model")

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
            emit_terminal_event=False,
            stream=True,
        )

    assert saw["ok"] is True
    assert result.text == "可见答案。"


def test_agent_drops_mid_transcript_empty_scaffolding() -> None:
    """HITL 前夹在中间的 (empty)/nudge 收口时也要清掉。"""
    from src.ai.application.agent import (
        EMPTY_ASSISTANT_SENTINEL,
        POST_TOOL_EMPTY_NUDGE,
        _drop_all_empty_recovery,
        messages_from_json,
        messages_to_json,
    )
    from src.ai import ChatMessage

    messages = [
        ChatMessage(role="user", content="平账"),
        ChatMessage(role="assistant", content="先查", tool_calls=[
            ToolCall(id="c1", name="qianlong_candidate_pool", arguments={}),
        ]),
        ChatMessage(role="tool", content="ok", tool_call_id="c1"),
        ChatMessage(role="assistant", content=EMPTY_ASSISTANT_SENTINEL),
        ChatMessage(role="user", content=POST_TOOL_EMPTY_NUDGE),
        ChatMessage(role="assistant", content="是否继续？"),
        ChatMessage(role="user", content="继续"),
    ]
    _drop_all_empty_recovery(messages)
    roles = [(m.role, m.content[:8]) for m in messages]
    assert ( "assistant", EMPTY_ASSISTANT_SENTINEL) not in [(m.role, m.content) for m in messages]
    assert all(m.content != POST_TOOL_EMPTY_NUDGE for m in messages)
    assert roles[-1] == ("user", "继续")
    # round-trip json 仍可用
    assert len(messages_from_json(messages_to_json(messages))) == len(messages)


def test_agent_slack_exhausted_empty_is_empty_completion_not_max_rounds() -> None:
    """P0：工具占满 max_rounds 后恢复仍空 → empty_completion/error，禁止伪装 max_rounds/done。"""
    events: list[dict] = []
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
        if calls["n"] <= 2:
            return ChatResponse(
                text=f"旁白{calls['n']}",
                model="model",
                tool_calls=[ToolCall(id=f"c{calls['n']}", name="qianlong_candidate_pool", arguments={})],
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
            tool_executor=lambda _n, _a: {"text": "ok"},
            max_rounds=2,
            on_event=events.append,
            emit_terminal_event=True,
            stream=True,
        )

    assert result.stopped_reason == "empty_completion"
    assert "未产出可读终稿" in result.text
    assert "旁白" not in result.text
    assert any(event["type"] == "error" for event in events)
    assert not any(event["type"] == "done" for event in events)


def test_agent_llm_error_after_tools_does_not_promote_plan_narration() -> None:
    """P1：工具后 LLMError 不得把「先读取…」旁白当失败正文。"""
    events: list[dict] = []
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
        raise LLMError("provider down")

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
            on_event=events.append,
            emit_terminal_event=True,
            stream=True,
        )

    assert result.stopped_reason.startswith("llm_error")
    assert "先读取账本" not in result.text
    assert "模型调用失败" in result.text
    err = next(event for event in events if event["type"] == "error")
    assert "先读取账本" not in str(err.get("message") or "")
