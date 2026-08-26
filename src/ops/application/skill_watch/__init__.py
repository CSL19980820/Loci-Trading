"""战法 Skill 实时监测（MCP + 本地量化，不走 LLM）。"""

from src.ops.application.skill_watch.runner import (
    run_skill_watch,
    skill_watch_mcp_call,
    wudao_availability_for_watch,
)

__all__ = ["run_skill_watch", "skill_watch_mcp_call", "wudao_availability_for_watch"]
