"""chat_text_with_thinking_fallback：空 content 降 thinking 再试。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.ai import ChatMessage, chat_text_with_thinking_fallback
from src.ai.infrastructure.client import ProviderConfig


def _cfg() -> ProviderConfig:
    return ProviderConfig(
        name="t",
        protocol="openai_compatible",
        base_url="http://localhost",
        api_key="x",
        model="m",
    )


def test_thinking_fallback_retries_when_first_empty() -> None:
    calls: list[str] = []

    def fake_chat(config, messages, *, system="", thinking="", **_kw):
        calls.append(thinking or "off")
        if thinking:
            return SimpleNamespace(text="", raw={"choices": [{"finish_reason": "length"}]})
        return SimpleNamespace(text="  ok  ", raw={})

    with patch("src.ai.infrastructure.chat_retry.chat", side_effect=fake_chat):
        text = chat_text_with_thinking_fallback(
            _cfg(),
            [ChatMessage(role="user", content="hi")],
            system="sys",
            thinking="medium",
        )
    assert text == "ok"
    assert calls == ["medium", "off"]


def test_thinking_fallback_returns_empty_when_both_blank() -> None:
    with patch(
        "src.ai.infrastructure.chat_retry.chat",
        return_value=SimpleNamespace(text="", raw={}),
    ):
        text = chat_text_with_thinking_fallback(
            _cfg(),
            [ChatMessage(role="user", content="hi")],
            thinking="high",
        )
    assert text == ""
