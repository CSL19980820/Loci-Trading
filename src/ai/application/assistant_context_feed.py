"""喂模上下文：库内历史 → ChatMessage，以及 `session.metadata.context_feed` 快照。

`context_feed` 是「喂给模型的那一份」，与 `ai_messages` 里的原文分开存：手动
`/compact` 与自动压缩都只改这份快照，**不删不改库内原文**；读回时以 `through_seq`
为界，把快照之后的新消息再拼上去。

手动 `compact_session`（`assistant_manager`）与自动压缩（`assistant_run_executor`）
写的是同一份快照，两边的构造逻辑必须一致，所以集中在 `context_feed_payload`。
"""
from __future__ import annotations

from typing import Any

from src.ai.application.agent import ChatMessage
from src.ai.application.assistant_images import images_from_metadata
from src.ai.application.context_compact import CompactResult


def history_to_chat_messages(history: list[dict[str, Any]]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for item in history:
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "")
        images = images_from_metadata(
            item.get("metadata") if isinstance(item.get("metadata"), dict) else None
        )
        if role == "assistant" and not content.strip() and not images:
            continue
        messages.append(ChatMessage(role=role, content=content, images=images))
    for msg in messages:
        if msg.role == "user" and msg.images and msg.content.strip() == "（附图）":
            msg.content = ""
    return messages


def feed_messages_for_session(
    session_row: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[ChatMessage]:
    """优先用手动/上次压缩写入的 context_feed，再拼 through_seq 之后的新消息。"""
    meta = session_row.get("metadata") if isinstance(session_row.get("metadata"), dict) else {}
    feed = meta.get("context_feed") if isinstance(meta, dict) else None
    if not isinstance(feed, dict):
        return history_to_chat_messages(history)
    raw_rows = feed.get("messages")
    if not isinstance(raw_rows, list) or not raw_rows:
        return history_to_chat_messages(history)
    base: list[ChatMessage] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        base.append(ChatMessage(role=role, content=str(row.get("content") or "")))
    through_seq = int(feed.get("through_seq") or 0)
    newer = [row for row in history if int(row.get("seq") or 0) > through_seq]
    if not newer:
        return base
    return [*base, *history_to_chat_messages(newer)]


def context_feed_payload(compact: CompactResult, *, through_seq: int) -> dict[str, Any]:
    """压缩结果 → 写进 `session.metadata.context_feed` 的那份喂模快照。"""
    return {
        "messages": [
            {"role": msg.role, "content": str(msg.content or "")}
            for msg in compact.messages
        ],
        "through_seq": through_seq,
        "tokens_before": compact.tokens_before,
        "tokens_after": compact.tokens_after,
        "message": compact.event_payload().get("message"),
        "method": compact.method,
    }


__all__ = [
    "context_feed_payload",
    "feed_messages_for_session",
    "history_to_chat_messages",
]
