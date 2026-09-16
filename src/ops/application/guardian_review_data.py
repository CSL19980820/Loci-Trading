"""交易员盘前/盘后报告的可核对事实，模型不参与资金计算。"""
from datetime import date, datetime, time, timedelta, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import guardian_account_at, mark_guardian_account
from src.market import scheduled_trading_days

TZ = ZoneInfo("Asia/Shanghai")
PERIOD_LABELS = {"premarket": "盘前计划", "daily": "日复盘", "weekly": "周复盘"}


def report_window(period: str, day: str, now: datetime) -> tuple[str, str]:
    target = date.fromisoformat(day)
    if period not in PERIOD_LABELS or target > now.date():
        raise ValueError("报告类型或日期无效")
    if day not in scheduled_trading_days(day, day):
        raise LookupError("非交易日，无需生成交易员报告")
    if period == "premarket":
        if target != now.date() or not time(8, 50) <= now.time().replace(tzinfo=None) < time(9, 25):
            raise LookupError("盘前计划仅在当日08:50至09:25生成，不事后伪造盘前计划")
        return day, day
    if target == now.date() and now.time().replace(tzinfo=None) < time(15, 45):
        raise LookupError("日/周复盘在15:45以后、收盘行情就绪后生成")
    start = target - timedelta(days=target.weekday()) if period == "weekly" else target
    if period == "weekly":
        week_days = scheduled_trading_days(start.isoformat(), (start + timedelta(days=6)).isoformat())
        if not week_days or day != week_days[-1]:
            raise LookupError("今天不是本周最后一个交易日")
    return start.isoformat(), day


def previous_day(market: Any, day: str) -> str:
    end = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    days = market.trading_days(end=end)
    if not days:
        raise ValueError("缺少上一交易日数据，不能构造期初净值")
    previous = days[-1]
    next_day = (date.fromisoformat(previous) + timedelta(days=1)).isoformat()
    if next_day <= end and scheduled_trading_days(next_day, end):
        raise ValueError("行情库交易日历落后，上一交易日尚未入库")
    return previous


def closing_account(market: Any, trades: list[dict], day: str, initial: int) -> dict[str, Any]:
    state = guardian_account_at(trades, day, initial_cents=initial)
    closed_at = datetime.combine(date.fromisoformat(day), time(15), TZ)
    quotes = {}
    sources = []
    for p in state["positions"]:
        frame = market.history(p["code"], start=day, end=day, adjust="none")
        if frame.empty:
            raise ValueError(f"{p['code']} 缺少 {day} 收盘日线，等待行情落库")
        row = frame.iloc[-1].to_dict()
        close = row.get("close")
        if str(row.get("trade_date")) != day or not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
            raise ValueError(f"{p['code']} 收盘价格无效")
        if row.get("source") not in {"tdx", "tdx_daily"}:
            raise ValueError(f"{p['code']} 尚无权威收盘日线，当前来源 {row.get('source')}")
        try:
            fetched = datetime.fromisoformat(str(row.get("fetched_at") or ""))
            # quotes_daily.fetched_at 使用SQLite datetime('now')，无时区值为UTC。
            fetched = fetched.replace(tzinfo=fetched.tzinfo or timezone.utc)
        except ValueError as exc:
            raise ValueError(f"{p['code']} 缺少可核对的日线采集时间") from exc
        if fetched < closed_at:
            raise ValueError(f"{p['code']} 日线采集于收盘前，不能拿盘中价做日结")
        quotes[p["code"]] = {"price": close, "trade_date": day, "trade_time": "15:00:00", "source": row["source"]}
        sources.append({"code": p["code"], "trade_date": day, "source": row["source"],
                        "close": close, "fetched_at": fetched.isoformat(), "receipt_id": row.get("receipt_id") if isinstance(row.get("receipt_id"), str) else None})
    result = mark_guardian_account(state, quotes, closed_at)
    result["valuation_kind"] = "official_close"
    result["valuation_date"] = day
    result["closing_sources"] = sources
    return result


