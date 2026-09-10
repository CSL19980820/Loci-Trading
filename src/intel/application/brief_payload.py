"""悟道 / MCP 载荷的解析原语：数字清洗、口径换算、嵌套查找。

为什么单独成文件：这批函数**只认 dict 和数字，不认业务**，同一份 `_walk` /
`_find_mapping` 被十段投影共用。它们与「断板怎么算」同住一个文件时，改某一段的
字段名要在共享原语里翻页，而动一下原语就是十段一起变——两种改动的爆炸半径差一个
数量级，值得分开放。

为什么用「找含某个键的那层 dict」而不写死 ``data.summary`` 这类路径：同一份结果
本仓见过三种包法（``structuredContent`` / ``data`` / ``result``），写死路径的那一版在
上游加一层包装时会静默变成「没数据」，而这与「今天真没数据」在界面上长得一样。
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

#: 悟道 short_term_emotion.summary 用 sealed*/broken* 命名，排在前面；
#: 后面的下划线/中文别名留给其它情报源兜底。
_ALIASES: dict[str, tuple[str, ...]] = {
    "promotion_rate": ("firstToSecond", "promotion_rate", "promotionRate", "晋级率"),
    "broken_rate": ("brokenBoardRate", "broken_rate", "brokenRate", "炸板率"),
    "temperature": ("temperature", "market_temperature", "市场温度", "情绪温度"),
    "limit_up_count": (
        "sealedLimitUp",
        "limit_up_count",
        "limitUpCount",
        "涨停家数",
        "涨停",
    ),
    "limit_down_count": (
        "sealedLimitDown",
        "limit_down_count",
        "limitDownCount",
        "跌停家数",
        "跌停",
    ),
    "height": ("height", "max_height", "maxHeight", "highest_board", "最高连板", "连板高度"),
    "theme_strength": ("strength", "theme_strength", "themeStrength", "score", "板块强度"),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _percent(value: float | None) -> float | None:
    """统一成百分数（0–100）。

    悟道给的是 31.91 这类百分数，历史别名可能给 0.3191 比例。比例不可能 >1，
    所以只把 ``<=1`` 的值换算，避免 1.07% 被误放大成 107%。口径收在这一处，
    前端不再猜。
    """
    if value is None:
        return None
    return value * 100.0 if 0.0 <= value <= 1.0 else value


def _pick_number(row: dict[str, Any], *keys: str) -> float | None:
    """按序取第一个能解析成数字的字段（0 也算命中，不被 ``or`` 吞掉）。"""
    for key in keys:
        num = _number(row.get(key))
        if num is not None:
            return num
    return None


def _norm(key: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(key).lower())


def _structured(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("structured", "structuredContent", "data", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    text = str(payload.get("text") or "").strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return payload


def _walk(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    if isinstance(value, dict):
        out = [value]
        for child in value.values():
            out.extend(_walk(child, depth=depth + 1))
        return out
    if isinstance(value, list):
        out: list[dict[str, Any]] = []
        for child in value:
            out.extend(_walk(child, depth=depth + 1))
        return out
    return []


def _metric(payload: dict[str, Any] | None, name: str) -> float | None:
    if not payload:
        return None
    wanted = {_norm(item) for item in _ALIASES.get(name, (name,))}
    for mapping in _walk(_structured(payload)):
        for key, value in mapping.items():
            if _norm(key) in wanted:
                num = _number(value)
                if num is not None:
                    return num
    return None


def _rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    structured = _structured(payload)
    for key in ("rows", "items"):
        value = structured.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _find_mapping(payload: dict[str, Any] | None, *keys: str) -> dict[str, Any] | None:
    """在载荷里找**第一个**含有任一给定键的嵌套 dict。"""
    if not payload:
        return None
    for mapping in _walk(_structured(payload)):
        if any(key in mapping for key in keys):
            return mapping
    return None


def _list_under(payload: dict[str, Any] | None, *keys: str) -> list[dict[str, Any]]:
    """取嵌套里第一个非空的 ``keys`` 列表（``_rows`` 只认 rows/items，这里认别的段名）。"""
    if not payload:
        return []
    for mapping in _walk(_structured(payload)):
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, list) and value:
                return [row for row in value if isinstance(row, dict)]
    return []
