"""从 intel_snapshots 投影盘面/助手用的短线情报摘要（只读，不调 MCP）。

编排入口兼对外门面：决定「取哪些工具的快照、拼成哪几段、缺数据时长什么样」。
原文件 602 行超了仓库 600 行硬规则，按职责拆出两块，本模块不再碰单个字段名：

- `brief_payload` —— 载荷解析原语（数字清洗、口径换算、嵌套查找）
- `brief_sections` —— 逐段投影，每段绑定悟道某一张表的字段名
"""

from __future__ import annotations

from typing import Any

from src.intel.application.brief_payload import _metric, _percent
from src.intel.application.brief_sections import (
    _auction_themes,
    _board_break,
    _breadth,
    _catalysts,
    _ladder_summary,
    _limit_down_summary,
    _margin,
    _theme_rows,
    _unlocks,
)
from src.intel.infrastructure.intel_cache import list_latest_snapshots
from src.intel.infrastructure.quota import trade_date_today
from src.market import MarketStore

#: 情绪/题材/梯队三段的老工具。
_CORE_TOOLS = (
    "short_term_emotion",
    "limit_up_ladder",
    "theme_intraday_capital",
    "market_overview",
    "limit_stats",
)

#: 复盘与排雷段（2026-08-31 进配方）。这几张表本地库算不出来：
#: 「昨涨停今天活着几只」「跌停原因」「竞价资金打哪条主线」「未来两周有什么催化」
#: 「杠杆资金加减」「谁要解禁」。缺任一条只是该段为空，不影响其它段与主体功能。
_REVIEW_TOOLS = (
    "board_break_analysis",
    "limit_down",
    "auction_theme_strength",
    "market_catalyst_calendar",
    "margin_trading",
    "unlock_events",
)

BRIEF_TOOLS = _CORE_TOOLS + _REVIEW_TOOLS

#: 晋级率口径：悟道 promotionRates.firstToSecond（首板晋级二板），单位已是 %。
PROMOTION_RATE_BASIS = "1进2"


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
        "board_break": None,
        "limit_down": None,
        "auction_themes": [],
        "catalysts": [],
        "margin": None,
        "unlocks": [],
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

    def payload_of(tool: str) -> dict[str, Any] | None:
        raw = (latest.get(tool) or {}).get("payload")
        return raw if isinstance(raw, dict) else None

    emotion_payload = payload_of("short_term_emotion")
    overview_payload = payload_of("market_overview")
    stats_payload = payload_of("limit_stats")

    breadth = _breadth(emotion_payload)
    if breadth["advancers"] is None and breadth["decliners"] is None:
        breadth = _breadth(overview_payload)
    limit_down = _limit_down_summary(payload_of("limit_down"))
    # 跌停家数三级兜底：情绪表 → 涨跌停统计 → 跌停池。跌停池才是权威口径，但它只在
    # 收盘档采（开盘 9:26 没有跌停可言），所以不能当第一顺位。
    pool_down_count = limit_down.get("count") if limit_down else None
    emotion = {
        "limit_up_count": _metric(emotion_payload, "limit_up_count")
        or _metric(stats_payload, "limit_up_count"),
        "limit_down_count": _metric(emotion_payload, "limit_down_count")
        or _metric(stats_payload, "limit_down_count")
        or pool_down_count,
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
    ladder = _ladder_summary(payload_of("limit_up_ladder"))
    themes = _theme_rows(payload_of("theme_intraday_capital"))
    board_break = _board_break(payload_of("board_break_analysis"))
    auction_themes = _auction_themes(payload_of("auction_theme_strength"))
    catalysts = _catalysts(payload_of("market_catalyst_calendar"), day=day)
    margin = _margin(payload_of("margin_trading"))
    unlocks = _unlocks(payload_of("unlock_events"))
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
        "board_break": board_break,
        "limit_down": limit_down,
        "auction_themes": auction_themes,
        "catalysts": catalysts,
        "margin": margin,
        "unlocks": unlocks,
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