def build_review_facts(ledger: Any, market: Any, period: str, day: str, now: datetime) -> dict[str, Any]:
    start, end = report_window(period, day, now)
    current = ledger.state()
    initial = current["initial_capital_cents"]
    trades = ledger.all_trades(end)
    baseline_day = previous_day(market, start)
    baseline = closing_account(market, trades, baseline_day, initial)
    if period == "premarket":
        account = mark_guardian_account(baseline, {}, now)
        account["valuation_kind"] = "previous_close"
        points = []
        period_trades = []
    else:
        account = closing_account(market, trades, end, initial)
        points = [{"date": baseline_day, "equity_cents": baseline["equity_cents"]}]
        for trade_day in scheduled_trading_days(start, end):
            close = account if trade_day == end else closing_account(market, trades, trade_day, initial)
            points.append({"date": trade_day, "equity_cents": close["equity_cents"]})
        period_trades = [t for t in trades if start <= t["occurred_at"][:10] <= end]
    by_code: dict[str, dict[str, Any]] = {}
    for source, key in ((baseline, "start_value_cents"), (account, "end_value_cents")):
        for p in source["positions"]:
            by_code.setdefault(p["code"], {"code": p["code"], "name": p["name"]})[key] = p["market_value_cents"]
    for fill in period_trades:
        row = by_code.setdefault(fill["code"], {"code": fill["code"], "name": fill["name"]})
        side = fill["side"]
        row[f"{side}_quantity"] = row.get(f"{side}_quantity", 0) + fill["quantity"]
        row["cash_flow_cents"] = row.get("cash_flow_cents", 0) + (fill["gross_cents"] if side == "sell" else -fill["gross_cents"]) - fill["fees_cents"]
        row["realized_pnl_cents"] = row.get("realized_pnl_cents", 0) + fill["realized_pnl_cents"]
        row["fees_cents"] = row.get("fees_cents", 0) + fill["fees_cents"]
    for row in by_code.values():
        row["period_pnl_cents"] = row.get("end_value_cents", 0) - row.get("start_value_cents", 0) + row.get("cash_flow_cents", 0)
    pnl = account["equity_cents"] - baseline["equity_cents"] if period != "premarket" else 0
    if period != "premarket" and sum(r["period_pnl_cents"] for r in by_code.values()) != pnl:
        raise ValueError("个股收益与账户净值变化未对齐，拒绝生成报告")
    peak = baseline["equity_cents"]
    drawdown = 0.0
    for point in points:
        peak = max(peak, point["equity_cents"])
        drawdown = min(drawdown, (point["equity_cents"] / peak - 1) * 100 if peak else 0)
    cycles = ledger.cycles_between(start, end)
    preopen = ledger.report("premarket", day)
    from src.ops.application.guardian_evidence import cycle_evidence
    cycle_rows = [{k: v for k, v in cycle_evidence(c).items() if k not in {"input_candidates", "account_before"}}
                  for c in cycles]
    earlier = [r for r in ledger.reports(30) if r["status"] == "success" and r["trade_date"] <= day
               and (r["period"], r["trade_date"]) != (period, day)]
    if period == "weekly":
        earlier = [r for r in earlier if r["period"] == "daily" and r["trade_date"] >= start]
    else:
        earlier = [r for r in earlier if r["period"] != "premarket" or r["trade_date"] == day]
    next_trade_date = None
    for offset in range(1, 16):
        candidate = (date.fromisoformat(day) + timedelta(days=offset)).isoformat()
        try:
            if scheduled_trading_days(candidate, candidate):
                next_trade_date = candidate
                break
        except ValueError:
            break
    return {"period": period, "start_date": start, "trade_date": day, "baseline_date": baseline_day,
            "created_at": now.isoformat(), "account": account, "baseline_equity_cents": baseline["equity_cents"],
            "baseline_sources": baseline.get("closing_sources", []),
            "period_pnl_cents": pnl, "period_return_pct": round(pnl / baseline["equity_cents"] * 100, 4) if baseline["equity_cents"] else None,
            "period_realized_pnl_cents": sum(t["realized_pnl_cents"] for t in period_trades),
            "execution_facts": {"has_premarket_report": bool(preopen and preopen["status"] == "success"),
                                "trade_records": len(period_trades),
                                "legacy_conversions": sum(t.get("origin") == "legacy_conversion" for t in period_trades),
                                "model_trade_records": sum(t.get("origin") != "legacy_conversion" for t in period_trades),
                                "expired_cycles": sum(c["status"] == "expired" for c in cycles),
                                "expired_cycle_slots": [c["slot"] for c in cycles if c["status"] == "expired"],
                                "failed_cycles": sum(c["status"] == "failed" for c in cycles),
                                "failed_cycle_slots": [c["slot"] for c in cycles if c["status"] == "failed"],
                                "first_successful_cycle": min((c["slot"] for c in cycles if c["status"] == "success"), default=None),
                                "first_buy_decision_cycle": min((c["slot"] for c in cycles if any(d.get("action") == "buy" for d in c["result"].get("decisions", []))), default=None),
                                "timing_semantics": "cycle时间是轮次开始；成交时间用trades.occurred_at，不用trade.id。工程失败、模型观望、旧约束拒单分别归因，不能说全天无判断或所有尾盘成交均由早盘故障导致。",
                                "current_scope": "全市场自主选择，观察池不是买入准入白名单；历史观察范围拒单属于已取消的旧约束",
                                "execution_cadence": "连续竞价期间每5分钟研判，最后连续竞价研判轮次14:55，15:00另做收盘研判；不是实时或券商条件单，15:00后不能成交"},
            "period_fees_cents": sum(t["fees_cents"] for t in period_trades),
            "close_drawdown_pct": round(drawdown, 4), "equity_points": points,
            "trades": period_trades, "stock_performance": list(by_code.values()), "cycles": cycle_rows,
            "next_trade_date": next_trade_date,
            "planning_trade_date": day if period == "premarket" else next_trade_date,
            "planning_sellable": [{"code": p["code"], "quantity": p["available_quantity"] if period == "premarket" else p["quantity"]} for p in account["positions"]],
            "watchlist": current.get("watchlist", []) if day == now.date().isoformat() else [],
            "current_plans": [{k: p.get(k) for k in ("code", "holding_plan", "take_profit_plan", "stop_loss_plan", "exit_today_plan")} for p in current["positions"]] if day == now.date().isoformat() else [],
            "previous_reviews": [{"id": r["report_key"], "date": r["trade_date"], "analysis": r["result"].get("analysis")} for r in earlier[:5]],
            "evidence_ids": [f"trade:{t['id']}" for t in period_trades] + [c["id"] for c in cycle_rows] + [f"close:{p['code']}:{account['valuation_at'][:10]}" for p in account["positions"]] + [r["report_key"] for r in earlier[:5]]}
