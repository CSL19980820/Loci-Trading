"""交易员盘前/盘后报告的可核对事实，模型不参与资金计算。"""
from copy import deepcopy
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import guardian_account_at, guardian_position_policy, mark_guardian_account
from src.market import scheduled_trading_days
from src.ops.application.retired_slugs import RETIRED_STRATEGY_MARKERS
from src.ops.application.guardian_opening_plans import fold_opening_plans

TZ = ZoneInfo("Asia/Shanghai")
PERIOD_LABELS = {"premarket": "盘前计划", "daily": "日复盘", "weekly": "周复盘"}


def allocation_snapshot(account: dict, day: str) -> dict:
    """收盘资金配置事实，不以期末仓位代替全周平均暴露。"""
    equity, cash = account['equity_cents'], account['cash_cents']
    return {'date': day, 'equity_cents': equity, 'cash_cents': cash,
            'exposure_pct': (equity - cash) / equity * 100 if equity > 0 else None,
            'position_count': len(account['positions']),
            'positions': [{'code': p['code'], 'name': p['name'], 'quantity': p['quantity'],
                           'market_value_cents': p['market_value_cents'],
                           'weight_pct': p['market_value_cents'] / equity * 100 if equity > 0 else None}
                          for p in account['positions']]}


def _report_available_as_of(report: dict[str, Any] | None, cutoff: datetime) -> bool:
    """Match history-tool visibility; nominal trade dates do not date revisions."""
    if not report or report.get("status") != "success":
        return False
    raw = (report.get("result") or {}).get("created_at")
    try:
        # guardian_reports.started is a Unix timestamp, not a date string.
        stamp = (datetime.fromtimestamp(float(report.get("started")), timezone.utc)
                 if raw is None else datetime.fromisoformat(str(raw)))
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    # As in SQLite julianday(), timezone-less date strings represent UTC.
    return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc) <= cutoff


