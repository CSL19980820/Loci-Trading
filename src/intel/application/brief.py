"""从 intel_snapshots 投影盘面/助手用的短线情报摘要（只读，不调 MCP）。"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from src.intel.infrastructure.intel_cache import list_latest_snapshots
from src.intel.infrastructure.quota import trade_date_today
from src.market import MarketStore

BRIEF_TOOLS = (
    "short_term_emotion",
    "limit_up_ladder",
    "theme_intraday_capital",
    "market_overview",
    "limit_stats",
)

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

#: 晋级率口径：悟道 promotionRates.firstToSecond（首板晋级二板），单位已是 %。
PROMOTION_RATE_BASIS = "1进2"


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


def _theme_rows(payload: dict[str, Any] | None, *, limit: int = 5) -> list[dict[str, Any]]:
    """题材行：除内部 strength 外带上涨跌幅与主力净额，供界面讲人话。

    ``strength`` 是开盘啦内部量纲（动辄上万），单独展示没有意义；``pct_chg``
    与 ``main_net_amount_text`` 才是能直接读的口径。
    """
    rows: list[dict[str, Any]] = []
    for row in _rows(payload):
        code = str(row.get("themeCode") or row.get("theme_code") or row.get("code") or "").strip()
        name = str(
            row.get("themeName")
            or row.get("theme_name")
            or row.get("name")
            or code
            or ""
        ).strip()
        if not (code or name):
            continue
        rows.append(
            {
                "code": code,
                "name": name or code,
                "strength": _pick_number(
                    row, "strength", "themeStrength", "theme_strength", "score"
                ),
                "pct_chg": _pick_number(row, "pctChg", "pct_chg", "涨跌幅"),
                "main_net_amount": _pick_number(
                    row, "mainNetAmount", "main_net_amount", "主力净额"
                ),
                "main_net_amount_text": str(
                    row.get("mainNetAmountText") or row.get("main_net_amount_text") or ""
                ).strip(),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _breadth(payload: dict[str, Any] | None) -> dict[str, float | None]:
    """涨跌家数：只认显式的 breadth 段，避免把别处的 up/down 当宽度。"""
    empty: dict[str, float | None] = {"advancers": None, "decliners": None}
    if not payload:
        return empty
    for mapping in _walk(_structured(payload)):
        raw = mapping.get("breadth")
        if not isinstance(raw, dict):
            continue
        advancers = _pick_number(raw, "up", "advancers", "上涨家数")
        decliners = _pick_number(raw, "down", "decliners", "下跌家数")
        if advancers is not None or decliners is not None:
            return {"advancers": advancers, "decliners": decliners}
    return empty


def _ladder_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    rows = _rows(payload)
    height = _metric(payload, "height")
    if height is None:
        for row in rows:
            level = _number(row.get("level") or row.get("board") or row.get("boards") or row.get("连板数"))
            if level is None:
                continue
            height = level if height is None else max(height, level)
    return {"count": len(rows) if rows else None, "height": height}


def empty_intel_brief(
    *,
    trade_date: str | None = None,
    note: str = "可选情报不可用；不影响盘面/账本/选股主体功能。",
) -> dict[str, Any]:
    """无缓存 / 读库失败时的稳定空结构（available=false）。"""
    day = str(trade_date or "").strip() or trade_date_today()
    return {
        "trade_date": day,
        "available": False,
        "fetched_at": None,
        "emotion": None,
        "themes": [],
        "ladder": None,
        "tools": {
            name: {"present": False, "fetched_at": None, "server": ""}
            for name in BRIEF_TOOLS
        },
        "source": "intel_snapshots",
        "note": note,
        "optional": True,
    }


def build_intel_brief(
    store: MarketStore,
    *,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """投影盘面短线摘要。无缓存时 available=false，不发明数字；异常也返回空摘要。"""
    day = str(trade_date or "").strip() or trade_date_today()
    try:
        latest = list_latest_snapshots(store, trade_date=day, tools=list(BRIEF_TOOLS))
    except Exception:
        return empty_intel_brief(
            trade_date=day,
            note="情报缓存读取失败（已忽略）；不影响盘面/账本/选股主体功能。",
        )
    emotion_payload = (latest.get("short_term_emotion") or {}).get("payload")
    ladder_payload = (latest.get("limit_up_ladder") or {}).get("payload")
    themes_payload = (latest.get("theme_intraday_capital") or {}).get("payload")
    overview_payload = (latest.get("market_overview") or {}).get("payload")
    stats_payload = (latest.get("limit_stats") or {}).get("payload")

    breadth = _breadth(emotion_payload if isinstance(emotion_payload, dict) else None)
    if breadth["advancers"] is None and breadth["decliners"] is None:
        breadth = _breadth(overview_payload if isinstance(overview_payload, dict) else None)
    emotion = {
        "limit_up_count": _metric(emotion_payload, "limit_up_count")
        or _metric(stats_payload, "limit_up_count"),
        "limit_down_count": _metric(emotion_payload, "limit_down_count")
        or _metric(stats_payload, "limit_down_count"),
        # 统一成 0–100 百分数，避免前端再猜比例/百分
        "promotion_rate": _percent(_metric(emotion_payload, "promotion_rate")),
        "broken_rate": _percent(_metric(emotion_payload, "broken_rate")),
        "temperature": _metric(emotion_payload, "temperature")
        or _metric(overview_payload, "temperature"),
        "advancers": breadth["advancers"],
        "decliners": breadth["decliners"],
    }
    has_emotion = any(
        value is not None
        for key, value in emotion.items()
        if key != "promotion_rate_basis"
    )
    if has_emotion:
        emotion["promotion_rate_basis"] = PROMOTION_RATE_BASIS
    ladder = _ladder_summary(ladder_payload if isinstance(ladder_payload, dict) else None)
    themes = _theme_rows(themes_payload if isinstance(themes_payload, dict) else None)
    fetched_ats = [
        str(item.get("fetched_at") or "")
        for item in latest.values()
        if str(item.get("fetched_at") or "")
    ]
    fetched_ats.sort(reverse=True)
    available = bool(latest)
    return {
        "trade_date": day,
        "available": available,
        "fetched_at": fetched_ats[0] if fetched_ats else None,
        "emotion": emotion if has_emotion else None,
        "themes": themes,
        "ladder": ladder if ladder.get("count") is not None or ladder.get("height") is not None else None,
        "tools": {
            name: {
                "present": name in latest,
                "fetched_at": (latest.get(name) or {}).get("fetched_at") or None,
                "server": (latest.get(name) or {}).get("server") or "",
            }
            for name in BRIEF_TOOLS
        },
        "source": "intel_snapshots",
        "optional": True,
        "note": (
            "可选：未配置悟道或未跑情报任务时为空；不影响盘面/账本/选股。"
            if not available
            else "只读缓存，不实时调用 MCP。"
        ),
    }


__all__ = [
    "BRIEF_TOOLS",
    "PROMOTION_RATE_BASIS",
    "build_intel_brief",
    "empty_intel_brief",
]
