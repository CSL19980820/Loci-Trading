"""从 intel_snapshots 投影盘面/助手用的短线情报摘要（只读，不调 MCP）。"""
from __future__ import annotations

import json
import math
import re
from typing import Any

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


# ---- 复盘与排雷段（悟道专供，本地库算不出来）------------------------------
#
# 一条共同纪律：**只投影，不发明**。字段缺就给 None / 空列表，不拿别处的数字顶替，
# 也不在这里做二次口径换算（例外只有 `_percent`：把 0–1 比例统一成 0–100 百分数）。
#
# 为什么用「找含某个键的那层 dict」而不是写死 `data.summary` 这类路径：同一份结果
# 本仓见过三种包法（`structuredContent` / `data` / `result`），写死路径的那一版在
# 上游加一层包装时会静默变成「没数据」，而这与「今天真没数据」在界面上长得一样。

#: 悟道 sentimentSignal 的三值枚举 → 人话。翻译只留一份，前端不再自己猜。
_SENTIMENT_ZH = {"cooling": "退潮", "neutral": "中性", "warming": "修复"}


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


def _board_break(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """断板分析：昨涨停 × 今日。悟道 ``breakRate`` 是 0–1 比例，统一成百分数。"""
    summary = _find_mapping(payload, "breakRate", "sentimentSignal")
    if not summary:
        return None
    signal = str(summary.get("sentimentSignal") or "").strip()
    high_board: list[dict[str, Any]] = []
    raw_high = summary.get("highBoardBroken")
    for row in raw_high if isinstance(raw_high, list) else []:
        if not isinstance(row, dict):
            continue
        high_board.append(
            {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "prev_streak": _pick_number(row, "prevStreak", "prev_streak"),
                "pct_chg": _pick_number(row, "pctChg", "pct_chg"),
            }
        )
        if len(high_board) >= 5:
            break
    result: dict[str, Any] = {
        "prev_limit_ups": _pick_number(summary, "totalPrevLimitUps"),
        "sealed_again": _pick_number(summary, "sealedAgainCount"),
        "broken": _pick_number(summary, "brokenCount"),
        "break_rate": _percent(_pick_number(summary, "breakRate")),
        "avg_broken_pct_chg": _pick_number(summary, "avgBrokenPctChg"),
        "sentiment_signal": signal or None,
        "sentiment_zh": _SENTIMENT_ZH.get(signal),
        "high_board_broken": high_board,
    }
    if all(value in (None, [], "") for value in result.values()):
        return None
    return result


def _limit_down_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """跌停池：家数 + 今日封板率/炸板数（悟道 ``stats.limitDownCount.today``）。"""
    if not payload:
        return None
    stats = _find_mapping(payload, "limitDownCount")
    bucket: dict[str, Any] | None = None
    if stats:
        raw = stats.get("limitDownCount")
        if isinstance(raw, dict) and isinstance(raw.get("today"), dict):
            bucket = raw["today"]
    root = _find_mapping(payload, "total")
    count = _pick_number(root, "total") if root else None
    if count is None and bucket:
        count = _pick_number(bucket, "num")
    rows = [
        {
            "code": str(row.get("code") or "").strip(),
            "name": str(row.get("name") or "").strip(),
            "reason": str(row.get("reason") or row.get("reasonInfo") or "").strip(),
        }
        for row in _list_under(payload, "rows", "items")[:5]
    ]
    if count is None and not rows:
        return None
    return {
        "count": count,
        "sealed_rate": _percent(_pick_number(bucket, "rate")) if bucket else None,
        "reopened": _pick_number(bucket, "open_num") if bucket else None,
        "rows": rows,
    }


def _auction_themes(payload: dict[str, Any] | None, *, limit: int = 5) -> list[dict[str, Any]]:
    """竞价题材强度：今天竞价资金打哪条主线。``consistency`` 是 0–1 比例。"""
    out: list[dict[str, Any]] = []
    for row in _list_under(payload, "themes"):
        name = str(row.get("name") or row.get("themeName") or "").strip()
        if not name:
            continue
        leaders: list[dict[str, Any]] = []
        raw_leaders = row.get("leaders")
        for leader in raw_leaders if isinstance(raw_leaders, list) else []:
            if not isinstance(leader, dict):
                continue
            leaders.append(
                {
                    "code": str(leader.get("code") or "").strip(),
                    "name": str(leader.get("name") or "").strip(),
                    "change_pct": _pick_number(leader, "changeRate", "change_pct"),
                }
            )
            if len(leaders) >= 3:
                break
        out.append(
            {
                "name": name,
                "member_count": _pick_number(row, "memberCount"),
                "hit_count": _pick_number(row, "hitCount"),
                "bid_amount_text": str(row.get("totalBidAmountText") or "").strip(),
                "avg_change_pct": _pick_number(row, "avgChangeRate"),
                "consistency": _percent(_pick_number(row, "consistency")),
                "limit_up_open": _pick_number(row, "limitUpOpenCount"),
                "leaders": leaders,
            }
        )
        if len(out) >= limit:
            break
    return out


def _catalysts(
    payload: dict[str, Any] | None, *, day: str, limit: int = 6
) -> list[dict[str, Any]]:
    """短线催化日历：只留**今天及以后**、国家为中国（或未标国家）的事件。

    过滤放在消费侧而不是请求参数里：服务端 ``country`` 过滤值一旦对不上就是静默
    0 行，而行里本来就带 ``country``，本地筛错了看得见。
    """
    out: list[dict[str, Any]] = []
    today = str(day or "")[:10]
    for row in _list_under(payload, "rows", "items"):
        date = str(row.get("date") or "").strip()[:10]
        if date and today and date < today:
            continue
        country = str(row.get("country") or "").strip()
        if country and "中国" not in country:
            continue
        title = str(row.get("title") or row.get("event") or "").strip()
        if not title:
            continue
        stamp = str(row.get("time") or "").strip()
        out.append(
            {
                "date": date,
                "time": stamp[-8:] if len(stamp) > 8 else stamp,
                "title": title,
                "type": str(row.get("type") or "").strip(),
                "star": _pick_number(row, "star"),
            }
        )
    out.sort(key=lambda item: (item["date"] or "9999", -(item["star"] or 0)))
    return out[:limit]


def _margin(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """两融汇总：**只取最新一个交易日，并把交易所三行加起来**。

    两个坑各踩过一次：

    - 悟道返回的 ``latest`` 只是 rows 的第一行（实测是 BSE 的 83 亿），正文 headline 也
      用的是那一行。拿它当全市场余额，会把两融说小两个数量级（全市场实测 2.6 万亿）。
    - 两融是 **T+1 数据**，问当天必空，所以配方给的是七天窗口（`_MARGIN_WINDOW_DAYS`）。
      窗口里有多天 × 三所十几行，**一锅加起来就是把一周的余额摞在一起**。所以先挑出
      最大的 ``tradeDate``，只汇总那一天。
    """
    rows = _list_under(payload, "rows", "items")
    if not rows:
        return None
    latest_day = ""
    for row in rows:
        day = str(row.get("tradeDate") or row.get("trade_date") or "").strip()
        if day > latest_day:
            latest_day = day
    balance = 0.0
    net_buy = 0.0
    seen = 0
    exchanges: list[dict[str, Any]] = []
    for row in rows:
        day = str(row.get("tradeDate") or row.get("trade_date") or "").strip()
        if latest_day and day != latest_day:
            continue
        value = _pick_number(row, "marginBalance")
        if value is None:
            continue
        buy = _pick_number(row, "marginBuy") or 0.0
        repay = _pick_number(row, "marginRepay") or 0.0
        seen += 1
        balance += value
        net_buy += buy - repay
        exchanges.append(
            {
                "exchange": str(row.get("exchangeId") or "").strip(),
                "balance": value,
                "net_buy": buy - repay,
            }
        )
    if not seen:
        return None
    return {
        "trade_date": latest_day,
        "balance": balance,
        "net_buy": net_buy,
        "exchange_count": seen,
        "exchanges": exchanges,
    }


def _unlocks(payload: dict[str, Any] | None, *, limit: int = 5) -> list[dict[str, Any]]:
    """解禁排雷：按解禁比例从大到小报前几条。"""
    out: list[dict[str, Any]] = []
    for row in _list_under(payload, "rows", "items"):
        code = str(row.get("tsCode") or row.get("code") or "").strip()
        ratio = _pick_number(row, "floatRatio", "float_ratio")
        if not code or ratio is None:
            continue
        out.append(
            {
                "code": code.split(".")[0],
                "float_date": str(row.get("floatDate") or "").strip(),
                "float_ratio": ratio,
                "share_type": str(row.get("shareType") or "").strip(),
                "holder": str(row.get("holderName") or "").strip(),
            }
        )
    out.sort(key=lambda item: -(item["float_ratio"] or 0))
    return out[:limit]


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
