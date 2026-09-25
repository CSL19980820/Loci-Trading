"""每五分钟自主研判；成交与研判分离，无成交轮次只在内部留存。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import time
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import GuardianStore, PalaceStore, mark_guardian_account
from src.market import calendar_trading_day
from src.ops.application.guardian_tools import data_source, snapshot as build_monitor_snapshot
from src.ops.application.guardian_agent import decide
from src.ops.application.guardian_evidence import decision_context
from src.ops.application.guardian_risk import evaluate_risk_plans
from src.ops.application.guardian_risk_execution import risk_decision, risk_rejections, finish_risk_execution
from src.ops.application.guardian_config import get_config
from src.ops.application.guardian_context import reference_days, reference_target_day, strategy_sources, quant_reference_candidates, observe, premarket_plan_context
from src.ops.application.guardian_decision import TRADE_ACTIONS, render_digest, simulate, bind_execution_references
from src.ops.application.jobs.context import JobContext, JobError, JobSkipped, JobCancelled, JobTimedOut
from src.ops.application.guardian_quotes import executable_quote, validated_quotes, quote_error
from src.ops.application.guardian_contract import ExecutionTerms, execution_error
from src.ops.application.guardian_order_repair import repair_preflight
from src.ops.application.guardian_delivery import deliver_pending
from src.ops.application.guardian_cycle_notice import observation_changes, observation_notice, publish_cycle_report
from src.ops.application.guardian_notification import (
    load_notification_day, with_notification_facts, render_failure_notice,
)
from src.ops.application.guardian_outcome import execution_window, missed_orders, withdrawn_orders
from src.ops.application.guardian_opening_plans import (build_opening_plans, pending_opening_plans, opening_plan_updates, opening_notice, validate_opening_reviews)
from src.ops.application.notify_dispatch import dispatch_text
from src.ops.application.session_clock import session_clock
from src.ops.application.guardian_session import in_review_window, is_opening_review, review_slot, recover_finished_runs
from src.shared.paths import palace_db


def execute_guardian(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    started = time.monotonic()
    timings: dict[str, int] = {}
    store = context.ops_store
    if store is None:
        raise JobError("缺少运维库")
    cfg = get_config(store)
    if not cfg["enabled"]:
        raise JobSkipped("天才交易员未开启")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    try:
        if not calendar_trading_day(now.date().isoformat()):
            raise JobSkipped("交易所休市，静默跳过")
    except ValueError as exc:
        raise JobSkipped(str(exc)) from exc
    if not in_review_window(now):
        raise JobSkipped("非交易员研判窗口")
    slot = review_slot(now)
    with GuardianStore(context.palace_db) as ledger:
        recover_finished_runs(ledger, store)
        if not ledger.claim(slot, run_id=context.run_id or ''):
            raise JobSkipped("本轮已扫描或上一轮仍在运行")
        meta: dict[str, Any] = {}
        risk_events: list[dict[str, Any]] = []
        holding_quote_evidence: dict[str, Any] = {}
        holding_quote_attempts: list[dict[str, Any]] = []
        committed = False
        decision, original_decision = None, None
        fills, rejects, initial_rejects, withdrawn, deferred = [], [], [], [], []
        opening_plans_pending = []
        failure_stage = "holding_quotes"
        try:
            state = mark_guardian_account(ledger.state(), {}, now)
            opening_plans_pending = pending_opening_plans(ledger, now)
            risk_orders: list[dict[str, Any]] = []
            if state["positions"] and session_clock(now).phase == "regular":
                holding_codes = [p["code"] for p in state["positions"]]
                initial, pending = {}, holding_codes
                # 普通轮次最多重试两次瞬时缺价；开盘边界继续等待真实更新，共用原30秒预算。
                opening = (now.hour, now.minute) in {(9, 30), (13, 0)} and now.second < 30
                while pending:
                    context.check_cancelled()
                    if time.monotonic() >= started + 30:
                        break
                    requested = list(pending)
                    try:
                        batch = build_monitor_snapshot(pending, include_minute=False,
                            force_refresh=True, check_cancelled=context.check_cancelled, deadline=started + 30).quotes
                    except (JobCancelled, JobTimedOut):
                        raise
                    except (OSError, TimeoutError, ValueError) as exc:
                        error = f"{type(exc).__name__}: {str(exc).strip() or '实时取价失败'}"
                        batch = {code: {"code": code, "error": error} for code in pending}
                    initial.update({code: batch.get(code, {}) for code in pending})
                    checked = datetime.now(ZoneInfo("Asia/Shanghai"))
                    pending = [code for code in holding_codes if quote_error(code, initial.get(code, {}), checked)]
                    holding_quote_attempts.append({"checked_at": checked.isoformat(), "requested_codes": requested,
                                     "quotes": dict(initial),
                                     "unavailable_codes": list(pending)})
                    ledger.annotate(slot, {"holding_quote_attempts": holding_quote_attempts})
                    context.check_cancelled()
                    if (not pending or (not opening and len(holding_quote_attempts) >= 3)
                            or time.monotonic() + 1 >= started + 30):
                        break
                    time.sleep(1)
                    context.check_cancelled()
                context.check_cancelled()
                refreshed = datetime.now(ZoneInfo("Asia/Shanghai"))
                state = mark_guardian_account(state, validated_quotes(initial, refreshed), refreshed)
                state, risk_orders, risk_events = evaluate_risk_plans(state, initial, refreshed)
                holding_quote_evidence = {
                    code: {key: row.get(key) for key in (
                        "code", "price", "source", "trade_date", "trade_time", "error", "quote_attempts"
                    )} for code, row in initial.items() if isinstance(row, dict)
                }
                ledger.annotate(slot, {"holding_quote_evidence": holding_quote_evidence})
            timings["holding_quotes_ms"] = int((time.monotonic() - started) * 1000)
            failure_stage = "context"
            decision = risk_decision(risk_orders, risk_events)
            risk_only = decision is not None
            if decision is None:
                days = reference_days(reference_target_day(now))
                with PalaceStore(context.palace_db or palace_db()) as palace:
                    candidates = quant_reference_candidates(observe(palace, days, state, []))
                codes = [item["code"] for item in candidates]
                payload = {"as_of": now.isoformat(), "trading_days": days, "candidates": candidates,
                           "execution_deadline": (now + timedelta(seconds=300)).isoformat(),
                           "analysis_only": session_clock(now).phase != 'regular', "cadence_minutes": 5,
                           "review_phase": "opening_auction" if is_opening_review(now) else "intraday",
                           "pending_opening_plans": opening_plans_pending,
                           "reference_history_note": '' if len(days) >= 3 else '本地参考池历史不足三个交易日，可通过研究工具自主查询，不限制交易范围。',
                           "portfolio": state, "risk_events": risk_events, "account_units": "人民币现金账户，金额字段 *_cents 单位为分，quantity 为股。初始本金20万元。参考池不限制买卖范围，空池也可自主发现股票；清仓后可重新买入。",
                           "active_strategies": strategy_sources(store),
                           "recent_trades": ledger.trades(), "stock_performance": ledger.performance(),
                           "recent_runs": [{"status": run["status"], "slot": run["slot"], "body": run["result"].get("analysis"), "fills": run["result"].get("fills", []), "orders": run['result'].get('decisions', []), "rejects": run["result"].get("rejects", []), "deferred": run['result'].get('deferred', [])}
                                           for run in ledger.recent() if run["status"] != "running"]}
                premarket = ledger.report("premarket", now.date().isoformat())
                payload["preopen_plan"] = premarket_plan_context(premarket, state)
                from src.ops.application.guardian_context import review_memory_context
                payload["review_memory"] = review_memory_context(ledger.reports(10), state, now)
                payload["experience"] = ledger.experience(as_of=now.isoformat())['text']
            else:
                days, candidates, codes = [], [], []
            research_started = time.monotonic()
            failure_stage = "research"
            if decision is None:
                from src.ops.application.guardian_memory import MEMORY_NOTE
                payload['portfolio'] = deepcopy(payload['portfolio'])
                payload['recent_runs'] = deepcopy(payload['recent_runs'])
                payload['historical_material_note'] = MEMORY_NOTE
                ledger.annotate(slot, {"decision_context": decision_context(payload)})
                decision, meta = decide(store, cfg, payload, check_cancelled=context.check_cancelled, deadline=started + 270, palace_db_path=context.palace_db)
            else:
                meta = {"source": "saved_risk_plan"}
            timings["research_ms"] = int((time.monotonic() - research_started) * 1000)
            original_decision = decision.model_dump(mode="json")
            if not risk_only:
                validate_opening_reviews(decision, opening_plans_pending)
            failure_stage = "final_quotes"
            # 模型慢推理后重新取价；收盘/午休、停用或改配置后不得按旧意图成交。
            finished = datetime.now(ZoneInfo("Asia/Shanghai"))
            context.check_cancelled()
            if get_config(store) != cfg:
                raise ValueError("交易员设置已变更，本轮结果作废")
            can_execute = execution_window(now, finished, time.monotonic() - started)
            execution_codes = list(dict.fromkeys([p["code"] for p in state["positions"]] + [item.code for item in decision.orders if item.action in TRADE_ACTIONS]))
            quote_started = time.monotonic()
            quotes = build_monitor_snapshot(execution_codes, include_minute=False, force_refresh=True,
                check_cancelled=context.check_cancelled, deadline=started + 300, require_order_book=False).quotes if execution_codes and can_execute else {}
            context.check_cancelled()
            finished = datetime.now(ZoneInfo("Asia/Shanghai"))
            if get_config(store) != cfg:
                raise ValueError("取价后配置已变更，本轮未成交")
            can_execute = can_execute and execution_window(now, finished, time.monotonic() - started)
            decision = bind_execution_references(decision, quotes, finished)
            deferred = [o.model_dump() for o in decision.orders if o.action in TRADE_ACTIONS] if not can_execute else []
            executable = decision if can_execute else decision.model_copy(update={'orders':[o for o in decision.orders if o.action not in TRADE_ACTIONS]})
            if is_opening_review(now):
                executable = decision.model_copy(update={'orders': []})
            failure_stage = "preflight"
            updated, fills, rejects = simulate(state, executable, candidates, quotes, finished,
                                               require_execution_terms=True, risk_only=risk_only)
            initial_rejects, withdrawn = list(rejects), []
            if can_execute and rejects and not risk_only:
                failure_stage = "preflight_repair"
                corrected = repair_preflight(store, cfg, decision, meta, state, quotes, rejects,
                    check_cancelled=context.check_cancelled, deadline=started + 270)
                if corrected is not decision:
                    withdrawn = withdrawn_orders(decision, corrected, rejects)
                    decision = corrected
                    # 修正撤回竞价计划的关联订单是程序受阻（opening_plan_updates记blocked），不是整轮失败。
                    validate_opening_reviews(decision, opening_plans_pending, withdrawn_plan_ids={
                        item["opening_plan_id"] for item in withdrawn if item.get("opening_plan_id")})
                    failure_stage = "final_quotes"
                    execution_codes = list(dict.fromkeys([p["code"] for p in state["positions"]] + [o.code for o in decision.orders if o.action in TRADE_ACTIONS]))
                    quotes = build_monitor_snapshot(execution_codes, include_minute=False, force_refresh=True,
                        check_cancelled=context.check_cancelled, deadline=started + 300, require_order_book=False).quotes if execution_codes else {}
                    context.check_cancelled()
                    finished = datetime.now(ZoneInfo("Asia/Shanghai"))
                    can_execute = execution_window(now, finished, time.monotonic() - started)
                    # 已绑定的参考价由修正沿用；首次取价未能绑定的市价意图按本次首个有效报价绑定。
                    decision = bind_execution_references(decision, quotes, finished)
                    deferred = [o.model_dump(mode="json") for o in decision.orders if o.action in TRADE_ACTIONS] if not can_execute else []
                    executable = decision if can_execute else decision.model_copy(update={"orders": [o for o in decision.orders if o.action not in TRADE_ACTIONS]})
                    failure_stage = "preflight"
                    updated, fills, rejects = simulate(state, executable, candidates, quotes, finished, require_execution_terms=True)
            timings["execution_preflight_ms"] = int((time.monotonic() - quote_started) * 1000)
            saved_risk_events = risk_events
            if session_clock(now).phase == "regular":
                updated, saved_risk_events = finish_risk_execution(updated, risk_events, fills, quotes, finished)
            rejects.extend(risk_rejections(saved_risk_events))
            meta = {key: value for key, value in meta.items() if not key.startswith("_")}
            blocked = rejects + withdrawn + missed_orders(deferred, now)
            watch_changes = observation_changes(state, updated, finished.isoformat(), references=candidates)
            day_facts = load_notification_day(ledger, finished,
                market_factory=None if risk_only else context.market)
            notice_state = with_notification_facts(updated, day_facts, fills, slot=slot)
            body = render_digest(decision.summary, fills, blocked, notice_state)
            if watch_changes:
                body += "\n\n观察变更\n" + observation_notice(watch_changes)
            lifecycle = [event for event in saved_risk_events if event.get("status") in {"adjusted", "expired", "invalidated"}]
            if fills and lifecycle:
                body += "\n\n" + "\n".join(f"风险保护 · {event['code']}：{event['reason']}" for event in lifecycle)
            result = {"status": "success", "body": body, "analysis": decision.summary,
                      "review_phase": "opening_auction" if is_opening_review(now) else "intraday",
                      "opening_plans": build_opening_plans(decision, slot) if is_opening_review(now) else [],
                      "opening_plan_updates": opening_plan_updates(opening_plans_pending, decision, fills, rejects + withdrawn,
                          unavailable='本轮优先处理已触发风险合同，竞价计划留待下一轮复核' if risk_only else ''),
                      "decisions": [item.model_dump() for item in decision.orders], "fills": fills, "rejects": rejects,
                      "deferred": deferred, "analysis_only": not can_execute,
                      "initial_rejects": initial_rejects, "withdrawn": withdrawn, "blocked": blocked,
                      "outcome": ("partial_execution" if fills else "rejected") if blocked else ("traded" if fills else "observation_changed" if watch_changes else "no_action"),
                      "observation_changes": watch_changes,
                      "stock_names": {item['code']: item['name'] for item in watch_changes},
                      "original_decision": original_decision, "timings": timings,
                      "risk_events": saved_risk_events, "risk_only": risk_only,
                      "holding_quote_evidence": holding_quote_evidence,
                      "holding_quote_attempts": holding_quote_attempts,
                      "ledger_committed": True, "notification_facts": notice_state["notification_day"],
                      "observed": len(codes), "candidates": candidates, "trading_days": days,
                      "model": cfg["model"], "usage": meta, "as_of": finished.isoformat(),
                      "account_version": 2, "account": {k: v for k, v in updated.items() if k != "positions"}}
            try:
                result["data_source"] = data_source()
            except (ValueError, RuntimeError, OSError) as exc:
                result["data_source"] = {"label": "来源目录暂不可用", "error": str(exc),
                                         "execution_sources": sorted({f.get("quote_source", "") for f in fills})}
            if blocked:
                result.update(status="failed", error="存在未执行意图，详见拒单原因；已成交部分已独立核账。")
            notice = None
            if cfg["notify"] and (fills or blocked or watch_changes):
                title = "天才交易员 · 执行受阻" if blocked else "天才交易员 · 五分钟动作"
                notice = {"title": title, "body": result["body"]}
            elif cfg["notify"] and is_opening_review(now):
                notice = {"title": "天才交易员 · 09:25操作预案",
                          "body": opening_notice(decision, result['opening_plans'], now)}
            if notice:
                try:
                    share_url = publish_cycle_report(slot, result)
                    if share_url:
                        notice['body'] += f"\n\n查看本轮简报（免登录）：\n{share_url}"
                        result['share_url'] = share_url
                except Exception as exc:
                    result['share_error'] = str(exc)
            def commit_check() -> None:
                context.check_cancelled()
                if get_config(store) != cfg:
                    raise ValueError("交易员设置已变更，本轮未提交")
                current = datetime.now(ZoneInfo("Asia/Shanghai"))
                if fills and not execution_window(now, current, time.monotonic() - started):
                    raise ValueError("成交提交已超出交易时段或本轮有效期")
                for fill in fills:
                    executable_quote(fill["code"], fill["action"], fill["quantity"], quotes.get(fill["code"], {}), current, paper=True)
                    problem = quote_error(fill["code"], quotes.get(fill["code"], {}), current)
                    terms = ExecutionTerms.model_validate(fill["execution"])
                    _, price_problem = execution_error(terms, fill["price_cents"] / 100, current, required=True)
                    if problem or price_problem:
                        raise ValueError(problem or price_problem)
            failure_stage = "commit"
            with store.guardian_commit_guard(context.run_id or ""):
                ledger.finish(slot, result, updated, run_id=context.run_id or "", before_commit=commit_check, notice=notice)
            committed = True
        except JobSkipped:
            raise
        except Exception as exc:
            if committed:
                raise
            failed_at = datetime.now(ZoneInfo("Asia/Shanghai"))
            saved_state = ledger.state()
            try:
                saved_state = mark_guardian_account(saved_state, {}, failed_at)
            except (ValueError, KeyError, TypeError) as valuation_exc:
                saved_state = {**saved_state, "valuation_error": str(valuation_exc)}
            # Failed preflight fills were rolled back and must never enter daily totals.
            notice_state = with_notification_facts(saved_state,
                load_notification_day(ledger, failed_at), [], slot=slot)
            error_body = render_failure_notice(notice_state, exc, failure_stage)
            cancelled = isinstance(exc, JobCancelled)
            orders = decision.model_dump(mode="json")["orders"] if decision is not None else []
            blocked = [{**order, "reject_code": "cancelled" if cancelled else "execution_failed",
                        "reason": str(exc)} for order in orders if order["action"] in TRADE_ACTIONS]
            # fills 只表示已落账事实；回滚后的模拟结果只能作为独立的预检证据。
            result = {"status": "cancelled" if cancelled else "failed", "body": error_body, "error": str(exc),
                      "opening_plan_updates": opening_plan_updates(opening_plans_pending, unavailable=f"本轮未完成：{exc}；继续待核验"),
                      "failure_stage": failure_stage, "ledger_committed": False, "fills": [],
                      "notification_facts": notice_state["notification_day"],
                      "preflight_fills": fills, "decisions": orders, "original_decision": original_decision,
                      "analysis": decision.summary if decision is not None else "",
                      "initial_rejects": initial_rejects, "rejects": rejects,
                      "withdrawn": withdrawn, "deferred": deferred, "blocked": blocked + withdrawn,
                      "outcome": "cancelled" if cancelled else ("rejected" if blocked or rejects or withdrawn else "failed"),
                      "risk_events": risk_events,
                      "holding_quote_evidence": holding_quote_evidence,
                      "holding_quote_attempts": holding_quote_attempts,
                      "usage": {k: v for k, v in getattr(exc, "usage", meta).items() if not k.startswith("_")}, "timings": timings}
            notice = {"title": "天才交易员 · 异常", "body": error_body} if cfg["notify"] and not isinstance(exc, JobCancelled) else None
            try:
                ledger.finish(slot, result, run_id=context.run_id or "", notice=notice)
            except RuntimeError:
                pass  # A superseded owner must not overwrite the terminal cycle.
            if cfg["notify"]:
                try:
                    deliver_pending(ledger, store, dispatch_text)
                except Exception as delivery_exc:
                    result["delivery_error"] = str(delivery_exc)
                    try:
                        ledger.annotate(slot, {"delivery_error": str(delivery_exc)})
                    except Exception:
                        pass  # Preserve the original failure even if diagnostics cannot be saved.
            if isinstance(exc, (JobCancelled, JobTimedOut)):
                raise
            raise JobError(str(exc)) from exc
        try:
            receipts = deliver_pending(ledger, store, dispatch_text) if cfg["notify"] else {}
        except Exception as exc:
            receipts = {}
            result["delivery_error"] = str(exc)
            # Content is already durable; delivery failure does not change execution facts.
            try:
                ledger.annotate(slot, {"delivery_error": str(exc)})
            except Exception:
                pass
        if slot in receipts:
            result["notify"] = receipts[slot]
        elif notice:
            result["notify"] = {"success": False, "pending": True}
        else:
            receipt = {'success': False, 'skipped': 'no_action' if not fills and not blocked and not watch_changes else 'disabled'}
            ledger.notification(slot, receipt)
            result['notify'] = receipt
        return result
