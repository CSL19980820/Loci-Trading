"""结构化情报采集配方：把 ~3000 次/天拆成 open / intraday / close 三档。"""
from __future__ import annotations

from src.intel.application.wudao_keys import (
    CODES_ARG_BY_TOOL as _WUDAO_CODES_ARG_BY_TOOL,
    DATE_ARG_BY_TOOL as _WUDAO_DATE_ARG_BY_TOOL,
)

from datetime import date as _date, timedelta
from typing import Any, Literal

IntelPhase = Literal["open", "intraday", "close"]

# 悟道多数工具的 schema 是 additionalProperties: false：传一个它不认的键，整条调用
# 会被 INVALID_ARGUMENTS 整体拒掉，而不是忽略该键。所以下面每条只写该工具真正
# 声明过的参数——「顺手加个 limit」会让这次采集白跑。
#: limit_up_filter 服务端上限
_LIMIT_UP_FILTER_MAX = 100

#: 交易日键名的真相在 ``wudao_keys``——那张表每一行都经真实调用双向验证。
#: 这里曾自己维护一份，与 tape 侧和 skill_watch 硬编码三份并存，必然漂移。
_DATE_REQUIRED = _WUDAO_DATE_ARG_BY_TOOL

#: limit_up_premium 是区间统计，单日样本通常达不到 minLimitUpCount（默认 5），
#: 取近一个月窗口才有胜率意义。
_PREMIUM_WINDOW_DAYS = 30

#: unlock_events 默认窗口是「近 30 天 ~ 未来 365 天」，一年的解禁全塞进来只会把
#: 排雷信号淹掉。收盘档只要「未来一个月」这一段：短线关心的是马上要砸下来的
#: 那批限售股，更远的等它走近了再采。
_UNLOCK_WINDOW_DAYS = 30

#: 两融回看窗口（自然日）。两融是 T+1 数据，收盘档问当天必空；七天足够跨过周末与
#: 小长假，取最新一天由 `brief._margin` 负责。
_MARGIN_WINDOW_DAYS = 7

#: 盘中题材扇出上限。盘中题材榜单十几分钟内不会翻天：top 40 与 top 120 对决策的
#: 差别，远小于每天多打 (120-40)×轮数 ≈ 1900 次、把 structured 池打穿的代价。
#: open / close 仍用完整 ``theme_top_n``——开盘与收盘的截面才是复盘要用的那两张。
#: **可配**：`build_followup_calls(..., intraday_theme_top_n=…)`，Job 配置键同名。
INTRADAY_THEME_TOP_N = 40

#: 盘中托管 cron 的**真相在 `ops/application/ensure_intel_jobs.py`**，这里只是兜底
#: 镜像。估算器按它数轮次，调用方（`jobs/intel_fetch.py`）会把 ops.db 里那条任务的
#: 真实 cron 传进来。曾经写死「20 轮」，而 `*/15 9-14` 实际每天触发 24 轮——估算
#: 天生比实际低两成，闸门自然永远卡不住。
DEFAULT_INTRADAY_CRON = "*/15 9-14 * * mon-fri"

#: 两池默认日预算（与 `infrastructure/wudao_settings.DEFAULT_QUOTA` 同源）。调用方
#: 拿得到 `quota_snapshot()` 的真实值时应显式传入，别依赖这两个常量。
STRUCTURED_BUDGET = 3000
SKILL_RESERVE = 2000


