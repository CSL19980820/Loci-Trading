"""Shared quote validation for execution and valuation."""
from __future__ import annotations
import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
#: 行情时间最多可比本机时钟晚这么多秒：服务器与行情源的时钟偏差，以及按结束时刻标注的
#: 进行中分钟线（10:02:30 取到的最新一根标 10:03）。零容差会把这些当前报价判成“来自未来”，
#: 主源整体被弃用、持仓缺价，进而拒单。更晚的时间仍视为无效。
FUTURE_SKEW_SECONDS = 60


def fresh_quote(quote: dict[str, Any], now: datetime, *, max_age_seconds: int = 180) -> bool:
    day = str(quote.get("trade_date") or "").replace("-", "")
    clock = str(quote.get("trade_time") or "").replace(":", "")
    try:
        stamp = datetime.strptime(day + clock, "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
    except (ValueError, TypeError):
        return False
    current = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now
    return -FUTURE_SKEW_SECONDS <= (current - stamp).total_seconds() <= max_age_seconds


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


def executable_quote(code: str, action: str, quantity: int, quote: dict[str, Any], now: datetime,
                     *, used_quantity: int = 0, paper: bool = False) -> dict[str, Any]:
    """天才交易员仅按有效行情价模拟；其他调用方保留严格盘口撮合。"""
    if paper:
        problem = quote_error(code, quote, now)
        if problem:
            raise ValueError(problem)
        if quantity <= 0:
            raise ValueError("模拟申报股数必须为正数")
        limit_evidence = _paper_buy_limit(code, action, quote, now)
        execution_quote = _paper_price_proxy(code, action, quantity, quote, now)
        if limit_evidence:
            execution_quote["execution_evidence"]["limit_up_check"] = limit_evidence
        return execution_quote
    book = quote.get("order_book")
    if not isinstance(book, dict) or book.get("code") != code or not book.get("source"):
        raise ValueError("缺少可核验的实时盘口，本轮未成交；分钟价格不能证明可成交")
    problem = quote_error(code, book, now)
    if problem or not fresh_quote(book, now, max_age_seconds=30):
        raise ValueError("盘口无效、过期或股票不匹配，本轮未成交")

    def number(key: str, *, zero: bool = False) -> float:
        value = book.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or (not zero and value == 0)):
            raise ValueError(f"盘口字段{key}缺失或无效，本轮未成交")
        return value

    buying = action in {"buy", "add"}
    upper, lower = number("limit_up"), number("limit_down")
    last = number("price")
    if upper <= lower or not lower <= last <= upper:
        raise ValueError("盘口涨跌停价格范围不一致，本轮未成交")
    if (buying and last >= upper) or (not buying and last <= lower):
        raise ValueError("涨停买入无法确认排队成交，本轮未成交" if buying else "跌停卖出无法确认排队成交，本轮未成交")
    side = "ask" if buying else "bid"
    price, depth = number(side + "_price", zero=True), number(side + "_quantity", zero=True)
    if price == 0 or depth == 0:
        raise ValueError("没有可成交的卖盘，本轮未成交" if buying else "没有可成交的买盘，本轮未成交")
    if not lower <= price <= upper or (buying and price >= upper) or (not buying and price <= lower):
        raise ValueError("对手报价到达涨跌停边界或越界，无法确认排队成交，本轮未成交")
    bid, ask = number("bid_price", zero=True), number("ask_price", zero=True)
    if bid > 0 and ask > 0 and bid > ask:
        raise ValueError("盘口买卖价交叉，本轮未成交")
    insufficient = depth - used_quantity < quantity
    if quantity <= 0 or (insufficient and not paper):
        raise ValueError("对手一档剩余数量不足，本轮未成交；不虚构全部或部分成交")
    return {**book, "price": price, "execution_evidence": {
        "method": "paper_opposite_best_v1" if paper else "opposite_best_v1",
        "simulated": True, "side": side,
        **({"liquidity_assumption": "full_quantity_beyond_displayed_depth" if insufficient else "displayed_depth",
            "requested_quantity": quantity, "price_proxy": False} if paper else {}),
        "used_quantity": used_quantity, "book": dict(book)}}


