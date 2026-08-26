"""MCP 扫池参数裁剪：统一挂在 call_mcp_tool / guarded 边界。"""
from __future__ import annotations

from typing import Any

# 上限的**权威来源是服务端 schema**（悟道 MCP `tools/list` 里每个参数的 maximum），
# 不是本文件的手感。本模块只防「无上限扇出」，不懂各工具语义：值比 schema 大 =
# 服务端 400 直接拒（`additionalProperties: false` 的工具连整条调用一起废），
# 值比 schema 小只是白白少取几行。所以宁可对齐 schema，也别留一个「比服务端还大」
# 的上限假装宽松。
_MCP_LIMIT_MAX = 200
#: `maxRows` / `days` 在 live schema 里都是 ≤150（同 builtin_market_mcp 的 kline
#: days maximum=150）。旧代码把 maxRows 混进 _MCP_LIMIT_KEYS 用 200 兜，
#: 于是 `maxRows=200` 会被服务端整条拒掉——裁剪器反而成了废调用的来源。
_MCP_ROWS_MAX = 150
_MCP_CODES_MAX = 50
_MCP_DAYS_MAX = 150
_MCP_LIMIT_KEYS = (
    "limit",
    "pageSize",
    "page_size",
    "topN",
    "top_n",
    "count",
    "screener_count",
    "theme_top_n",
    "stock_flow_top_n",
    "theme_limit",
    "member_limit",
)
#: 与 _MCP_LIMIT_KEYS 分开：同是「要多少行」，服务端给的天花板不同。
_MCP_ROWS_KEYS = ("maxRows", "max_rows")
_MCP_WINDOW_KEYS = ("days", "window", "window_days")
_MCP_CODE_KEYS = ("codes", "stockCodes", "stock_codes")


def _split_code_tokens(value: str) -> list[str]:
    parts: list[str] = []
    for chunk in value.replace("\n", " ").replace("\t", " ").replace(";", ",").split(","):
        for token in chunk.split():
            cleaned = token.strip()
            if cleaned:
                parts.append(cleaned)
    return parts


def clamp_mcp_arguments_with_notes(
    arguments: dict[str, Any] | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """裁剪扫池参数，并回报「哪个参数被削到多少」。

    静默截断会让调用方把「只看了前 50 只」当成「全市场都没有」，所以每次真正
    缩小取数范围都要留一条 ``key:before->after`` 记录，交给上层写进警告。
    """
    args = dict(arguments or {})
    notes: list[str] = []

    def _note(key: str, before: Any, after: Any) -> None:
        notes.append(f"{key}:{before}->{after}")

    # 三组「数量」参数的天花板不同（limit / maxRows / days），逐组按各自上限裁，
    # 不再共用一个 200：共用会让 maxRows 带着服务端不接受的值出门。
    for keys, ceiling in (
        (_MCP_LIMIT_KEYS, _MCP_LIMIT_MAX),
        (_MCP_ROWS_KEYS, _MCP_ROWS_MAX),
        (_MCP_WINDOW_KEYS, _MCP_DAYS_MAX),
    ):
        for key in keys:
            if key not in args:
                continue
            raw = args[key]
            try:
                args[key] = max(1, min(ceiling, int(raw)))
            except (TypeError, ValueError):
                args[key] = ceiling
                _note(key, raw, ceiling)
                continue
            if args[key] != raw:
                _note(key, raw, args[key])
    for key in _MCP_CODE_KEYS:
        value = args.get(key)
        if isinstance(value, list) and len(value) > _MCP_CODES_MAX:
            args[key] = value[:_MCP_CODES_MAX]
            _note(key, len(value), _MCP_CODES_MAX)
        elif isinstance(value, str):
            parts = _split_code_tokens(value)
            if len(parts) > _MCP_CODES_MAX:
                args[key] = ",".join(parts[:_MCP_CODES_MAX])
                _note(key, len(parts), _MCP_CODES_MAX)
            elif "," in value or " " in value or "\n" in value:
                args[key] = ",".join(parts)
    return args, tuple(notes)


def clamp_mcp_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """裁剪助手/Skill/Job 透传的 MCP 扫池参数，防止无上限扇出。"""
    return clamp_mcp_arguments_with_notes(arguments)[0]


__all__ = ["clamp_mcp_arguments", "clamp_mcp_arguments_with_notes"]
