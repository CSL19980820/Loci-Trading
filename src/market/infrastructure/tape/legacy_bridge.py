"""旧 skill_watch 工具名到 tape lane 的兼容桥。

扫描器暂时仍消费 ``dict/raw payload``，所以桥只在 market 域内做一次 DTO
到旧载荷的投影。调用方不再知道 provider，也不会绕过 router 直连 MCP。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import re
from typing import Any

from src.market.domain.tape import TapeAttempt, TapeRequest, TapeResult
from src.market.infrastructure.tape.router import route_tape

LEGACY_TOOL_TO_LANE: dict[str, str] = {
    "short_term_emotion": "market_emotion",
    "limit_up_filter": "limit_up_pool",
    "limit_up_ladder": "limit_up_pool",
    "broken_limit_up": "broken_limit_up",
    "theme_intraday_capital": "theme_board",
    "theme_stocks": "theme_members",
    "auction_opening_snapshot": "auction_snapshot",
    "sector_analysis": "sector_analysis",
    # 与 sector_analysis 同池（247 个细分概念）的盘中截面，独立 lane 免得与
    # theme_board（271 个精选大类）互相污染缓存。
    "theme_concept_board": "theme_concept_board",
}

def _date_value(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(value or "").strip()[:10]


def _request_date(arguments: Mapping[str, Any]) -> str:
    for key in ("tradeDate", "trade_date", "requestedDate", "requested_date", "date"):
        value = arguments.get(key)
        if value:
            return _date_value(value)
    return ""


def _request_codes(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    raw_codes = arguments.get("codes", arguments.get("stockCodes", ()))
    if isinstance(raw_codes, str):
        values: Sequence[Any] = tuple(
            item.strip() for item in re.split(r"[\s,，;；]+", raw_codes) if item.strip()
        )
    elif isinstance(raw_codes, Sequence):
        values = raw_codes
    elif raw_codes in (None, ""):
        values = ()
    else:
        values = (raw_codes,)
    return tuple(str(code).strip() for code in values if str(code).strip())


def _request_limit(arguments: Mapping[str, Any]) -> int | None:
    value = arguments.get("limit", arguments.get("maxRows"))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _raw_payload(data: Any) -> Any:
    """把 Tape DTO / 已缓存 MCP 外壳恢复为旧解析器可读的 root。"""
    dto_payload = getattr(data, "payload", None)
    if isinstance(dto_payload, Mapping):
        return dict(dto_payload)
    if not isinstance(data, Mapping):
        return data
    for key in ("structured", "structuredContent"):
        nested = data.get(key)
        if isinstance(nested, Mapping):
            inner = nested.get("data")
            if isinstance(inner, Mapping) and (
                "tool" in nested or "success" in nested or "meta" in nested
            ):
                return dict(inner)
            return dict(nested)
    return dict(data)


def _attempt_payload(attempt: TapeAttempt) -> dict[str, Any]:
    return {
        "provider_id": attempt.provider_id,
        "lane": attempt.lane,
        "ok": attempt.ok,
        "status": attempt.status,
        "error": attempt.error,
        "elapsed_ms": attempt.elapsed_ms,
    }


def _provenance_payload(result: TapeResult) -> dict[str, Any]:
    provenance = result.provenance
    return {
        "provider_id": provenance.provider_id,
        "lane": provenance.lane,
        "requested_date": provenance.requested_date,
        "as_of_date": provenance.as_of_date,
        "fetched_at": provenance.fetched_at,
        "degraded": provenance.degraded,
        "stale": provenance.stale,
        "from_cache": provenance.from_cache,
        "warnings": list(provenance.warnings),
        "attempts": [_attempt_payload(item) for item in provenance.attempts],
    }


def _legacy_payload(
    name: str,
    arguments: Mapping[str, Any],
    result: TapeResult,
) -> dict[str, Any]:
    provenance = _provenance_payload(result)
    warnings = [str(item) for item in provenance["warnings"] if str(item).strip()]
    warnings = list(dict.fromkeys(warnings))
    data = _raw_payload(result.data)
    if result.error and not warnings:
        warnings.append(str(result.error))
    return {
        "tool": name,
        "arguments": dict(arguments),
        "structured": data if isinstance(data, Mapping) else {},
        "is_error": result.data is None,
        "unavailable": result.data is None,
        "text": str(result.error or ""),
        "provider_id": provenance["provider_id"],
        "provenance": provenance,
        "degraded": bool(provenance["degraded"]),
        "warnings": warnings,
    }


def _unsupported_payload(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tool": name,
        "arguments": dict(arguments),
        "structured": {},
        "is_error": True,
        "unavailable": True,
        "text": "unsupported_tape_tool",
        "provider_id": None,
        "provenance": {
            "provider_id": None,
            "lane": None,
            "requested_date": _request_date(arguments),
            "as_of_date": None,
            "degraded": True,
            "stale": False,
            "from_cache": False,
            "warnings": ["unsupported_tape_tool"],
            "attempts": [],
        },
        "degraded": True,
        "warnings": ["unsupported_tape_tool"],
    }


def legacy_call_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    store: Any | None = None,
    providers: Sequence[Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """通过统一 tape router 返回旧 scanner 能消费的 payload。"""
    tool = str(name or "").strip()
    args = dict(arguments or {})
    lane = LEGACY_TOOL_TO_LANE.get(tool)
    if lane is None:
        return _unsupported_payload(tool, args)
    context = {"market_store": store} if store is not None else {}
    request = TapeRequest(
        lane=lane,
        requested_date=_request_date(args),
        tool=tool,
        limit=_request_limit(args),
        codes=_request_codes(args),
        arguments=args,
        params=args,
        context=context,
        cache=True,
        cache_max_age_minutes=5,
    )
    result = route_tape(request, providers=providers, config=config)
    return _legacy_payload(tool, args, result)


def make_legacy_tape_call(
    *,
    store: Any | None = None,
    providers: Sequence[Any] | None = None,
    config: dict[str, Any] | None = None,
) -> Callable[..., dict[str, Any]]:
    """构造扫描器专用闭包，保留可注入 provider 的测试 seam。

    ``allow_injected_store=False``：工作线程取题材成分时不透传主线程
    MarketStore，迫使 local/cache provider 走 owned 独立连接（方案 B）。
    """

    def call(
        name: str,
        arguments: dict[str, Any],
        *,
        allow_injected_store: bool = True,
    ) -> dict[str, Any]:
        return legacy_call_tool(
            name,
            arguments,
            store=store if allow_injected_store else None,
            providers=providers,
            config=config,
        )

    return call


__all__ = [
    "LEGACY_TOOL_TO_LANE",
    "legacy_call_tool",
    "make_legacy_tape_call",
]