def _expand_cron_field(field: str, *, low: int, high: int) -> list[int]:
    """展开一个 cron 字段（支持 ``*`` / ``a-b`` / ``*/n`` / ``a-b/n`` / 逗号列表）。"""
    values: set[int] = set()
    for part in str(field or "").split(","):
        token = part.strip()
        if not token:
            continue
        step = 1
        if "/" in token:
            token, _, step_text = token.partition("/")
            step = int(step_text)
            if step <= 0:
                raise ValueError(f"cron 步长非法：{step_text}")
        token = token.strip() or "*"
        if token == "*":
            start, end = low, high
        elif "-" in token:
            head, _, tail = token.partition("-")
            start, end = int(head), int(tail)
        else:
            start = end = int(token)
        if start > end or start < low or end > high:
            raise ValueError(f"cron 字段越界：{part}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("cron 字段为空")
    return sorted(values)


def intraday_runs_from_cron(cron: str | None = None) -> int:
    """按 cron 数出「一个交易日真的会触发几轮」。

    只看分钟与小时两段：日/月/星期决定的是「哪些天跑」，而配额按天算（工作日 cron
    在每个交易日都跑满）。解析不出来时退回 ``DEFAULT_INTRADAY_CRON`` 的轮数，**不**
    返回一个乐观的小数字——估少了等于闸门形同虚设。
    """
    text = str(cron or "").strip() or DEFAULT_INTRADAY_CRON
    fields = text.split()
    try:
        if len(fields) < 5:
            raise ValueError(f"cron 字段不足 5 段：{text}")
        minutes = _expand_cron_field(fields[0], low=0, high=59)
        hours = _expand_cron_field(fields[1], low=0, high=23)
    except ValueError:
        if text != DEFAULT_INTRADAY_CRON:
            return intraday_runs_from_cron(DEFAULT_INTRADAY_CRON)
        return 24
    return len(minutes) * len(hours)


def _shift_days(day: str, delta: int) -> str:
    try:
        base = _date.fromisoformat(day[:10])
    except ValueError:
        return day
    return (base + timedelta(days=delta)).isoformat()


def _resolve_trade_date(trade_date: str | None) -> str:
    text = str(trade_date or "").strip()
    if text:
        return text[:10]
    from src.intel.infrastructure.quota import trade_date_today

    return trade_date_today()


def _with_dates(tool: str, args: dict[str, Any], trade_date: str) -> dict[str, Any]:
    """补齐 schema 必填的日期；调用方已显式给过就不覆盖。"""
    out = dict(args)
    if tool == "margin_trading":
        # 两融是 **T+1 才发布**的数据：拿 15:40 收盘档去问当天，服务端返回「融资融券汇总」
        # 但一行都没有（线上实测过）。所以给一个七天窗口，由消费侧
        # （`brief._margin`）取窗口里最新那一天——周一与节后也不会落到没有数据的日子上。
        # schema 明写 `tradeDate` 与 `startDate`/`endDate` **二选一**，所以这里直接 return，
        # 不再走下面补 `tradeDate` 的那一步。
        out.setdefault("endDate", trade_date)
        out.setdefault("startDate", _shift_days(trade_date, -_MARGIN_WINDOW_DAYS))
        return out
    date_key = _DATE_REQUIRED.get(tool)
    if date_key:
        out.setdefault(date_key, trade_date)
    if tool == "limit_up_premium":
        out.setdefault("endDate", trade_date)
        out.setdefault("startDate", _shift_days(trade_date, -_PREMIUM_WINDOW_DAYS))
    if tool == "unlock_events":
        # 它不收 tradeDate/date（实测被拒，见 wudao_keys.DATELESS_TOOLS），只认区间。
        out.setdefault("startDate", trade_date)
        out.setdefault("endDate", _shift_days(trade_date, _UNLOCK_WINDOW_DAYS))
    return out


# 截面工具优先：一次调用覆盖全市场，避免逐股扫池。
_STATIC_OPEN: list[tuple[str, dict[str, Any]]] = [
    ("trading_calendar", {}),
    ("short_term_emotion", {}),
    ("auction_opening_snapshot", {}),
    ("limit_stats", {}),
    ("market_overview", {}),
    ("index_market", {}),
    ("news_hotlist", {"limit": 30}),
    ("theme_intraday_capital", {"limit": 80, "includeBoomReason": True}),
    ("sector_analysis", {"source": "kpl"}),
    ("limit_up_ladder", {}),
    ("limit_up_filter", {"limit": _LIMIT_UP_FILTER_MAX}),
    ("approaching_limit_up", {}),
    ("broken_limit_up", {}),
    ("auction_market_scan", {"sortBy": "limitBuyAmount", "limit": 50}),
    ("auction_market_scan", {"sortBy": "finalSealAmount", "limit": 50}),
    ("smart_hotlist", {"limit": 50}),
    # 同花顺单平台榜与上面的综合榜并存：热度尾盘战法要的是两榜交集，且 MCP 不返回
    # hot_rank_chg，只能靠 open / close 两档快照差分算注意力增量。见 ADR-011 决策 3、4。
    ("smart_hotlist", {"limit": 50, "platform": "ths"}),
    # 竞价题材强度：把全市场竞价数据按开盘啦题材聚合，回答「今天竞价资金打哪条
    # 主线」。**必须 summary 档**：standard 档正文默认吐 JSON 明细，实测单次载荷
    # 63KB（summary 5KB），每天一张快照进 intel_snapshots，不值这个体积；明细
    # 要看时由助手临机点调。9:25 前调会返回 AUCTION_DATA_NOT_READY，本档 9:26 跑。
    ("auction_theme_strength", {"limit": 12, "detailLevel": "summary"}),
    # 短线催化日历：未来两周的政策会议/行业大会/指数调整/经济数据。盘前排雷用，
    # 一天一张就够。**不传 country**：服务端过滤值对不上就是静默 0 行，行里本来
    # 就带 country 字段，按「中国」筛在消费侧做（brief）。
    ("market_catalyst_calendar", {"limit": 60}),
    ("cls_news", {"limit": 40}),
]

_STATIC_INTRADAY: list[tuple[str, dict[str, Any]]] = [
    ("short_term_emotion", {}),
    ("limit_up_ladder", {}),
    ("theme_intraday_capital", {"limit": 60, "includeBoomReason": True}),
    ("index_market", {}),
    ("market_overview", {}),
    ("approaching_limit_up", {}),
    ("cls_news", {"limit": 25}),
]

_STATIC_CLOSE: list[tuple[str, dict[str, Any]]] = [
    ("short_term_emotion", {}),
    ("limit_up_ladder", {}),
    ("limit_up_filter", {"limit": _LIMIT_UP_FILTER_MAX}),
    ("broken_limit_up", {}),
    ("limit_up_premium", {}),
    ("limit_event_summary", {}),
    ("dragon_tiger", {}),
    # 断板分析：昨涨停 × 今日的交叉面板（断板率 / 断板平均涨跌 / 高标杀名单 /
    # sentimentSignal=cooling|neutral|warming）。这是短线复盘最缺的那张表——本地
    # 日 K 能算「有没有涨停」，算不出「昨天的涨停今天活着几只」。focus=all 一次
    # 拿续板与断板两侧，省一次调用。
    ("board_break_analysis", {"focus": "all", "limit": 80}),
    # 跌停池：权威跌停口径 + stats 里今日/昨日封板率与炸板数。情绪段此前只能靠
    # short_term_emotion 的 sealedLimitDown 兜底，缺跌停原因与负反馈明细。
    ("limit_down", {}),
    # 两融汇总：不传 code = 交易所汇总（SSE/SZSE/BSE 三行）。杠杆资金是「谁在
    # 加/减杠杆」这一层，本地库完全没有。**注意**：返回的 `latest` 只是第一行
    # （实测是 BSE），全市场余额要把三行加起来，别拿 latest 当全市场。
    ("margin_trading", {}),
    # 限售解禁：未来一个月（区间在 `_with_dates` 里补）。盘前/盘后排雷，本地无源。
    ("unlock_events", {"limit": 60}),
    ("theme_intraday_capital", {"limit": 100, "includeBoomReason": True}),
    ("sector_analysis", {"source": "kpl"}),
    ("index_market", {}),
    ("market_overview", {}),
    ("news_hotlist", {"limit": 40}),
    ("smart_hotlist", {"limit": 60}),
    ("smart_hotlist", {"limit": 60, "platform": "ths"}),
    ("stock_screener", {"closePctChgMin": 7, "limit": 80}),
    ("stock_screener", {"volumeRatioMin": 2.5, "aboveMa": [5], "limit": 80}),
    ("stock_screener", {"conceptKeywords": ["机器人"], "limit": 60}),
    ("stock_screener", {"conceptKeywords": ["半导体"], "limit": 60}),
    ("stock_screener", {"conceptKeywords": ["新能源车"], "limit": 60}),
]

#: 闸门/监测下游要算指标的工具：正文走 JSON，配合 structuredContent 双保险
_JSON_BODY_TOOLS = frozenset(
    {
        "short_term_emotion",
        "limit_up_ladder",
        "theme_intraday_capital",
        "broken_limit_up",
        "auction_opening_snapshot",
        "auction_market_scan",
        "theme_stocks",
        "kline",
        "limit_up_filter",
        "approaching_limit_up",
    }
)


def _json_args(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    if tool in _JSON_BODY_TOOLS:
        out.setdefault("format", "json")
        out.setdefault("detailLevel", "standard")
    return out


_SCREENER_SWEEPS: list[dict[str, Any]] = [
    {"closePctChgMin": 5, "aboveMa": [5], "limit": 80},
    {"closePctChgMin": 7, "volumeRatioMin": 1.8, "limit": 80},
    {"closePctChgMin": 9, "limit": 60},
    {"highPctChgMin": 7, "limit": 80},
    {"marketCapMinYi": 30, "marketCapMaxYi": 200, "closePctChgMin": 3, "limit": 80},
    {"marketCapMinYi": 200, "closePctChgMin": 2, "limit": 80},
    {"nameIncludes": ["龙"], "closePctChgMin": 2, "limit": 40},
    {"conceptKeywords": ["人工智能"], "limit": 60},
    {"conceptKeywords": ["低空经济"], "limit": 60},
    {"conceptKeywords": ["华为"], "limit": 60},
]


def _theme_stock_calls(theme_codes: list[str]) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for code in theme_codes:
        text = str(code or "").strip()
        if not text:
            continue
        calls.append(("theme_stocks", {"themeCode": text, "limit": 120}))
    return calls


#: 批量代码键名同样只留一份，见 ``wudao_keys.CODES_ARG_BY_TOOL``。
_CODES_ARG_BY_TOOL = _WUDAO_CODES_ARG_BY_TOOL
#: 批量工具在代码池之外的固定参数（键名同样照 schema 写）。
_BATCH_EXTRA_ARGS: dict[str, dict[str, Any]] = {
    "capital_flow": {"flowType": "stock"},
    "intraday_main_flow": {},
    "kline": {"days": 30, "maxRows": 30},
}
#: 只收单只代码的工具 → (每批最多打几只, 固定参数)。它们没有代码数组参数，
#: 硬塞 codes 会整条作废，只能一只一调，所以必须自己限量。
_SINGLE_CODE_TOOLS: dict[str, tuple[int, dict[str, Any]]] = {
    "minute_data": (5, {}),
    "official_disclosure_evidence": (5, {"limit": 5}),
}


def _batch_flow_calls(
    codes: list[str],
    *,
    tool: str,
    batch_size: int = 20,
) -> list[tuple[str, dict[str, Any]]]:
    clean = [str(code).strip() for code in codes if str(code).strip()]
    calls: list[tuple[str, dict[str, Any]]] = []
    for index in range(0, len(clean), batch_size):
        chunk = clean[index : index + batch_size]
        if not chunk:
            continue
        if tool in _SINGLE_CODE_TOOLS:
            per_batch, extra = _SINGLE_CODE_TOOLS[tool]
            calls.extend((tool, {"code": code, **extra}) for code in chunk[:per_batch])
            continue
        extra_args = _BATCH_EXTRA_ARGS.get(tool)
        if extra_args is None:
            continue
        calls.append((tool, {**extra_args, _CODES_ARG_BY_TOOL[tool]: chunk}))
    return calls


def _extract_theme_codes(payload: dict[str, Any] | None, *, limit: int) -> list[str]:
    if not payload:
        return []
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return []
    rows = structured.get("rows") or structured.get("items") or []
    if not isinstance(rows, list):
        return []
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("themeCode") or row.get("code") or "").strip()
        if code and code not in codes:
            codes.append(code)
        if len(codes) >= limit:
            break
    return codes


def _extract_stock_codes(payload: dict[str, Any] | None, *, limit: int) -> list[str]:
    if not payload:
        return []
    structured = payload.get("structured")
    if not isinstance(structured, dict):
        return []
    rows = structured.get("rows") or structured.get("items") or []
    if not isinstance(rows, list):
        return []
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or row.get("stockCode") or "").strip()
        if code and code not in codes:
            codes.append(code)
        if len(codes) >= limit:
            break
    return codes


