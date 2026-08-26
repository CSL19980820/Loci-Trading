"""满轮后轻量自动整理记忆。"""
from __future__ import annotations

import json
import logging
from typing import Any

from src.ai import ChatMessage, chat
from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store import AssistantStore

from src.ai.infrastructure.assistant_store_util import utc_now

logger = logging.getLogger(__name__)

_CONSOLIDATE_SYSTEM = (
    "你是 Loci 助手的记忆整理器。根据最近对话与现有记忆，只输出 JSON 对象，"
    "格式：{\"ops\":[{\"action\":\"add|replace|remove\",\"target\":\"user|memory\","
    "\"content\":\"...\",\"old_text\":\"...\"}]}。"
    "只保存稳定偏好、纠正、环境事实；不要保存临时任务进度或一次性数字。"
    "若无需变更，返回 {\"ops\":[]}。不要输出其它文字。"
)


def maybe_auto_consolidate_memory(
    store: AssistantStore,
    *,
    session_id: str,
    config: Any,
) -> dict[str, Any]:
    """成功收口后调用；失败吞掉并返回 skipped/error，不影响主回答。"""
    try:
        profile = store.get_profile()
        if not profile.get("memory_enabled") or not profile.get("auto_memory_enabled"):
            return {"status": "skipped", "reason": "disabled"}
        min_turns = int(profile.get("auto_memory_min_turns") or 20)
        count = store.count_dialog_messages(session_id)
        if count < min_turns:
            return {"status": "skipped", "reason": "below_threshold", "count": count}

        session = store.get_session(session_id) or {}
        metadata = dict(session.get("metadata") or {})
        last_count = int(metadata.get("last_auto_memory_msg_count") or 0)
        if count - last_count < min_turns and last_count > 0:
            return {"status": "skipped", "reason": "debounce", "count": count, "last": last_count}

        history = store.list_messages(session_id, limit=24)
        dialog = [
            f"{row['role']}: {str(row['content'])[:400]}"
            for row in history
            if row.get("role") in {"user", "assistant"}
        ]
        memories = store.list_memories()
        mem_blob = "\n".join(
            f"- [{row['target']}] {row['content']}" for row in memories
        ) or "(空)"
        user_prompt = (
            f"现有记忆：\n{mem_blob}\n\n最近对话：\n" + "\n".join(dialog[-20:])
        )
        response = chat(
            config,
            [ChatMessage(role="user", content=user_prompt[:8000])],
            system=_CONSOLIDATE_SYSTEM,
            max_tokens=800,
            temperature=0.2,
        )
        ops = _parse_ops(response.text or "")
        applied = 0
        for op in ops:
            if _apply_op(store, op):
                applied += 1
        metadata["last_auto_memory_msg_count"] = count
        metadata["last_auto_memory_at"] = utc_now()
        store.update_session(session_id, metadata=metadata)
        return {"status": "ok", "applied": applied, "ops": len(ops)}
    except Exception as exc:
        logger.warning("auto memory consolidate failed: %s", exc)
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _parse_ops(text: str) -> list[dict[str, Any]]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return []
    ops = payload.get("ops") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        return []
    return [item for item in ops if isinstance(item, dict)]


def _apply_op(store: AssistantStore, op: dict[str, Any]) -> bool:
    action = str(op.get("action") or "").strip()
    target = str(op.get("target") or "").strip()
    content = str(op.get("content") or "").strip()
    old_text = str(op.get("old_text") or "").strip()
    try:
        if action == "add" and content:
            store.add_memory(target=target, content=content, source="auto")
            return True
        if action == "replace" and old_text and content:
            store.replace_memory_by_text(
                target=target, old_text=old_text, content=content, source="auto"
            )
            return True
        if action == "remove" and old_text:
            store.remove_memory_by_text(target=target, old_text=old_text)
            return True
    except AssistantError:
        return False
    return False
