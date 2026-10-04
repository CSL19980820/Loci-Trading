"""股票工作台事实投影：价格、观察时间与模型复核分别记录。"""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextvars import copy_context
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import time


def quote_values(quote: dict, now: datetime) -> tuple[int | None, str | None]:
    try:
        if quote.get("error"):
            return None, None
        value = quote.get("price", quote.get("current_price"))
        if isinstance(value, bool):
            return None, None
        price = Decimal(str(value))
        if not price.is_finite() or price <= 0:
            return None, None
        stamp = datetime.fromisoformat(f"{quote['trade_date']}T{quote['trade_time']}")
        stamp = stamp.replace(tzinfo=stamp.tzinfo or now.tzinfo)
        if stamp > now:
            return None, None
        return int((price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), stamp.isoformat()
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None, None


def research_quotes(codes: list[str], *, now: datetime, deadline: float,
                    force_refresh: bool = False, checkpoint=None) -> dict:
    """只读最近有效市场报价；收盘价可供研究，绝不授权模拟成交。"""
    if checkpoint:
        checkpoint()
    unique = list(dict.fromkeys(codes))
    if not unique:
        return {}
    from src.market.application.live_cache import build_monitor_snapshot
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-reference")
    started = time.monotonic()
    try:
        remaining = min(6.0, deadline-time.monotonic())
        if remaining <= 0:
            return {code: {"code": code, "error": "研究取价预算耗尽"} for code in unique}
        task = pool.submit(copy_context().run, build_monitor_snapshot, unique,
                           include_minute=False, force_refresh=force_refresh)
        try:
            quotes = task.result(timeout=remaining).quotes
        except FutureTimeout:
            task.cancel()
            return {code: {"code": code, "error": "研究行情暂未返回"} for code in unique}
        except Exception:
            return {code: {"code": code, "error": "研究行情暂不可用"} for code in unique}
        received_at = now+timedelta(seconds=time.monotonic()-started)
        result = {}
        for code in unique:
            row = quotes.get(code, {})
            price, stamp = quote_values(row, received_at)
            if price is None or row.get("code") not in (None, "", code) or not row.get("source"):
                result[code] = {"code": code, "error": "缺少可核验的研究报价"}
            else:
                result[code] = {**row, "research_reference": True,
                                "quote_received_at": received_at.isoformat(),
                                "quote_age_seconds": max(0, int((received_at-datetime.fromisoformat(stamp)).total_seconds()))}
        if checkpoint:
            checkpoint()
        return result
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def capture_observation_prices(state: dict, *, quotes: dict, now: datetime) -> dict:
    result = deepcopy(state)
    for row in result.get("watchlist", []):
        price, stamp = quote_values(quotes.get(row["code"], {}), now)
        if row.get("observed_price_cents") is None and not row.get("observation_price_attempted_at") and row.get("added_at"):
            try:
                added = datetime.fromisoformat(row["added_at"])
                # 只记录首次入池这一轮实际取到的报价，旧缺失价格不回填。
                if added.tzinfo and 0 <= (now-added).total_seconds() <= 180:
                    row["observation_price_attempted_at"] = now.isoformat()
                    if price is not None:
                        row.update(observed_price_cents=price, observed_price_at=stamp)
            except ValueError:
                pass
    return result


def entry_prices(trades: list[dict], quantities: dict[str, int] | None = None) -> dict[str, float]:
    """按账本平均成本方式回放实际成交；买入价不包含规费。"""
    books: dict[str, tuple[int, Decimal]] = {}
    for trade in trades:
        code = str(trade.get("code") or "")
        qty, price = trade.get("quantity"), trade.get("price_cents")
        if not code or type(qty) is not int or qty <= 0 or type(price) is not int or price <= 0:
            continue
        held, gross = books.get(code, (0, Decimal(0)))
        if trade.get("side") == "buy":
            books[code] = (held + qty, gross + qty * price)
        elif trade.get("side") == "sell" and held >= qty:
            books[code] = (held - qty, gross * (held - qty) / held)
    return {code: float(gross / qty) for code, (qty, gross) in books.items()
            if qty and (quantities is None or quantities.get(code) == qty)}


def enrich_workbench_state(state: dict, *, now: datetime, trades: list[dict] | None = None,
                           quotes: dict | None = None) -> dict:
    result = deepcopy(state)
    prices = entry_prices(trades or [], {row["code"]: row["quantity"] for row in result.get("positions", [])})
    for row in result.get("positions", []):
        context = row.get("entry_context") or {}
        at = context.get("opened_at")
        try:
            stamp = datetime.fromisoformat(at) if at else None
            if stamp:
                stamp = stamp.astimezone(now.tzinfo) if stamp.tzinfo else stamp.replace(tzinfo=now.tzinfo)
            days = (now.date() - stamp.date()).days if stamp and stamp <= now else None
        except (ValueError, TypeError):
            at, days = None, None
        cost = row.get("cost_cents", 0)
        row.update(entry_at=at, entry_price_cents=prices.get(row["code"]), holding_days=days,
                   entry_reason=str(context.get("reason") or ""),
                   pnl_pct=round(row["unrealized_pnl_cents"] / cost * 100, 2) if cost > 0 else None)
    for row in result.get("watchlist", []):
        row["observed_at"] = row.get("observed_at") or row.get("added_at")
        row.setdefault("observed_price_cents", None)
        # 老数据 updated_at 只在模型真实提交 watch 动作时存在；自动入池不是复核。
        if not row.get("reviewed_at") and row.get("updated_at"):
            row.update(reviewed_at=row["updated_at"], review_reason=str(row.get("reason") or ""), review_status="wait")
        row.setdefault("review_reason", "")
        row.setdefault("expected_entry_price_cents", None)
        row.setdefault("review_status", "unreviewed")
        price, stamp = quote_values((quotes or {}).get(row["code"], {}), now)
        previous_at = row.get("current_price_at")
        try:
            previous = datetime.fromisoformat(previous_at) if previous_at else None
            if previous and previous.tzinfo is None:
                previous = previous.replace(tzinfo=now.tzinfo)
        except (ValueError, TypeError):
            previous = None
        if price is not None and (previous is None or datetime.fromisoformat(stamp) >= previous):
            row.update(current_price_cents=price, current_price_at=stamp)
        else:
            row.setdefault("current_price_cents", None)
            row.setdefault("current_price_at", None)
    return result


def apply_workbench_research(state: dict, decision, *, quotes: dict, now: datetime,
                             coverage: dict | None = None) -> dict:
    result = capture_observation_prices(enrich_workbench_state(state, now=now, quotes=quotes), quotes=quotes, now=now)
    assessments = {item.code: item for item in (getattr(decision, "assessments", None) or [])}
    for row in result.get("watchlist", []):
        item = assessments.get(row["code"])
        if item is not None and item.stance != "unreviewed":
            expected = item.expected_entry_price
            row.update(reviewed_at=now.isoformat(), review_reason=item.summary, review_status=item.stance,
                       expected_entry_price_cents=int(Decimal(str(expected)) * 100) if expected is not None else None)
    plan = getattr(decision, "research_plan_structured", None)
    if plan is not None:
        result["research_plan_structured"] = plan.model_dump(mode="json")
    if coverage is not None:
        result["assessment_coverage"] = deepcopy(coverage)
    return result


def valuation_snapshot(state: dict, at: datetime) -> dict:
    return {"day": at.date().isoformat(), "at": at.isoformat(), "equity_cents": state["equity_cents"],
            "funded_cents": state["initial_capital_cents"], "pnl_cents": state["equity_cents"] - state["initial_capital_cents"],
            "realized_pnl_cents": state["realized_pnl_cents"], "fees_cents": state["fees_cents"],
            "stale": int(bool(state.get("stale_codes")))}