def build_static_calls(
    phase: IntelPhase,
    *,
    screener_count: int = 10,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    if phase == "open":
        static = list(_STATIC_OPEN)
        static.extend(("stock_screener", args) for args in _SCREENER_SWEEPS[:screener_count])
    elif phase == "intraday":
        static = list(_STATIC_INTRADAY)
    else:
        static = list(_STATIC_CLOSE)
        static.extend(("stock_screener", args) for args in _SCREENER_SWEEPS[: max(screener_count, 8)])
    day = _resolve_trade_date(trade_date)
    return [
        {"tool": tool, "arguments": _json_args(tool, _with_dates(tool, args, day)), "cache": True}
        for tool, args in static
    ]


def _theme_fanout(phase: IntelPhase, *, theme_top_n: int, intraday_theme_top_n: int) -> int:
    """本档要打几条题材成分。

    盘中单独设上限（``INTRADAY_THEME_TOP_N``）：题材榜十几分钟内不会翻天，top 40 与
    top 120 对决策的差别远小于把配额打穿的代价。open / close 保持完整 ``theme_top_n``,
    开盘与收盘的截面是复盘要用的那两张，不能砍。
    """
    if phase == "intraday":
        return max(0, min(int(theme_top_n), int(intraday_theme_top_n)))
    return max(0, int(theme_top_n))


def build_followup_calls(
    phase: IntelPhase,
    prior_results: dict[str, dict[str, Any]],
    *,
    theme_top_n: int = 120,
    stock_flow_top_n: int = 160,
    intraday_theme_top_n: int = INTRADAY_THEME_TOP_N,
) -> list[dict[str, Any]]:
    """依赖首轮截面结果的主题成分、资金流、K 线等深挖。"""
    calls: list[dict[str, Any]] = []
    theme_seed = _extract_theme_codes(prior_results.get("theme_intraday_capital"), limit=theme_top_n)
    ladder_codes = _extract_stock_codes(prior_results.get("limit_up_ladder"), limit=stock_flow_top_n)
    filter_codes = _extract_stock_codes(prior_results.get("limit_up_filter"), limit=stock_flow_top_n)
    stock_pool = list(dict.fromkeys(ladder_codes + filter_codes))[:stock_flow_top_n]

    theme_n = _theme_fanout(
        phase, theme_top_n=theme_top_n, intraday_theme_top_n=intraday_theme_top_n
    )
    for tool, args in _theme_stock_calls(theme_seed[:theme_n]):
        calls.append({"tool": tool, "arguments": _json_args(tool, args), "cache": True})

    flow_n = {"open": 80, "intraday": 60, "close": stock_flow_top_n}[phase]
    for tool in ("capital_flow", "intraday_main_flow"):
        calls.extend(
            {"tool": item[0], "arguments": _json_args(item[0], item[1]), "cache": True}
            for item in _batch_flow_calls(stock_pool[:flow_n], tool=tool)
        )

    if phase in {"open", "close"}:
        calls.extend(
            {"tool": item[0], "arguments": _json_args(item[0], item[1]), "cache": True}
            for item in _batch_flow_calls(stock_pool[: min(100, flow_n)], tool="kline")
        )
        if phase == "close":
            calls.extend(
                {"tool": item[0], "arguments": item[1], "cache": True}
                for item in _batch_flow_calls(stock_pool[: min(80, flow_n)], tool="minute_data")
            )
            calls.extend(
                {"tool": item[0], "arguments": item[1], "cache": True}
                for item in _batch_flow_calls(
                    stock_pool[: min(60, flow_n)], tool="official_disclosure_evidence"
                )
            )
    return calls


def build_phase_calls(
    phase: IntelPhase,
    *,
    theme_top_n: int = 120,
    stock_flow_top_n: int = 160,
    screener_count: int = 10,
    intraday_theme_top_n: int = INTRADAY_THEME_TOP_N,
    prior_results: dict[str, dict[str, Any]] | None = None,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """静态 +（可选）follow-up 合并清单。"""
    calls = build_static_calls(phase, screener_count=screener_count, trade_date=trade_date)
    if prior_results:
        calls.extend(
            build_followup_calls(
                phase,
                prior_results,
                theme_top_n=theme_top_n,
                stock_flow_top_n=stock_flow_top_n,
                intraday_theme_top_n=intraday_theme_top_n,
            )
        )
    return calls



# 别名形式是 PEP 484 的显式再导出标记：这些名字本模块不用，只为兼容旧导入路径。
from src.intel.application.quota_estimate import (  # noqa: E402
    estimate_daily_calls as estimate_daily_calls,
    structured_budget_alert as structured_budget_alert,
)
