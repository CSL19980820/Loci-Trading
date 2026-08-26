"""本轮斜杠激活技能：把 SKILL.md 指令注入助手 system 快照。"""
from __future__ import annotations

from src.ai.domain.assistant import AssistantError


def skill_prompt_block(slug: str) -> str:
    """加载 ``data/skills/<slug>``；失败抛 AssistantError。"""
    cleaned = str(slug or "").strip()
    if not cleaned:
        return ""
    try:
        from src.ops.application.skills import load_skill_from_disk
    except ImportError as exc:
        raise AssistantError("技能模块不可用") from exc
    package = load_skill_from_disk(cleaned)
    if package is None:
        raise AssistantError(f"未找到技能：{cleaned}")
    if not package.enabled:
        raise AssistantError(f"技能已停用：{cleaned}")
    body = (package.instructions or "").strip()
    if not body:
        raise AssistantError(f"技能正文为空：{cleaned}")
    return (
        f"# 本轮激活技能 /{package.slug}\n"
        f"名称：{package.name}\n"
        f"说明：{package.description}\n\n"
        f"{body}"
    )
