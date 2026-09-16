"""Shared quote validation for execution and valuation."""
from __future__ import annotations
import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def fresh_quote(quote: dict[str, Any], now: datetime) -> bool:
    day = str(quote.get("trade_date") or "").replace("-", "")
    clock = str(quote.get("trade_time") or "").replace(":", "")
    try:
        stamp = datetime.strptime(day + clock, "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
    except (ValueError, TypeError):
        return False
    current = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now
    return 0 <= (current - stamp).total_seconds() <= 180


def quote_error(code: str, quote: dict[str, Any], now: datetime) -> str | None:
    if not isinstance(quote, dict):
        return "Invalid quote format"
    if quote.get("error"):
        return str(quote["error"])
    if quote.get("code") not in (None, "", code):
        return "报价股票代码不匹配"
    price = quote.get("price", quote.get("current_price"))
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return "缺少有效实时价格"
    if not fresh_quote(quote, now):
        return "报价过期、来自未来或缺少行情时间"
    return None


def validated_quotes(quotes: dict[str, dict[str, Any]], now: datetime) -> dict[str, dict[str, Any]]:
    return {code: dict(q) for code, q in quotes.items() if quote_error(code, q, now) is None}
