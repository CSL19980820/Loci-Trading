"""工具回执预览：本机把 structured 收成可读摘要，禁止把 JSON 原文甩给 UI。"""
from __future__ import annotations

import json
from typing import Any


def tool_event_preview(name: str, result: dict[str, Any], *, limit: int = 220) -> str:
    """给 tool_end.preview 用的短中文摘要。"""
    if result.get("is_error"):
        text = str(result.get("text") or "工具失败").strip()
        return _clip(text, limit)
    structured = result.get("structured")
    summary = _from_structured(name, structured)
    if summary:
        return _clip(summary, limit)
    text = str(result.get("text") or "").strip()
    if not text:
        return "完成"
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            return _clip(text, limit)
        summary = _from_structured(name, parsed)
        if summary:
            return _clip(summary, limit)
        return _clip(_generic_payload(parsed), limit)
    return _clip(text, limit)


def _from_structured(name: str, data: Any) -> str:
    if data is None:
        return ""
    if name == "market_kline" and isinstance(data, list):
        return f"日 K {len(data)} 根"
    if name == "market_search" and isinstance(data, list):
        return f"命中 {len(data)} 只"
    if name in {"strategy_screen", "strategy_catalog"} and isinstance(data, dict):
        rows = data.get("candidates") or data.get("strategies") or data.get("items")
        if isinstance(rows, list):
            return f"结果 {len(rows)} 条"
    if name.startswith("qianlong_") and isinstance(data, dict):
        cands = data.get("candidates") or data.get("decisions")
        if isinstance(cands, list):
            return f"候选 {len(cands)} 只"
    if isinstance(data, list):
        return f"{len(data)} 条"
    if isinstance(data, dict):
        return _generic_payload(data)
    return ""


def _generic_payload(data: Any) -> str:
    if isinstance(data, list):
        return f"{len(data)} 条"
    if not isinstance(data, dict):
        return str(data)
    for key in ("count", "total", "size"):
        value = data.get(key)
        if isinstance(value, (int, float)):
            return f"{int(value)} 条"
    for key in ("items", "rows", "results", "candidates"):
        value = data.get(key)
        if isinstance(value, list):
            return f"{key} {len(value)} 条"
    keys = list(data.keys())[:4]
    return "含 " + "、".join(str(key) for key in keys) if keys else "完成"


def _clip(text: str, limit: int) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"
