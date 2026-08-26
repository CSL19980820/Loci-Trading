"""喂模历史自动压缩（auto-compact）。

只改「送给模型的 messages」；不删不改写 SQLite 会话原文。
与跨会话记忆整理（maybe_auto_consolidate_memory）独立。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.ai.application.context_usage import estimate_tokens
from src.ai.infrastructure.client import ChatMessage

DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_THRESHOLD_RATIO = 0.70
DEFAULT_KEEP_TURNS = 6
DEFAULT_SUMMARY_CHARS = 2_400
COMPACT_NOTICE = "已压缩较早对话（库内原文仍在）"


@dataclass(frozen=True)
class CompactResult:
    messages: list[ChatMessage]
    compacted: bool
    removed_count: int = 0
    kept_count: int = 0
    kept_turns: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    summary: str = ""
    method: str = "none"  # none | llm | deterministic
    meta: dict[str, Any] = field(default_factory=dict)

    def event_payload(self) -> dict[str, Any]:
        return {
            "type": "context_compacted",
            "message": COMPACT_NOTICE,
            "removed": self.removed_count,
            "kept": self.kept_count,
            "kept_turns": self.kept_turns,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "method": self.method,
            "summary_preview": (self.summary or "")[:240],
        }


def estimate_messages_tokens(messages: list[ChatMessage] | None) -> int:
    """会话段粗估：拼接 role + content（附图按占位计）。"""
    if not messages:
        return 0
    parts: list[str] = []
    for msg in messages:
        role = str(msg.role or "")
        content = str(msg.content or "")
        if not content.strip() and getattr(msg, "images", None):
            content = "（附图）"
        parts.append(f"{role}\n{content}")
    return estimate_tokens("\n\n".join(parts))


def compact_threshold_tokens(
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    reserve_tokens: int = 0,
    threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
) -> int:
    """可用窗 = context_window − 系统/工具预留；阈值 = 可用窗 × ratio。"""
    window = max(1_024, int(context_window or DEFAULT_CONTEXT_WINDOW))
    usable = max(1_024, window - max(0, int(reserve_tokens)))
    ratio = float(threshold_ratio)
    if ratio <= 0 or ratio > 1:
        ratio = DEFAULT_THRESHOLD_RATIO
    return max(1, int(usable * ratio))


def _group_turns(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """一轮 = 一条 user 及其后的非 user 消息（assistant/tool）。"""
    groups: list[list[ChatMessage]] = []
    for msg in messages:
        if msg.role == "user" or not groups:
            groups.append([msg])
        else:
            groups[-1].append(msg)
    return groups


def _transcript(messages: list[ChatMessage]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = "用户" if msg.role == "user" else "助手" if msg.role == "assistant" else msg.role
        text = str(msg.content or "").strip().replace("\n", " ")
        if not text and getattr(msg, "images", None):
            text = "（附图）"
        if text:
            lines.append(f"{role}：{text[:400]}")
    return "\n".join(lines)


def _deterministic_summary(messages: list[ChatMessage], *, max_chars: int = DEFAULT_SUMMARY_CHARS) -> str:
    """失败回退：头尾拼接，禁止静默丢光。"""
    body = _transcript(messages)
    if not body.strip():
        return "（较早对话无可用正文；库内原文仍在）"
    if len(body) <= max_chars:
        return body
    half = max(200, max_chars // 2)
    return f"{body[:half]}\n…\n{body[-half:]}"


def _summarize(
    older: list[ChatMessage],
    *,
    summarizer: Callable[[str], str] | None,
) -> tuple[str, str]:
    transcript = _transcript(older)
    if summarizer is not None:
        try:
            text = str(summarizer(transcript) or "").strip()
            if text:
                return text, "llm"
        except Exception:
            pass
    return _deterministic_summary(older), "deterministic"


def compact_feed_messages(
    messages: list[ChatMessage] | None,
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    reserve_tokens: int = 0,
    threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
    keep_turns: int = DEFAULT_KEEP_TURNS,
    summarizer: Callable[[str], str] | None = None,
    force: bool = False,
) -> CompactResult:
    """超阈值才压缩；``force=True`` 时（手动 /compact）无视阈值仍压。

    保留最近 ``keep_turns`` 轮原文；更早轮写入一条摘要 user 消息。
    """
    source = list(messages or [])
    tokens_before = estimate_messages_tokens(source)
    threshold = compact_threshold_tokens(
        context_window=context_window,
        reserve_tokens=reserve_tokens,
        threshold_ratio=threshold_ratio,
    )
    keep = max(DEFAULT_KEEP_TURNS, int(keep_turns or DEFAULT_KEEP_TURNS))
    if not source:
        return CompactResult(
            messages=source,
            compacted=False,
            removed_count=0,
            kept_count=0,
            kept_turns=0,
            tokens_before=0,
            tokens_after=0,
            method="none",
            meta={"threshold": threshold, "force": force},
        )
    if not force and tokens_before < threshold:
        return CompactResult(
            messages=source,
            compacted=False,
            removed_count=0,
            kept_count=len(source),
            kept_turns=len(_group_turns(source)) if source else 0,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            method="none",
            meta={"threshold": threshold},
        )

    turns = _group_turns(source)
    if len(turns) <= keep:
        # 轮数不够切，但对超阈值长正文仍做摘要；保留末条原文，禁止静默丢光
        summary, method = _summarize(source, summarizer=summarizer)
        tail = source[-1:]
        out = [ChatMessage(role="user", content=f"（{COMPACT_NOTICE}）\n{summary}"), *tail]
        tokens_after = estimate_messages_tokens(out)
        if tokens_after >= tokens_before:
            summary = _deterministic_summary(source, max_chars=800)
            out = [ChatMessage(role="user", content=f"（{COMPACT_NOTICE}）\n{summary}"), *tail]
            tokens_after = estimate_messages_tokens(out)
            method = "deterministic"
        if tokens_after >= tokens_before:
            return CompactResult(
                messages=source,
                compacted=False,
                removed_count=0,
                kept_count=len(source),
                kept_turns=len(turns),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                method="none",
                meta={"threshold": threshold, "reason": "few_turns_no_savings", "force": force},
            )
        return CompactResult(
            messages=out,
            compacted=True,
            removed_count=max(0, len(source) - len(tail)),
            kept_count=len(out),
            kept_turns=1,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            summary=summary,
            method=method,
            meta={"threshold": threshold, "reason": "few_turns"},
        )

    older_turns = turns[:-keep]
    kept_turns_list = turns[-keep:]
    older = [msg for group in older_turns for msg in group]
    kept = [msg for group in kept_turns_list for msg in group]
    summary, method = _summarize(older, summarizer=summarizer)
    summary_msg = ChatMessage(
        role="user",
        content=f"（{COMPACT_NOTICE}）\n{summary}",
    )
    out = [summary_msg, *kept]
    tokens_after = estimate_messages_tokens(out)
    if tokens_after >= tokens_before:
        short = _deterministic_summary(older, max_chars=800)
        out = [ChatMessage(role="user", content=f"（{COMPACT_NOTICE}）\n{short}"), *kept]
        tokens_after = estimate_messages_tokens(out)
        method = "deterministic"
        summary = short
    if tokens_after >= tokens_before:
        return CompactResult(
            messages=source,
            compacted=False,
            removed_count=0,
            kept_count=len(source),
            kept_turns=len(turns),
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            method="none",
            meta={"threshold": threshold, "reason": "no_savings", "force": force},
        )

    return CompactResult(
        messages=out,
        compacted=True,
        removed_count=len(older),
        kept_count=len(kept) + 1,
        kept_turns=keep,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        summary=summary,
        method=method,
        meta={"threshold": threshold},
    )

__all__ = [
    "COMPACT_NOTICE",
    "CompactResult",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_KEEP_TURNS",
    "DEFAULT_THRESHOLD_RATIO",
    "compact_feed_messages",
    "compact_threshold_tokens",
    "estimate_messages_tokens",
]
