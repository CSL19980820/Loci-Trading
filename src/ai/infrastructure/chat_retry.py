"""空 completion 时降级 thinking 再调一次（推理模型常见补丁）。"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from src.ai.infrastructure.client import ChatMessage, ProviderConfig, chat

logger = logging.getLogger(__name__)


def chat_text_with_thinking_fallback(
    config: ProviderConfig,
    messages: Sequence[ChatMessage],
    *,
    system: str = "",
    thinking: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    log: logging.Logger | None = None,
) -> str:
    """先按 preferred thinking 调用；空文本则降到无 thinking 再试。

    返回首段非空 ``result.text``；两档皆空则 ``\"\"``（调用方自行 fail-closed / 忽略）。
    """
    log = log or logger
    efforts = [thinking or "", ""]
    seen: set[str] = set()
    for effort in efforts:
        key = effort or "off"
        if key in seen:
            continue
        seen.add(key)
        result = chat(
            config,
            list(messages),
            system=system,
            thinking=effort if effort and effort != "off" else "",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = str(getattr(result, "text", None) or "").strip()
        if text:
            return text
        finish = ""
        usage: Any = {}
        raw = getattr(result, "raw", None) or {}
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            if choices:
                finish = str((choices[0] or {}).get("finish_reason") or "")
            usage = raw.get("usage") or {}
        log.warning(
            "llm empty content (thinking=%s finish=%s usage=%s); retrying without thinking",
            key,
            finish,
            usage,
        )
    return ""
