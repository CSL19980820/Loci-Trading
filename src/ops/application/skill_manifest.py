"""Skill ``SKILL.md`` frontmatter 解析与元数据规范化。"""
from __future__ import annotations

import re
from typing import Any

import yaml

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
# Skill 只描述能力与方法。调度、启停和推送属于系统 Job，不允许写进清单。
FORBIDDEN_SCHEDULING_KEYS = frozenset(
    {
        "cron",
        "schedule",
        "default_cron",
        "run_at",
        "run_time",
        "frequency",
        "interval_minutes",
    }
)


class SkillError(RuntimeError):
    """技能包不合法。消息会原样回给用户，要说清楚哪一条不满足。"""


def _forbidden_scheduling_keys(value: Any, path: str = "") -> list[str]:
    """递归找调度字段，避免把 cron 藏进 watch/agents 等嵌套配置。"""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text.casefold() in FORBIDDEN_SCHEDULING_KEYS:
                found.append(child_path)
            else:
                found.extend(_forbidden_scheduling_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_scheduling_keys(child, f"{path}[{index}]"))
    return found


def parse_manifest(text: str) -> tuple[dict[str, Any], str]:
    """拆出 YAML frontmatter 与正文指令。"""
    match = FRONTMATTER_PATTERN.match(text.lstrip("\ufeff"))
    if not match:
        raise SkillError(
            "SKILL.md 缺少 YAML frontmatter。开头必须是 --- 包裹的元数据块，"
            "至少包含 name 与 description。"
        )
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"SKILL.md 的 frontmatter 不是合法 YAML：{exc}") from exc
    if not isinstance(meta, dict):
        raise SkillError("SKILL.md 的 frontmatter 必须是键值映射")
    forbidden = _forbidden_scheduling_keys(meta)
    if forbidden:
        raise SkillError(
            f"SKILL.md 不应声明调度字段：{', '.join(forbidden)}。"
            "运行时间、频率、启停与推送请在系统的技能配置中设置。"
        )
    return meta, match.group(2).strip()


def _meta_tool_specs(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 frontmatter 的 tools 声明。

    兼容两种写法：
    - 旧：``tools: [kline, limit_up]`` → 仅作为 allowed 名字，无本地 CLI
    - 新：``tools: [{name, description, kind, command, ...}]``
    """
    raw = meta.get("tools")
    if not isinstance(raw, list):
        return []
    specs: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            kind = str(item.get("kind") or "cli").strip().lower()
            if kind not in {"cli", "mcp", "builtin"}:
                kind = "cli"
            specs.append(
                {
                    "name": str(item["name"]).strip(),
                    "description": str(item.get("description") or item["name"]).strip(),
                    "kind": kind,
                    "command": item.get("command") or [],
                    "cwd": str(item.get("cwd") or "."),
                    "timeout_sec": int(item.get("timeout_sec") or 120),
                    "args_schema": item.get("args_schema")
                    if isinstance(item.get("args_schema"), dict)
                    else {"type": "object", "properties": {}},
                    "mcp_tool": str(item.get("mcp_tool") or item.get("name") or ""),
                }
            )
    return specs


def _meta_tools(meta: dict[str, Any]) -> list[str]:
    """允许暴露给模型的工具名列表（收窄面）。"""
    explicit = meta.get("allowed_tools")
    if explicit is not None:
        if isinstance(explicit, str):
            return [item.strip() for item in explicit.split(",") if item.strip()]
        if isinstance(explicit, list):
            return [str(item) for item in explicit if not isinstance(item, dict)]
        return []

    tools = meta.get("tools") or []
    if isinstance(tools, str):
        return [item.strip() for item in tools.split(",") if item.strip()]
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for item in tools:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif not isinstance(item, dict):
            names.append(str(item))
    return names


def _meta_mcp_servers(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("mcp_servers") or meta.get("mcpServers") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _meta_enabled(meta: dict[str, Any]) -> bool:
    if "enabled" not in meta:
        return True
    value = meta.get("enabled")
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _meta_isolation(meta: dict[str, Any]) -> str:
    raw = str(meta.get("isolation") or "normal").strip().lower()
    return "skill_only" if raw in {"skill_only", "isolated", "strict"} else "normal"


def _meta_policy(meta: dict[str, Any]) -> str:
    raw = str(meta.get("policy") or "research").strip().lower()
    return "trading_voice" if raw in {"trading_voice", "trading", "weipan"} else "research"


def _meta_agents(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 frontmatter ``agents:`` 子任务声明。"""
    raw = meta.get("agents")
    if not isinstance(raw, list):
        return []
    agents: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if not agent_id:
            continue
        kind = str(item.get("kind") or "cli").strip().lower()
        if kind not in {"cli", "llm"}:
            kind = "cli"
        role = str(item.get("role") or "ammo").strip().lower() or "ammo"
        agents.append(
            {
                "id": agent_id,
                "role": role,
                "kind": kind,
                "description": str(item.get("description") or "").strip(),
                "tool": str(item.get("tool") or "").strip(),
                "command": item.get("command") or [],
                "cwd": str(item.get("cwd") or "."),
                "timeout_sec": int(item.get("timeout_sec") or 300),
                "instructions": str(item.get("instructions") or "").strip(),
                "max_rounds": int(item.get("max_rounds") or 3),
                "max_tokens": int(item.get("max_tokens") or 2048),
                "mcp_servers": list(item["mcp_servers"])
                if isinstance(item.get("mcp_servers"), list)
                else None,
                "tools": list(item["tools"]) if isinstance(item.get("tools"), list) else None,
            }
        )
    return agents


def _meta_extras(meta: dict[str, Any]) -> dict[str, Any]:
    skip = {
        "name",
        "slug",
        "version",
        "description",
        "tools",
        "allowed_tools",
        "schedule",
        "cron",
        "enabled",
        "mcp_servers",
        "mcpServers",
        "isolation",
        "policy",
        "hitl",
        "agents",
    }
    return {key: value for key, value in meta.items() if key not in skip}


def _normalise_slug(raw: str) -> str:
    slug = str(raw).strip().lower().replace(" ", "-")
    if not SLUG_PATTERN.match(slug):
        raise SkillError(
            f"非法的技能标识：{raw!r}。只允许小写字母、数字、点、下划线与连字符，"
            "且不超过 64 字符"
        )
    return slug


__all__ = [
    "FORBIDDEN_SCHEDULING_KEYS",
    "FRONTMATTER_PATTERN",
    "SLUG_PATTERN",
    "SkillError",
    "parse_manifest",
    "_meta_agents",
    "_meta_enabled",
    "_meta_extras",
    "_meta_isolation",
    "_meta_mcp_servers",
    "_meta_policy",
    "_meta_tool_specs",
    "_meta_tools",
    "_normalise_slug",
]
