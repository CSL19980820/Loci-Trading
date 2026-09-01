"""空 completion 时降级 thinking 再调一次（推理模型常见补丁）。"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from src.ai.application.quota import record_llm_usage
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
    ops_db: str | None = None,
) -> str:
    """先按 preferred thinking 调用；空文本则降到无 thinking 再试。

    返回首段非空 ``result.text``；两档皆空则空串（调用方自行 fail-closed / 忽略）。

    **每一档都计费**：降级重试是真花了两次钱的，只算最后一次会系统性低估。
    调用方（纸面盯盘、风格复盘）拿到的是纯文本、看不见 token，计费只能在这里做。
    ``ops_db`` 传调用方手里那条库路径，别让用量写去另一个租户的库。
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
        record_llm_usage(
            provider=config.name,
            model=getattr(result, "model", "") or config.model,
            input_tokens=getattr(result, "input_tokens", 0),
            output_tokens=getattr(result, "output_tokens", 0),
            ops_db=ops_db,
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
