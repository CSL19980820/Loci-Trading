"""助手记忆工具：Hermes 风格 add/replace/remove。"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai.application.system_toolbus import SystemToolBus, ToolSpec


def build_memory_tool_specs(owner: SystemToolBus) -> dict[str, ToolSpec]:
    from src.ai.application.system_toolbus import ToolSpec, _object

    return {
        "memory_update": ToolSpec(
            "memory_update",
            "更新跨会话记忆。target=user 存用户画像/偏好；target=memory 存环境与约定。"
            "用户说「记住」或纠正你时主动写入；仓满须先 remove/replace。",
            _object(
                {
                    "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                    "target": {"type": "string", "enum": ["user", "memory"]},
                    "content": {"type": "string", "maxLength": 4000},
                    "old_text": {"type": "string", "maxLength": 4000},
                },
                ["action", "target"],
            ),
            True,
            lambda args: _memory_update(owner, args),
        ),
    }


def _memory_update(owner: SystemToolBus, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok
    from src.ai.infrastructure.assistant_store import AssistantStore

    if not owner.ops_db:
        raise AssistantError("未配置 ops.db，无法写入记忆")
    action = str(args.get("action") or "").strip()
    target = str(args.get("target") or "").strip()
    content = str(args.get("content") or "").strip()
    old_text = str(args.get("old_text") or "").strip()
    canonical = {"action": action, "target": target, "content": content, "old_text": old_text}
    owner._grant("memory.update", target, canonical)  # noqa: SLF001 — 与其它写工具一致
    with AssistantStore(owner.ops_db) as store:
        profile = store.get_profile()
        if not profile.get("memory_enabled"):
            raise AssistantError("记忆已关闭；请在助手设置中启用")
        if action == "add":
            if not content:
                raise AssistantError("add 需要 content")
            row = store.add_memory(target=target, content=content, source="tool")
        elif action == "replace":
            if not old_text or not content:
                raise AssistantError("replace 需要 old_text 与 content")
            row = store.replace_memory_by_text(
                target=target, old_text=old_text, content=content, source="tool"
            )
        elif action == "remove":
            if not old_text:
                raise AssistantError("remove 需要 old_text")
            store.remove_memory_by_text(target=target, old_text=old_text)
            row = {"removed": True, "old_text": old_text, "target": target}
        else:
            raise AssistantError("action 必须是 add、replace 或 remove")
        usage = {
            "user": store.memory_char_usage("user"),
            "memory": store.memory_char_usage("memory"),
        }
    return _ok({"memory": row, "usage": usage})
