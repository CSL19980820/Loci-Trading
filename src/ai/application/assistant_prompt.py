"""组装助手 system prompt：安全底座 + 用户指令/规则 + 记忆快照。"""
from __future__ import annotations

from typing import Any

from src.ai.domain.assistant import assistant_system_prompt


def build_assistant_system_prompt(
    *,
    profile: dict[str, Any] | None = None,
    memories: list[dict[str, Any]] | None = None,
) -> str:
    """每次 run 调用一次，生成冻结快照；中途记忆写入不刷新本字符串。"""
    parts = [assistant_system_prompt().strip()]
    profile = profile or {}
    about = str(profile.get("about_user") or "").strip()
    style = str(profile.get("response_style") or "").strip()
    rules = profile.get("rules") if isinstance(profile.get("rules"), list) else []
    clean_rules = [str(item).strip() for item in rules if str(item).strip()]

    if about or style:
        parts.append("\n\n# 用户自定义指令")
        if about:
            parts.append(f"\n## 关于用户\n{about}")
        if style:
            parts.append(f"\n## 回答偏好\n{style}")

    if clean_rules:
        parts.append("\n\n# 用户规则")
        for rule in clean_rules:
            parts.append(f"\n- {rule}")

    if profile.get("memory_enabled", True) and memories:
        user_rows = [row for row in memories if row.get("target") == "user"]
        note_rows = [row for row in memories if row.get("target") == "memory"]
        if user_rows or note_rows:
            parts.append("\n\n# 跨会话记忆（冻结快照，本轮不变）")
            if user_rows:
                parts.append("\n## 用户画像\n")
                parts.append("\n\n".join(str(row.get("content") or "").strip() for row in user_rows if str(row.get("content") or "").strip()))
            if note_rows:
                parts.append("\n## 工作记忆\n")
                parts.append("\n\n".join(str(row.get("content") or "").strip() for row in note_rows if str(row.get("content") or "").strip()))

    return "".join(parts).strip()
