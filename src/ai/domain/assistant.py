"""全局助手的纯领域约束。"""
from __future__ import annotations

from typing import Any, Literal


SessionStatus = Literal["idle", "running", "waiting_user", "error", "archived"]
RunStatus = Literal["running", "waiting_user", "completed", "failed", "cancelled"]


class AssistantError(ValueError):
    """助手输入、状态或依赖不满足时的可展示错误。"""


class AssistantUnavailableError(AssistantError):
    """助手后台依赖暂不可用，调用方应提示稍后重试。"""


def assistant_system_prompt() -> str:
    """不可被客户端提示词覆盖的助手边界。"""
    return (
        "你是 Loci 工作台助手。行情、候选和策略数字只能引用工具结果；"
        "没有工具证据时明确说未取到数据。只可调用已注册工具，禁止 raw SQL、"
        "密钥读取、券商下单或自动交易。已注册的候选池、预案、复盘和运维写操作"
        "在 owner_full 模式下可由工具直接执行，不要求逐笔确认；成功前不得宣称已经写入。"
        "本工作台不记录真实持仓、成交与资金：用户问持仓或盈亏时，说明账本只留候选池、"
        "预案与复盘，可改为回顾候选表现或预案兑现。"
        "用户要求潜龙精选时，先读取整池与 qianlong_pool_evidence，再对全部 6-10 只提交"
        "精选/观察/落选裁决，精选最多 2 只。子 agent 的结果仅是证据，不得作为终裁或"
        "交易建议。回答使用简洁中文。"
    )


def validate_qianlong_decisions(rows: Any) -> list[dict[str, Any]]:
    """潜龙整池提交的硬约束，避免模型绕过候选裁决纪律。"""
    if not isinstance(rows, list) or not 6 <= len(rows) <= 10:
        raise AssistantError("潜龙整池必须提交 6-10 只候选")
    allowed = {"精选", "观察", "落选"}
    codes: set[str] = set()
    selected = 0
    clean: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise AssistantError("潜龙候选必须是对象数组")
        code = str(item.get("code") or "").strip()
        decision = str(item.get("decision") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if len(code) != 6 or not code.isdigit() or code in codes:
            raise AssistantError("潜龙候选代码必须为唯一的 6 位数字")
        if decision not in allowed:
            raise AssistantError("潜龙裁决只能是：精选、观察、落选")
        if not reason:
            raise AssistantError("潜龙每只候选都必须给出理由")
        codes.add(code)
        if decision == "精选":
            selected += 1
            if not str(item.get("timing") or "").strip():
                raise AssistantError("潜龙精选必须给出 entry timing")
            if not str(item.get("invalidation") or "").strip():
                raise AssistantError("潜龙精选必须给出失效条件")
        clean.append(dict(item, code=code, decision=decision, reason=reason))
    if selected > 2:
        raise AssistantError("潜龙精选最多 2 只")
    return clean
