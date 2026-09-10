"""逐段投影：情绪宽度 / 题材 / 梯队，加上复盘与排雷六段。

一条共同纪律：**只投影，不发明**。字段缺就给 None / 空列表，不拿别处的数字顶替，
也不在这里做二次口径换算（例外只有 ``_percent``：把 0–1 比例统一成 0–100 百分数）。

为什么单独成文件：每个函数与悟道**某一张表的字段名**一一绑定，上游改字段只波及
一个函数，与 `brief.py` 里「哪几段拼成一份摘要、缺数据时长什么样」的编排决策无关。
段落只会越加越多（2026-08-31 一次进了六段），编排入口不该跟着一起长。
"""

from __future__ import annotations

from typing import Any

from src.intel.application.brief_payload import (
    _find_mapping,
    _list_under,
    _metric,
    _number,
    _percent,
    _pick_number,
    _rows,
    _structured,
    _walk,
)


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


#: 悟道 sentimentSignal 的三值枚举 → 人话。翻译只留一份，前端不再自己猜。
_SENTIMENT_ZH = {"cooling": "退潮", "neutral": "中性", "warming": "修复"}


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