def _contains_retired_strategy_reference(report: dict[str, Any]) -> bool:
    """历史报告保留，但不把已退役战法的分析原文带入新计划。"""
    import json

    analysis = report.get("result", {}).get("analysis") or {}
    serialized = json.dumps(analysis, ensure_ascii=False)
    return any(marker in serialized for marker in RETIRED_STRATEGY_MARKERS)


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
    # 成交流水可重建收益，不能重建没有成交的合同安装、撤回及过期。
    # 当前报告独立保存实际合同快照；历史报告不以今天的合同冒充过去状态。
    risk_contracts = {"available": False, "as_of": None, "source": "not_recorded",
                      "positions": [], "note": "成交流水不包含完整风险合同，缺失不等于零条。"}
    if day == now.date().isoformat():
        from src.ops.application.guardian_risk import evaluate_risk_plans
        checked, _, _ = evaluate_risk_plans(current, {}, now)
        risk_contracts = {"available": True, "as_of": now.isoformat(), "source": "ledger_state",
            "positions": [{"code": p["code"], "quantity": p["quantity"],
                           "entry_context": deepcopy(p.get("entry_context", {})),
                           "risk_plans": deepcopy(p.get("risk_plans", []))} for p in checked["positions"]],
            "note": "独立于收盘账务的实际合同快照；按as_of检查有效期与持仓绑定，不写回、不下单。"}
    initial = current["initial_capital_cents"]
    trades = ledger.all_trades(end)
    baseline_day = previous_day(market, start)
    baseline = closing_account(market, trades, baseline_day, initial)
    allocation_points = [allocation_snapshot(baseline, baseline_day)]
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
            allocation_points.append(allocation_snapshot(close, trade_day))
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
    status_counts = Counter((row['slot'][:10], row['status']) for row in cycles)
    status_by_date = {day_key: {status: count for (day_value, status), count in status_counts.items()
                                if day_value == day_key} for day_key in sorted({key[0] for key in status_counts})}
    preopen = ledger.report("premarket", day)
    memory_cutoff = min(now, datetime.combine(date.fromisoformat(day), time(23, 59, 59), TZ))
    experience = ledger.experience(as_of=memory_cutoff.isoformat(), day=day)
    daily_learning = ledger.daily_learning(start, end, memory_cutoff.isoformat()) if period == 'weekly' else []
    from src.ops.application.guardian_evidence import cycle_evidence
    cycle_rows = [{k: v for k, v in cycle_evidence(c).items() if k not in {"input_candidates", "account_before"}}
                  for c in cycles]
    earlier = [r for r in ledger.reports(30) if _report_available_as_of(r, memory_cutoff) and r["trade_date"] <= day
               and (r["period"], r["trade_date"]) != (period, day)]
    if period == "weekly":
        earlier = [r for r in earlier if r["period"] == "daily" and r["trade_date"] >= start]
    else:
        earlier = [r for r in earlier if r["period"] != "premarket" or r["trade_date"] == day]
    # 旧报告仍是审计历史；已退役战法不再作为新复盘的研究输入，避免名称/观点
    # 从盘前或旧日复盘的 analysis 原文重新污染当前计划。
    earlier = [r for r in earlier if not _contains_retired_strategy_reference(r)]
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
            "experience": experience, "daily_learning": daily_learning,
            "created_at": now.isoformat(), "account": account, "account_basis": "reconstructed_from_trades",
            "risk_contracts": risk_contracts, "baseline_equity_cents": baseline["equity_cents"],
            "current_position_policy": {"as_of": now.isoformat(), "usage": "当前及未来计划；不能代替历史当轮规则快照。",
                                        **guardian_position_policy(current, now)},
            "baseline_sources": baseline.get("closing_sources", []),
            "period_pnl_cents": pnl, "period_return_pct": round(pnl / baseline["equity_cents"] * 100, 4) if baseline["equity_cents"] else None,
            "period_realized_pnl_cents": sum(t["realized_pnl_cents"] for t in period_trades),
            "opening_plan_reconciliation": fold_opening_plans(cycles, now),
            "execution_facts": {"has_premarket_report": _report_available_as_of(preopen, memory_cutoff),
                                "trade_records": len(period_trades),
                                "legacy_conversions": sum(t.get("origin") == "legacy_conversion" for t in period_trades),
                                "model_trade_records": sum(t.get("origin") != "legacy_conversion" for t in period_trades),
                                "expired_cycles": sum(c["status"] == "expired" for c in cycles),
                                "expired_cycle_slots": [c["slot"] for c in cycles if c["status"] == "expired"],
                                "failed_cycles": sum(c["status"] == "failed" for c in cycles),
                                "failed_cycles_with_fills": sum(c["status"] == "failed" and bool(c["result"].get("fills")) for c in cycles),
                                "failed_cycle_slots": [c["slot"] for c in cycles if c["status"] == "failed"],
                                "cycle_status_counts_by_date": status_by_date,
                                "first_successful_cycle": min((c["slot"] for c in cycles if c["status"] == "success"), default=None),
                                "first_buy_decision_cycle": min((c["slot"] for c in cycles if any(d.get("action") == "buy" for d in c["result"].get("decisions", []))), default=None),
                                "timing_semantics": "cycle时间是轮次开始；成交时间用trades.occurred_at，不用trade.id。failed可能已有部分成交，不等于整轮未执行；工程失败、模型观望、旧约束拒单分别归因，不能说全天无判断或所有尾盘成交均由早盘故障导致。",
                                "current_scope": "全市场自主选择，观察池是研究参考；历史操作按当时记录评价。",
                                "execution_cadence": "连续竞价期间每5分钟研判，最后连续竞价研判轮次14:55，15:00另做收盘研判；不是实时或券商条件单，15:00后不能成交"},
            "period_fees_cents": sum(t["fees_cents"] for t in period_trades),
            "close_drawdown_pct": round(drawdown, 4), "equity_points": points,
            "allocation_points": allocation_points,
            "trades": period_trades, "stock_performance": list(by_code.values()), "cycles": cycle_rows,
            "next_trade_date": next_trade_date,
            "planning_trade_date": day if period == "premarket" else next_trade_date,
            "planning_sellable": [{"code": p["code"], "quantity": p["available_quantity"] if period == "premarket" else p["quantity"]} for p in account["positions"]],
            "watchlist": current.get("watchlist", []) if day == now.date().isoformat() else [],
            "current_plans": [{k: p.get(k) for k in ("code", "holding_plan", "take_profit_plan", "stop_loss_plan", "exit_today_plan")} for p in current["positions"]] if day == now.date().isoformat() else [],
            "previous_reviews_as_of": memory_cutoff.isoformat(),
            "previous_reviews": [{"id": r["report_key"], "date": r["trade_date"], "analysis": r["result"].get("analysis")} for r in earlier[:5]],
            "evidence_ids": [f"experience:{experience['revision']}:{item['id']}" for item in experience['items']] + [r['report_key'] for r in daily_learning] + [f"trade:{t['id']}" for t in period_trades] + [c["id"] for c in cycle_rows] + [f"close:{p['code']}:{account['valuation_at'][:10]}" for p in account["positions"]] + [r["report_key"] for r in earlier[:5]]}
