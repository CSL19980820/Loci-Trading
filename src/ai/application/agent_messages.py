"""Agent消息快照序列化，保留工具调用所需的原始推理字段。"""
from __future__ import annotations

from typing import Any
from src.ai.infrastructure.client import ChatMessage, ToolCall


def messages_to_json(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        item: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            item["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            item["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in msg.tool_calls
            ]
        if msg.reasoning_content is not None:
            item["reasoning_content"] = msg.reasoning_content
        out.append(item)
    return out


def messages_from_json(raw: list[dict[str, Any]] | None) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for item in raw or []:
        calls = [
            ToolCall(
                id=str(c.get("id") or ""),
                name=str(c.get("name") or ""),
                arguments=c.get("arguments") if isinstance(c.get("arguments"), dict) else {},
            )
            for c in (item.get("tool_calls") or [])
            if isinstance(c, dict)
        ]
        messages.append(
            ChatMessage(
                role=str(item.get("role") or "user"),
                content=str(item.get("content") or ""),
                tool_calls=calls,
                tool_call_id=str(item.get("tool_call_id") or ""),
                reasoning_content=item.get("reasoning_content") if isinstance(item.get("reasoning_content"), str) else None,
            )
        )
    return messages
