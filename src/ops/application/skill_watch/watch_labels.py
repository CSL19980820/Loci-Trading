"""战法监测对外展示名：推送标题 / 任务名 / 跳过原因，统一中文。"""
from __future__ import annotations

import re
from typing import Any

from src.ops.application.skill_watch.engine_registry import (
    engines_using_market_gate,
    watch_label_map,
)

WATCH_SLUG_LABELS: dict[str, str] = watch_label_map()

#: 龙王战法大成体：能力声明 uses_market_gate 的 slug 集合（兼容旧导入）
DRAGON_SUITE_SLUGS = frozenset(k for k in engines_using_market_gate() if "-" in k)

SKIP_REASON_LABELS: dict[str, str] = {
    "skill_disabled": "技能已停用",
    "no_signal_engine": "未配置信号引擎",
    "mcp_unavailable": "悟道暂不可用，本次未扫描",
    "mcp_degraded": "悟道数据不可用，本次未出结论",
    "market_gate_degraded": "关键指标不全，保守空仓",
    "degraded": "数据降级，本次未出结论",
    "outside_window": "不在监测时段",
}


def suite_short_name(*, slug: str = "") -> str:
    """套件级短名（企微预案标题）；非套件返回空串。"""
    key = str(slug or "").strip()
    if key in DRAGON_SUITE_SLUGS:
        return "龙王"
    return ""


def watch_short_name(
    *,
    slug: str = "",
    skill_name: str = "",
    job_name: str = "",
) -> str:
    key = str(slug or "").strip()
    if key in WATCH_SLUG_LABELS:
        return WATCH_SLUG_LABELS[key]
    for source in (skill_name, job_name):
        text = str(source or "").strip()
        if text.startswith("监测·"):
            text = text[len("监测·") :].strip()
        if text.startswith("skill:"):
            text = text[len("skill:") :].strip()
        if text in WATCH_SLUG_LABELS:
            return WATCH_SLUG_LABELS[text]
        if text and not re.search(r"[A-Za-z]", text):
            if "·" in text:
                text = text.split("·", 1)[0].strip() or text
            if text.endswith("实战战法"):
                text = text[: -len("实战战法")].strip() or text
            return text or "战法"
    return "战法"


def watch_job_title(*, slug: str = "", skill_name: str = "", job_name: str = "") -> str:
    return f"监测·{watch_short_name(slug=slug, skill_name=skill_name, job_name=job_name)}"


def skip_reason_zh(reason: str) -> str:
    key = str(reason or "").strip()
    if not key:
        return "已跳过"
    if key in SKIP_REASON_LABELS:
        return SKIP_REASON_LABELS[key]
    if re.search(r"[A-Za-z_]", key):
        return "本次未执行"
    return key


def format_watch_status_push(
    *,
    slug: str = "",
    skill_name: str = "",
    job_name: str = "",
    status: str,
    summary: str = "",
    reason: str = "",
    error: str = "",
    result: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """返回 ``(标题, 正文)``；正文不再复读标题行。"""
    title = watch_job_title(slug=slug, skill_name=skill_name, job_name=job_name)
    body = str(summary or "").strip()
    if body:
        return title, body

    payload = result if isinstance(result, dict) else {}
    why = skip_reason_zh(str(reason or payload.get("reason") or ""))
    unavailable = str(payload.get("unavailable_reason") or "").strip()
    if status == "skipped":
        lines = [why]
        if unavailable and "悟道" in unavailable:
            lines.append(unavailable[:120])
        return title, "\n".join(lines)
    if status == "failed":
        detail = str(error or "").strip() or "执行失败，请到运维查看详情"
        return title, f"失败：{detail[:160]}"
    return title, "无新信号"


__all__ = [
    "DRAGON_SUITE_SLUGS",
    "SKIP_REASON_LABELS",
    "WATCH_SLUG_LABELS",
    "format_watch_status_push",
    "skip_reason_zh",
    "suite_short_name",
    "watch_job_title",
    "watch_short_name",
]