def _paper_buy_limit(code: str, action: str, quote: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """行情价模拟不能假定涨停排队成交；缺少可靠涨停参考时买入暂不执行。"""
    if action not in {"buy", "add"}:
        return None

    def positive(value: Any) -> Decimal | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return None
        return Decimal(str(value))

    cent = Decimal("0.01")
    previous = positive(quote.get("prev_close"))
    upper = positive(quote.get("limit_up"))
    reference = "quote_limit_up" if upper is not None else ""
    reference_quote = quote
    supplement = quote.get("limit_reference")
    if (isinstance(supplement, dict) and not supplement.get("error") and supplement.get("code") == code
            and isinstance(supplement.get("source"), str) and supplement["source"].strip()
            and str(supplement.get("trade_date") or "").replace("-", "") == now.strftime("%Y%m%d")):
        if upper is None and positive(supplement.get("limit_up")) is not None:
            upper, reference = positive(supplement["limit_up"]), "same_day_limit_reference"
            reference_quote = supplement
        if previous is None and positive(supplement.get("prev_close")) is not None:
            previous, reference_quote = positive(supplement["prev_close"]), supplement
    # 当日同股同源盘口只可提供静态涨停参考，不使用盘口深度或对手价撮合。
    book = quote.get("order_book")
    if (upper is None and isinstance(book, dict) and not book.get("error") and book.get("code") == code
            and book.get("source") == quote.get("source") and fresh_quote(book, now)):
        upper = positive(book.get("limit_up"))
        reference = "same_day_limit_up" if upper is not None else ""
        if upper is not None:
            reference_quote = book

    expected = None
    ratio = None
    if previous is not None:
        from src.market.domain.universe import classify_board, is_st_name
        board = classify_board(code)
        ratio = {"star": Decimal("0.20"), "chi_next": Decimal("0.20"), "bse": Decimal("0.30")}.get(board)
        if board == "main":
            # 沪深2026版交易规则自7月6日起将主板风险警示股票也调整为10%。
            historical_st = now.date().isoformat() < "2026-07-06" and is_st_name(reference_quote.get("name", quote.get("name", "")))
            ratio = Decimal("0.05") if historical_st else Decimal("0.10")
        if ratio is not None:
            expected = (previous * (1 + ratio)).quantize(cent, rounding=ROUND_HALF_UP)
            expected = max(expected, previous.quantize(cent, rounding=ROUND_HALF_UP) + cent)
    if upper is not None:
        if upper != upper.quantize(cent, rounding=ROUND_HALF_UP) or (previous is not None and upper <= previous):
            raise ValueError("当日涨停参考价无效，本轮不买入或加仓")
        if expected is not None and upper != expected:
            raise ValueError("当日涨停参考价与昨收、板块规则不一致，本轮不买入或加仓")
    elif expected is not None:
        upper, reference = expected, "prev_close_board_rule"
    else:
        raise ValueError("缺少可靠当日涨停价或昨收参考，本轮不买入或加仓；不得用现价或涨幅反推昨收")
    price = Decimal(str(quote.get("price", quote.get("current_price")))).quantize(cent, rounding=ROUND_HALF_UP)
    if price >= upper:
        raise ValueError(f"最新报价{price}已达涨停价{upper}，禁止模拟买入或加仓；等待开板后以新行情重新研判")
    return {"limit_up": float(upper), "reference": reference,
            "prev_close": float(previous) if previous is not None else None,
            "limit_ratio": float(ratio) if ratio is not None else None,
            "source": reference_quote.get("source"), "trade_date": reference_quote.get("trade_date"),
            "trade_time": reference_quote.get("trade_time"), "code": code,
            "checked_at": now.isoformat()}


def _paper_price_proxy(code: str, action: str, quantity: int, quote: dict[str, Any], now: datetime) -> dict[str, Any]:
    """用户授权的行情价模拟：盘口存在、缺失或损坏都不参与成交判断。"""
    if quote.get("code") != code or not isinstance(quote.get("source"), str) or not quote["source"].strip():
        raise ValueError("模拟报价缺少可信股票代码或行情来源")
    price = quote.get("price", quote.get("current_price"))
    # Keep only the price evidence used for this fill. Optional book fields must
    # neither veto the trade nor masquerade as validated execution evidence.
    price_quote = {key: value for key, value in quote.items() if key not in {
        "order_book", "order_book_error", "bid_price", "ask_price", "bid_quantity", "ask_quantity",
        "limit_up", "limit_down", "execution_evidence",
    }}
    return {**price_quote, "price": price, "execution_evidence": {
        "method": "paper_quote_proxy_v2", "simulated": True, "price_proxy": True,
        "liquidity_assumption": "full_quantity_order_book_ignored", "requested_quantity": quantity,
        "checked_at": now.isoformat(), "quote": price_quote}}
