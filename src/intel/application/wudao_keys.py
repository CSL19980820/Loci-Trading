r"""悟道 MCP 参数键名的**单一真相源**。

为什么单独一个模块：同一份映射曾经在三处各写一份——`daily_recipe._DATE_REQUIRED`、
`tape/wudao_provider.DATE_ARG_BY_TOOL`，以及 `ops/skill_watch/*` 里直接硬编码的
日期键。三份必然漂移，实测结果是：同一个 `broken_limit_up`，两处都写 `tradeDate`，
而服务端只认 `date`——整条调用被 INVALID_ARGUMENTS 拒掉，上层读成「悟道没数据」。

悟道 schema 多是 additionalProperties=false：**键名写错不是被忽略，而是整条作废**。
所以键名只能有一份，且只能来自真实调用验证。

下表每一行都经双向验证（正键 + 对照键各打一次，看服务端认哪个），证据在
``output/wudao-key-verification*.json``。靠「同族约定」推断过五次错了四次。
"""
from __future__ import annotations

#: 工具 → 服务端认的交易日键名（全部实测双向验证过）。
#:
#: | 工具 | 键名 | 验证结论 |
#: |---|---|---|
#: | short_term_emotion | tradeDate | 实测 date 被拒 |
#: | theme_intraday_capital | tradeDate | 实测 date 被拒 |
#: | theme_stocks | tradeDate | 实测 date 被拒 |
#: | auction_opening_snapshot | tradeDate | 实测 date 被拒 |
#: | trading_calendar | date | 实测 tradeDate 被拒 |
#: | approaching_limit_up | date | 实测 tradeDate 被拒 |
#: | limit_stats | date | 实测 tradeDate 被拒（曾写错） |
#: | limit_up_ladder | date | 实测 tradeDate 被拒（曾写错） |
#: | broken_limit_up | date | 实测 tradeDate 被拒（曾写错） |
#: | limit_up_filter | date | 实测 tradeDate 被拒（曾写错） |
#: | limit_down | date | 实测 tradeDate 被拒（2026-08-31 双向验证） |
#: | anomaly_detection | date | 实测 tradeDate 被拒（2026-08-31 双向验证） |
#: | board_break_analysis | tradeDate | 实测 date 被拒（2026-08-31 双向验证） |
#: | auction_theme_strength | tradeDate | 实测 date 被拒（2026-08-31 双向验证） |
#: | margin_trading | tradeDate | 实测 date 被拒（2026-08-31 双向验证） |
#: | northbound_holdings | tradeDate | 实测 date 被拒（2026-08-31 双向验证） |
DATE_ARG_BY_TOOL: dict[str, str] = {
    "short_term_emotion": "tradeDate",
    "theme_intraday_capital": "tradeDate",
    "theme_stocks": "tradeDate",
    "auction_opening_snapshot": "tradeDate",
    "trading_calendar": "date",
    "approaching_limit_up": "date",
    "limit_stats": "date",
    "limit_up_ladder": "date",
    "broken_limit_up": "date",
    "limit_up_filter": "date",
    "limit_down": "date",
    "anomaly_detection": "date",
    "board_break_analysis": "tradeDate",
    "auction_theme_strength": "tradeDate",
    "margin_trading": "tradeDate",
    "northbound_holdings": "tradeDate",
}

#: **一个日期键都不补**的工具。两类原因，别混：
#:
#: 1. **服务端不收任何日期键**：补了就是整条 INVALID_ARGUMENTS。
#:    `sector_analysis` 实测 tradeDate 与 date 双双被拒，空参数才通；
#:    `unlock_events` 实测 tradeDate 被拒（它只认 startDate/endDate 区间）。
#: 2. **语义是「向前看的日历」**：`macro_calendar` / `market_catalyst_calendar`
#:    的 schema 有单日 `date`，但我们要的是「今天起未来 N 天」那一段，补上今天
#:    等于把日历砍成一天。两者实测 tradeDate 被拒；要单日请调用方显式传 `date`。
DATELESS_TOOLS: frozenset[str] = frozenset(
    {
        "sector_analysis",
        "unlock_events",
        "macro_calendar",
        "market_catalyst_calendar",
    }
)

#: 表里没有的工具按多数派处理。新工具接入前先真打一次再登记。
DEFAULT_DATE_ARG = "tradeDate"

#: 调用方可能自带其中任一个；再补一个同义键 = 一次请求两个日期键，
#: schema 只声明其中一个，照样整条被拒。补之前要先摘干净。
DATE_ALIASES: tuple[str, ...] = ("tradeDate", "date", "trade_date", "requestedDate")

#: 批量代码键名。同是「传一批代码」，悟道两个键名并存。
#: capital_flow=stockCodes（实测两收，取 schema 声明的）、
#: intraday_main_flow=codes（实测 stockCodes 被拒）、kline=codes（实测两收）。
CODES_ARG_BY_TOOL: dict[str, str] = {
    "capital_flow": "stockCodes",
    "intraday_main_flow": "codes",
    "kline": "codes",
}


def date_argument(tool: str, day: str) -> dict[str, str]:
    """该工具要的交易日参数；不收日期的工具返回空 dict。

    调用点一律用它，别手写日期键——硬编码正是三份表漂移的来源。
    """
    text = str(day or "").strip()
    if not text or tool in DATELESS_TOOLS:
        return {}
    return {DATE_ARG_BY_TOOL.get(tool, DEFAULT_DATE_ARG): text}


def with_date(tool: str, day: str, **extra: object) -> dict[str, object]:
    """``date_argument`` + 其它参数，省掉调用点每次拼 dict。"""
    merged: dict[str, object] = dict(extra)
    merged.update(date_argument(tool, day))
    return merged


def strip_dates(arguments: dict) -> dict:
    """摘掉所有日期别名，供补规范键之前先归一。"""
    out = dict(arguments)
    for alias in DATE_ALIASES:
        out.pop(alias, None)
    return out