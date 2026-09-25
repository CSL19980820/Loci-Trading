"""会话侧栏标题：占位检测、首条消息临时标题、模型精炼。"""
from __future__ import annotations

import logging
import re
from typing import Any

from src.ai import ChatMessage, chat
from src.ai.application.quota import record_llm_usage
from src.ai.domain.assistant import AssistantError

logger = logging.getLogger(__name__)

PLACEHOLDER_TITLES = frozenset({
    "",
    "新对话",
    "新会话",
    "untitled",
    "new chat",
    "new conversation",
})

_TITLE_SYSTEM = (
    "你为本地量化工作台的对话侧栏生成标题。"
    "只输出一行中文短标题，8～18 个字，概括用户这一轮想做什么；"
    "不要引号、不要句号、不要「新对话」这类空标题、不要模型名。"
)


def is_placeholder_title(title: str | None) -> bool:
    return (title or "").strip().lower() in PLACEHOLDER_TITLES


def is_title_locked(metadata: dict[str, Any] | None) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    return bool(meta.get("title_locked"))


def title_source(metadata: dict[str, Any] | None) -> str:
    meta = metadata if isinstance(metadata, dict) else {}
    return str(meta.get("title_source") or "")


def needs_provisional_title(title: str | None, metadata: dict[str, Any] | None = None) -> bool:
    if is_title_locked(metadata):
        return False
    return is_placeholder_title(title)


def needs_llm_title(title: str | None, metadata: dict[str, Any] | None = None) -> bool:
    if is_title_locked(metadata):
        return False
    source = title_source(metadata)
    if source == "llm":
        return False
    return is_placeholder_title(title) or source in {"", "provisional"}


def provisional_title(user_message: str, *, max_chars: int = 28) -> str:
    """从首条用户消息生成立即可用的侧栏标题（不调模型）。"""
    text = " ".join((user_message or "").strip().split())
    text = re.sub(r"^[#>*\-\d.\s]+", "", text).strip()
    if not text:
        return "未命名对话"
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rstrip("，,、;；:： ")
    return f"{cut}…"


def sanitize_llm_title(raw: str, *, fallback: str) -> str:
    line = (raw or "").strip().splitlines()[0].strip() if raw else ""
    line = line.strip("「」『』\"'“”‘’。．.！!？?")
    line = re.sub(r"\s+", " ", line)
    if not line or is_placeholder_title(line):
        return fallback
    if len(line) > 40:
        line = line[:39].rstrip() + "…"
    return line


def llm_session_title(
    config: Any,
    *,
    user_message: str,
    assistant_text: str = "",
    store: Any = None,
) -> str:
    """用当前会话模型生成短标题；失败回退 provisional。传入 ``store`` 时这次调用计入用量。"""
    fallback = provisional_title(user_message)
    excerpt = " ".join((assistant_text or "").strip().split())[:400]
    prompt = (
        f"用户：{user_message.strip()[:600]}\n"
        f"助手摘要：{excerpt or '（尚无正文）'}\n"
        "请给出侧栏标题："
    )
    try:
        response = chat(
            config,
            [ChatMessage(role="user", content=prompt)],
            system=_TITLE_SYSTEM,
            max_tokens=48,
            temperature=0.2,
        )
        if store is not None:
            record_llm_usage(store=store, provider=config.name, model=response.model or config.model,
                             input_tokens=response.input_tokens, output_tokens=response.output_tokens)
        return sanitize_llm_title(response.text or "", fallback=fallback)
    except Exception as exc:
        logger.warning("session title llm failed: %s", exc)
        return fallback


def apply_session_title(
    store: Any,
    session_id: str,
    title: str,
    *,
    source: str,
) -> dict[str, Any] | None:
    """写入标题并返回可供 SSE 透出的 payload；无变更则 None。"""
    cleaned = (title or "").strip()[:160]
    if not cleaned:
        return None
    session = store.get_session(session_id)
    if session is None:
        return None
    prev_meta = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    if is_title_locked(prev_meta):
        return None
    prev_title = (session.get("title") or "").strip()
    prev_source = title_source(prev_meta)
    if prev_title == cleaned and prev_source == source:
        return None
    metadata = dict(prev_meta or {})
    metadata["title_source"] = source
    metadata.pop("title_locked", None)
    store.update_session(session_id, title=cleaned, metadata=metadata)
    return {"title": cleaned, "source": source}


def maybe_apply_provisional_title(store: Any, session_id: str, user_message: str) -> dict[str, Any] | None:
    session = store.get_session(session_id)
    if session is None:
        return None
    meta = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    if not needs_provisional_title(session.get("title"), meta):
        return None
    return apply_session_title(
        store,
        session_id,
        provisional_title(user_message),
        source="provisional",
    )


def maybe_summarize_session_title(
    store: Any,
    session_id: str,
    config: Any,
    *,
    user_message: str,
    assistant_text: str = "",
) -> dict[str, Any] | None:
    session = store.get_session(session_id)
    if session is None:
        return None
    meta = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    if not needs_llm_title(session.get("title"), meta):
        return None
    title = llm_session_title(config, user_message=user_message, assistant_text=assistant_text, store=store)
    return apply_session_title(store, session_id, title, source="llm")


def lock_manual_title(store: Any, session_id: str, title: str) -> dict[str, Any]:
    """用户手动改名：锁定，后续自动总结不再覆盖。"""
    session = store.get_session(session_id)
    if session is None:
        raise AssistantError("AI 会话不存在")
    metadata = dict(session.get("metadata") or {})
    metadata["title_locked"] = True
    metadata["title_source"] = "user"
    return store.update_session(session_id, title=title.strip()[:160], metadata=metadata)
