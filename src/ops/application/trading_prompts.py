"""按交易阶段选择一份用户提示词，兼容仅配置盘中提示词的旧账户。"""
from collections.abc import Mapping


def phase_prompt(config: Mapping, phase: str, default: str = "") -> str:
    if phase == "weekly":
        from src.ops.application.guardian_weekly_prompt import DEFAULT_WEEKLY_PROMPT
        return str(config.get("weekly_prompt") or "").strip() or default or DEFAULT_WEEKLY_PROMPT
    field = {"premarket": "premarket_prompt", "review": "review_prompt",
             "daily": "review_prompt"}.get(phase, "prompt")
    return str(config.get(field) or "").strip() or str(config.get("prompt") or "").strip() or default


def trading_prompt(config: Mapping, phase: str, default: str = "") -> str:
    """共用身份与偏好只出现一次；其他阶段提示词不进入本轮。"""
    common = str(config.get("common_prompt") or "").strip()
    selected = phase_prompt(config, phase, default)
    return common + "\n\n" + selected if common else selected
