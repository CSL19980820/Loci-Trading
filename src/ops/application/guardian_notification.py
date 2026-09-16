"""Intraday notice facts and formatting; never change research or settlement state."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    "holding_quotes": "持仓行情读取", "context": "研究资料准备", "research": "交易研判",
    "final_quotes": "成交前核价", "preflight": "交易预检", "preflight_repair": "预检修正",
    "commit": "成交核账",
}


def notice_reason(value: Any, limit: int = 100) -> str:
    """Keep diagnostic detail in the run, not credentials or a traceback in a push."""
    text = str(value or "原因未提供").split("Traceback (most recent call last):", 1)[0]
    text = re.sub(r"https?://\S+", "[服务地址已隐藏]", text)
    text = re.sub(r"(?i)\b(bearer\s+)\S+", r"\1[已隐藏]", text)
    text = re.sub(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*[^\s,;]+",
                  r"\1=[已隐藏]", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…（详见运行记录）"


def _positive_cents(value: Any) -> bool:
    return type(value) is int and value > 0


def load_notification_day(
    ledger: Any, now: datetime, *, market_factory: Callable | None = None,
) -> dict[str, Any]:
    """Read-only, best-effort daily basis. Missing display data must not block a trade."""
    day = now.date().isoformat()
    facts: dict[str, Any] = {"trade_date": day, "baseline_equity_cents": None,
                             "baseline_date": None, "trade_counts_available": False}
    try:
        account = ledger.state()
        facts["initial_capital_cents"] = account["initial_capital_cents"]
        trades = ledger.all_trades(day)
        today = [t for t in trades if t["occurred_at"][:10] == day]
        facts.update(buy_count=sum(t["side"] == "buy" for t in today),
                     sell_count=sum(t["side"] == "sell" for t in today),
                     fees_cents=sum(t["fees_cents"] for t in today), trade_counts_available=True)
        premarket = ledger.report("premarket", day)
        if premarket and premarket["status"] == "success":
            saved = premarket["result"].get("facts", {})
            baseline = saved.get("baseline_equity_cents")
            if (saved.get("trade_date") == day and saved.get("period") == "premarket"
                    and str(saved.get("baseline_date") or "") < day
                    and saved.get("baseline_date")
                    and saved.get("account", {}).get("initial_capital_cents") == account["initial_capital_cents"]
                    and _positive_cents(baseline)):
                facts.update(baseline_equity_cents=baseline, baseline_date=saved["baseline_date"],
                             baseline_source="premarket_report")
                return facts
        # No trades before today means the account started the day in cash.
        if not any(t["occurred_at"][:10] < day for t in trades):
            facts.update(baseline_equity_cents=account["initial_capital_cents"],
                         baseline_source="initial_cash")
            return facts
        # Reuse only a verified same-day basis, never cached trade counts or current equity.
        recent = getattr(ledger, "recent", None)
        for cycle in recent(5) if callable(recent) else []:
            cached = cycle.get("result", {}).get("notification_facts", {})
            if (cached.get("trade_date") == day
                    and cached.get("initial_capital_cents") == account["initial_capital_cents"]
                    and cached.get("baseline_source") in {"official_close", "premarket_report", "initial_cash"}
                    and _positive_cents(cached.get("baseline_equity_cents"))):
                facts.update({key: cached.get(key) for key in
                              ("baseline_equity_cents", "baseline_date", "baseline_source")})
                facts["baseline_from_slot"] = cycle.get("slot")
                return facts
        if market_factory is not None:
            from src.ops.application.guardian_review_data import previous_day, closing_account
            with market_factory() as market:
                baseline_day = previous_day(market, day)
                if baseline_day >= day:
                    raise ValueError("上一交易日不能是当日或未来日期")
                baseline = closing_account(market, trades, baseline_day, account["initial_capital_cents"])
            facts.update(baseline_equity_cents=baseline["equity_cents"], baseline_date=baseline_day,
                         baseline_source="official_close")
    except Exception as exc:
        from src.ops.application.jobs.context import JobCancelled, JobTimedOut
        if isinstance(exc, (JobCancelled, JobTimedOut)):
            raise
        facts["data_error"] = notice_reason(exc)
        logger.warning("guardian notice day facts unavailable: %s", facts["data_error"])
    return facts


def with_notification_facts(
    state: dict[str, Any], facts: dict[str, Any], fills: list[dict], *, slot: str,
) -> dict[str, Any]:
    """Pending fills are included only in the notice committed atomically with them."""
    daily = dict(facts)
    if daily.get("trade_counts_available"):
        daily["buy_count"] += sum(f["side"] == "buy" for f in fills)
        daily["sell_count"] += sum(f["side"] == "sell" for f in fills)
        daily["fees_cents"] += sum(f["fees_cents"] for f in fills)
    baseline = daily.get("baseline_equity_cents")
    equity = state.get("equity_cents")
    if _positive_cents(baseline) and type(equity) is int and not state.get("valuation_error"):
        daily["pnl_cents"] = equity - baseline
        daily["return_pct"] = (equity - baseline) / baseline * 100
    return {**state, "notification_day": daily, "notification_slot": slot}


def render_account_overview(state: dict[str, Any]) -> str:
    money = lambda value: f"{value / 100:,.2f}"
    positions = state.get("positions", [])
    lines = []
    if state.get("notification_slot"):
        lines.append(f"轮次 · {state['notification_slot']}（北京时间）")
    valuation_error = state.get("valuation_error")
    equity = state.get("equity_cents")
    total = f"{money(equity)} 元" if type(equity) is int and not valuation_error else "暂不可用"
    cash = state.get("cash_cents")
    cash_text = f"{money(cash)} 元" if type(cash) is int else "暂不可用"
    lines.append(f"账户 · 总资产 {total} · 现金 {cash_text} · 持仓 {len(positions)} 只")
    daily = state.get("notification_day", {})
    if "pnl_cents" in daily and not valuation_error:
        lines.append(f"今日盈亏 {daily['pnl_cents'] / 100:+,.2f} 元（{daily['return_pct']:+.2f}%）")
    else:
        lines.append("今日盈亏 · 暂不可用（缺少有效估值或上一交易日收盘基准）")
    if daily.get("trade_counts_available"):
        lines.append(f"今日成交 · 买入/加仓 {daily['buy_count']} 笔 · 卖出/减仓 {daily['sell_count']} 笔"
                     f" · 费用 {money(daily['fees_cents'])} 元")
    if valuation_error:
        lines.append("估值未完成，未将旧资产数字当作本轮实时值。")
    elif state.get("stale_codes"):
        lines.append(f"估值提示 · {len(state['stale_codes'])} 只股票使用最近有效报价，资产及今日盈亏仅供参考。")
    return "\n".join(lines)


def render_failure_notice(state: dict[str, Any], exc: Exception, stage: str) -> str:
    label = STAGE_LABELS.get(stage, "本轮任务")
    timeout = isinstance(exc, TimeoutError) or "超过270秒" in str(exc)
    timeout_label = "研判" if stage == "research" else label
    reason = f"{timeout_label}超时，未在本轮有效期内完成；过期意图不执行。" if timeout else notice_reason(exc)
    return (render_account_overview(state) + f"\n\n本轮未完成 · {label}\n原因 · {reason}"
            "\n本轮无已落账成交；预检结果不计成交。\n完整诊断保留在设置 → 运行记录。")
