"""独立股票智能体运行器；所有成交由模拟账本执行，绝不连接券商。"""
from __future__ import annotations

import logging
import time
from copy import deepcopy
from datetime import date, datetime, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

from src.ledger import StockAgentStore, StockAgentConflict
from src.market import calendar_trading_day
from src.ops.application.guardian_decision import TRADE_ACTIONS, GuardianDecision, bind_execution_references
from src.ops.application.guardian_quotes import executable_quote, quote_error
from src.ops.application.guardian_contract import ExecutionTerms, execution_error
from src.ops.application.guardian_tools import snapshot
from src.ops.application.jobs.context import JobContext, JobSkipped, JobCancelled
from src.ops.application.session_clock import session_clock
from src.ops.application.stock_agent_policy import simulate_stock_agent, closing_stock_agent_decision, leader_research_codes
from src.ops.application.guardian_risk import evaluate_risk_plans
from src.ops.application.stock_agent_prompts import PHASE_NAMES
from src.ops.application.stock_agent_service import agent_time
from src.ops.application.falcon_watch_pool import reconcile_falcon_watch_pool, sync_falcon_watch_pools
from src.ops.infrastructure.store import OpsStore
from src.shared.paths import palace_db
from src.shared.tenancy import current_tenant, tenant_scope

logger = logging.getLogger(__name__)


def phase_allowed(phase: str, now: datetime) -> bool:
    clock = now.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
    if phase == "research":
        return True
    if phase == "intraday":
        return session_clock(now).phase == "regular" and clock < "14:57"
    if phase == "closeout":
        return session_clock(now).phase == "regular" and "14:50" <= clock < "14:57"
    if phase == "auction":
        return "09:25" <= clock < "09:30"
    if phase == "premarket":
        return "06:00" <= clock < "09:15"
    return phase in {"review", "weekly_review"} and "15:00" <= clock <= "23:59"


def require_phase(phase: str, now: datetime) -> None:
    if phase not in PHASE_NAMES or not phase_allowed(phase, now):
        raise ValueError("当前不在所选工作阶段；竞价研判限09:25—09:30，盘前和盘后不模拟成交")
    if phase not in {"research", "weekly_review"} and not calendar_trading_day(now.date().isoformat()):
        raise ValueError("交易所休市；保留记录，不生成虚构交易")


def execute_stock_agent(cfg: dict, context: JobContext) -> dict:
    now, path = agent_time(), str(context.palace_db or palace_db())
    phase = str(cfg.get("phase") or "intraday")
    try:
        require_phase(phase, now)
    except (ValueError, LookupError) as exc:
        raise JobSkipped(str(exc)) from exc
    with StockAgentStore(path) as ledger:
        profile = ledger.get(str(cfg.get("agent_id") or ""))
        if profile["config"].get("kind") == "falcon":
            sync_falcon_watch_pools(context.ops_store, path, as_of=now, agent_id=profile["id"])
            profile = ledger.get(profile["id"])
        if cfg.get("revision") != profile["revision"]:
            raise JobSkipped("旧日程已失效，等待新的智能体日程")
        minute = now.minute // profile["config"]["schedule"]["intraday_minutes"] * profile["config"]["schedule"]["intraday_minutes"]
        period = f"{now.hour:02d}:{minute:02d}" if phase == "intraday" else now.strftime("%H:%M") if phase == "closeout" else phase
        claimed = ledger.claim_run(profile["id"], f"{now.date().isoformat()}:{phase}:{period}", phase, now=now)
    if claimed is None:
        raise JobSkipped("智能体暂停、本轮已执行或同租户并发名额占用")
    return run_claimed(claimed, phase, context, path)


def research_scope(phase: str, now: datetime, research_date: str | None = None) -> dict:
    target = date.fromisoformat(research_date) if research_date else now.date()
    if research_date:
        if phase not in {"review", "weekly_review"} or target > now.date() or (target == now.date() and now.hour < 15):
            raise ValueError("指定日期仅用于已收盘交易日的复盘，不回填历史成交")
        if phase != "weekly_review" and not calendar_trading_day(target.isoformat()):
            raise ValueError("所选研究日期不是交易日")
    else:
        require_phase(phase, now)
    historical = target < now.date()
    cutoff = now.replace(year=target.year, month=target.month, day=target.day, hour=23, minute=59, second=59, microsecond=0) if historical else now
    daily_cutoff = target if historical or now.hour >= 15 else target - timedelta(days=1)
    return {"research_date": target.isoformat(), "historical_review": historical,
            "research_cutoff": cutoff.isoformat(), "market_history_cutoff": daily_cutoff.isoformat()}


def phase_budget(phase: str, now: datetime, configured: int) -> float:
    """墙钟是运维预算；竞价研究及时收束，让09:30轮能读取其最终计划。"""
    boundary = None
    if phase == "auction":
        boundary = now.replace(hour=9, minute=29, second=50, microsecond=0)
    elif phase in {"intraday", "closeout"}:
        boundary = now.replace(hour=11, minute=29, second=50, microsecond=0) if now.hour < 12 else now.replace(hour=14, minute=56, second=50, microsecond=0)
    return max(1, min(configured, (boundary-now).total_seconds())) if boundary else configured


def run_claimed(profile: dict, phase: str, context: JobContext, path: str, research_date: str | None = None) -> dict:
    from src.ops.application.stock_agent_decide import decide_stock_agent
    config, agent_id, run_id = profile["config"], profile["id"], profile["run_id"]
    started, tenant = agent_time(), current_tenant()
    budget = phase_budget(phase, started, config["timeout_seconds"])
    deadline = time.monotonic() + budget
    ops_path = str(context.ops_store.db_path)
    last_check, check_lock = [0.0], Lock()

    def deadline_check():
        if current_tenant() != tenant:
            raise StockAgentConflict("智能体运行租户不匹配")
        if time.monotonic() >= deadline:
            raise TimeoutError("本轮研究超时，未提交的交易不落账")
        if context.is_timed_out():
            raise TimeoutError("任务预算已耗尽")

    def checkpoint(*_args):
        deadline_check()
        # 模型并发工具线程不能复用主线程的SQLite连接。
        with check_lock:
            if time.monotonic() - last_check[0] < 0.5:
                return
            with StockAgentStore(path) as ledger:
                ledger.assert_owner(agent_id, run_id)
            if context.run_id:
                with OpsStore(ops_path) as ops:
                    record = ops.get_run(context.run_id)
                    if not record or record["status"] != "running" or record.get("cancel_requested"):
                        raise JobCancelled("任务已取消")
            last_check[0] = time.monotonic()

    committed = False
    try:
        scope = research_scope(phase, started, research_date)
        checkpoint()
        with StockAgentStore(path) as ledger:
            recent = ledger.history(agent_id, limit=12)["items"]
            review_evidence = {}
            if config["kind"] == "falcon" and phase in {"review", "weekly_review"}:
                from src.ops.application.falcon_review_evidence import falcon_review_evidence
                review_evidence = falcon_review_evidence(ledger, agent_id, phase, scope, checkpoint=deadline_check)
        candidate_scope = None
        learning_evidence = {}
        if config["kind"] == "falcon":
            from src.ops.application.falcon_candidates import load_falcon_candidates
            from src.ops.application.falcon_review_evidence import falcon_learning_evidence
            candidate_scope = load_falcon_candidates(path, context.ops_store, as_of=datetime.fromisoformat(scope["research_cutoff"]),
                                                     research_date=scope["research_date"], historical_review=scope["historical_review"])
            learning_evidence = falcon_learning_evidence(candidate_scope, review_evidence)
        analysis_only = phase not in {"intraday", "closeout"}
        decision = None
        risk_events = []
        if not analysis_only:
            held_codes = [p["code"] for p in profile["state"]["positions"]]
            held_quotes = snapshot(held_codes, force_refresh=True, check_cancelled=checkpoint, deadline=deadline).quotes if held_codes else {}
            profile["state"], risk_orders, risk_events = evaluate_risk_plans(profile["state"], held_quotes, agent_time())
            decision = closing_stock_agent_decision(profile["state"], agent_time(), config)
            if risk_orders and decision is None:
                decision = GuardianDecision.model_validate({"summary": "优先执行本账户已确认并触发的止损/止盈合同。", "orders": risk_orders})
        watch_quotes = {}
        watch_codes = list(dict.fromkeys(row["code"] for key in ("watchlist", "positions") for row in profile["state"].get(key, [])))
        allowed_research = leader_research_codes(profile["state"], config, phase)
        if allowed_research is not None:
            watch_codes = [code for code in watch_codes if code in allowed_research]
        if decision is None and watch_codes and not scope["historical_review"]:
            from src.ops.application.stock_agent_workbench import research_quotes, capture_observation_prices
            watch_quotes = research_quotes(watch_codes, force_refresh=True, now=agent_time(), checkpoint=checkpoint, deadline=deadline)
            profile["state"] = capture_observation_prices(profile["state"], quotes=watch_quotes, now=agent_time())
        payload = {"as_of": started.isoformat(), "phase": phase, "phase_name": PHASE_NAMES[phase],
                   "analysis_only": analysis_only, "portfolio": profile["state"],
                   "recent_work": recent, "research_plan": profile["state"].get("research_plan", ""),
                   "execution_deadline": (started + timedelta(seconds=budget)).isoformat(),
                   "independent_research": True,
                   "watch_snapshot": {"quotes": watch_quotes, "missing_codes": [code for code in watch_codes if not watch_quotes.get(code) or watch_quotes[code].get("error")]},
                   **scope}
        if candidate_scope is not None:
            from src.ops.application.falcon_learning import falcon_learning_context
            payload.update(candidate_scope=candidate_scope, review_evidence=review_evidence,
                           learning_evidence=learning_evidence,
                           learning=falcon_learning_context(profile["state"], agent_id=agent_id, research_date=scope["research_date"]))
            payload["portfolio"] = {key: value for key, value in profile["state"].items() if key != "falcon_learning"}
            if scope["historical_review"]:
                # 当前持仓、近期日记和计划包含研究日后的事实，不能供历史研判。
                payload["portfolio"] = {"positions": [], "watchlist": [], "historical_snapshot_available": False,
                                        "note": "未保存该历史时点的完整账户快照；仅按本窗口原始成交与决策研究，不用当前仓位代替历史仓位。"}
                payload["watch_snapshot"] = {"quotes": {}, "missing_codes": []}
                payload["recent_work"] = [{key: row.get(key) for key in (
                    "id", "phase", "started_at", "finished_at", "status", "summary", "actions")}
                    for row in review_evidence.get("runs", [])[:12]]
                payload["research_plan"] = next((row["research_plan"] for row in review_evidence.get("runs", [])
                                                 if row.get("research_plan")), "")
        usage = {"model": "已保存的执行计划", "input_tokens": 0, "output_tokens": 0}
        if decision is None:
            decision, usage = decide_stock_agent(context.ops_store, profile, payload, palace_path=path,
                                                 checkpoint=checkpoint, deadline=deadline)
        checkpoint()
        from src.ops.application.stock_agent_decision import StockAgentDecision
        from src.ops.application.agent_workbench_skill import normalize_stock_agent_research
        decision, research_metadata = normalize_stock_agent_research(
            StockAgentDecision.model_validate(decision.model_dump(mode="json")), payload, kind=config["kind"])
        for key, value in research_metadata.items():
            usage.setdefault(key, value)
        codes = list(dict.fromkeys([p["code"] for p in profile["state"]["positions"]] + [o.code for o in decision.orders]))
        research_codes = leader_research_codes(profile["state"], config, phase)
        if research_codes is not None:
            codes = [code for code in codes if code in research_codes]
        if candidate_scope is not None:
            permitted = set(candidate_scope["candidate_codes"]) | {p["code"] for p in profile["state"]["positions"]}
            codes = [code for code in codes if code in permitted]
        quotes = snapshot(codes, force_refresh=True, check_cancelled=checkpoint, deadline=deadline,
                          require_order_book=True).quotes if codes and not analysis_only else {}
        now = agent_time()
        decision = bind_execution_references(decision, quotes, now)
        state, fills, rejects = simulate_stock_agent(profile["state"], decision, quotes, now, config,
                                                    analysis_only=analysis_only, phase=phase,
                                                    **({"candidate_codes": candidate_scope["candidate_codes"],
                                                        "auto_observe_codes": candidate_scope.get("auto_observe_codes", [])}
                                                       if candidate_scope is not None else {}))
        if candidate_scope is not None and scope["historical_review"]:
            # 历史复盘保存研究日记，不把旧观察/旧计划写回今天的执行状态。
            state = deepcopy(profile["state"])
        plan = getattr(decision, "research_plan", None)
        if (plan is not None or decision.research_plan_structured is not None) and not (candidate_scope is not None and scope["historical_review"]):
            if plan is not None:
                state["research_plan"] = plan
            state.update(research_plan_date=scope["research_date"], research_plan_at=now.isoformat())
        learning_changes = []
        if candidate_scope is not None:
            from src.ops.application.falcon_learning import apply_falcon_learning
            evidence_ids = {row["evidence_id"] for key in ("candidates", "runs") for row in learning_evidence.get(key, [])}
            previous_learning = deepcopy(state.get("falcon_learning"))
            state = apply_falcon_learning(state, decision, phase, scope["research_date"], agent_id=agent_id,
                                          evidence_ids=evidence_ids,
                                          executed_trade_ids={row["evidence_id"] for row in learning_evidence.get("trades", [])})
            if state.get("falcon_learning") != previous_learning:
                learning_changes = (state.get("falcon_learning") or {}).get("last_changes", [])
                state["falcon_learning"].pop("last_changes", None)
        from src.ops.application.guardian_risk_execution import finish_risk_execution
        state, risk_events = finish_risk_execution(state, risk_events, fills, quotes, now)
        if candidate_scope is not None and not scope["historical_review"]:
            state, _ = reconcile_falcon_watch_pool(state, candidate_scope, as_of=now, agent_id=agent_id)
            pool_rejects = [row["code"] for row in rejects if row.get("reject_code") == "falcon_source_watch_pool"]
            if pool_rejects:
                decision = decision.model_copy(update={"summary": "来源观察池校验：" + "、".join(pool_rejects)
                    + "仍有有效公式产出，撤观察请求未执行。\n" + decision.summary})
        from src.ops.application.stock_agent_workbench import apply_workbench_research, valuation_snapshot
        if not scope["historical_review"]:
            state = apply_workbench_research(state, decision, quotes={**watch_quotes, **quotes}, now=now,
                                              coverage=usage.get("assessment_coverage"))
        # 以实际成交/接受观察标识动作；被拒绝的买单不能显示成“已买入”。
        rejected_codes = {(item.get("code"), item.get("action")) for item in rejects}
        actions = [{"code": order.code, "name": str(quotes.get(order.code, {}).get("name") or order.name),
                    "action": order.action, "quantity": order.quantity,
                    "status": "rejected" if (order.code, order.action) in rejected_codes else
                              ("filled" if any(f.get("code") == order.code and f.get("action") == order.action and f.get("quantity") == order.quantity for f in fills)
                               else "rejected" if order.action in TRADE_ACTIONS else "recorded")}
                   for order in decision.orders]
        result = {"summary": decision.summary, "phase": phase, "analysis_only": analysis_only, "risk_events": risk_events,
                  **scope, "research_plan": plan if plan is not None else state.get("research_plan", ""), "workshop_access": candidate_scope is not None,
                  "actions": actions, "decisions": [o.model_dump(mode="json") for o in decision.orders],
                  "fills": fills, "rejects": rejects, "usage": usage,
                  "assessments": [item.model_dump(mode="json") for item in decision.assessments],
                  "research_plan_structured": decision.research_plan_structured.model_dump(mode="json") if decision.research_plan_structured else None,
                  "detail": decision.detail.model_dump(mode="json") if decision.detail else None,
                  "assessment_coverage": usage.get("assessment_coverage"),
                  "valuation_snapshot": valuation_snapshot(state, now),
                  "learning_changes": learning_changes,
                  "watch_snapshot": {"as_of": started.isoformat(),
                      "quotes": {code: {key: value.get(key) for key in ("name", "price", "trade_date", "trade_time", "source", "error", "research_reference", "quote_received_at", "quote_age_seconds")}
                                 for code, value in payload["watch_snapshot"]["quotes"].items()},
                      "missing_codes": payload["watch_snapshot"]["missing_codes"]},
                  "quotes": {code: {k: q.get(k) for k in ("name", "price", "trade_date", "trade_time", "source", "error", "order_book", "order_book_error")}
                             for code, q in {**watch_quotes, **quotes}.items()}, "as_of": now.isoformat()}
        if candidate_scope is not None:
            result.update(candidate_scope=candidate_scope,
                          learning=decision.learning.model_dump(mode="json") if getattr(decision, "learning", None) is not None else None,
                          review_window={key: value for key, value in review_evidence.items() if key not in {"runs", "trades"}},
                          review_sample_counts={"runs": len(review_evidence.get("runs", [])), "trades": len(review_evidence.get("trades", []))})

        def final_check():
            deadline_check()
            current = agent_time()
            if current.date() != started.date():
                raise ValueError("跨交易日的旧意图不能提交")
            if fills:
                if analysis_only or not phase_allowed("intraday", current):
                    raise ValueError("成交前已离开连续交易时段")
                for fill in fills:
                    executable_quote(fill["code"], fill["action"], fill["quantity"], quotes.get(fill["code"], {}), current)
                    error = quote_error(fill["code"], quotes.get(fill["code"], {}), current)
                    if error:
                        raise ValueError(error)
                    _, error = execution_error(ExecutionTerms.model_validate(fill["execution"]),
                                               fill["price_cents"] / 100, current, required=True)
                    if error:
                        raise ValueError(error)
        with context.ops_store.guardian_commit_guard(context.run_id):
            with StockAgentStore(path) as ledger:
                if candidate_scope is not None and not scope["historical_review"]:
                    from src.ops.application.falcon_candidates import load_falcon_candidates
                    latest_scope = load_falcon_candidates(path, context.ops_store, as_of=agent_time())
                    ledger.update_falcon_watch_pool(agent_id, lambda current: reconcile_falcon_watch_pool(
                        current, latest_scope, as_of=now, agent_id=agent_id)[0], now=now)
                    state, _ = reconcile_falcon_watch_pool(state, latest_scope, as_of=now, agent_id=agent_id)
                    result["candidate_scope_at_commit"] = latest_scope
                ledger.finish_run(agent_id, run_id, state, result, before_commit=final_check)
        committed = True
        from src.ops.application.stock_agent_notify import notify_stock_agent
        try:
            notification = notify_stock_agent(context.ops_store, path, agent_id, run_id)
        except Exception as exc:
            logger.warning("智能体研究已保存，推送失败：%s", exc)
            notification = {"success": False, "errors": [str(exc)]}
        return {"status": "success", "agent_id": agent_id, "run_id": run_id, "ledger_committed": True,
                "summary": decision.summary[:800], "fills": len(fills), "rejects": len(rejects), "usage": usage,
                "notify": notification}
    except Exception as exc:
        if not committed:
            with StockAgentStore(path) as ledger:
                ledger.fail_run(agent_id, run_id, str(exc), cancelled=isinstance(exc, (JobCancelled, StockAgentConflict)))
        raise
    finally:
        try:
            with StockAgentStore(path) as ledger:
                ledger.prune_diary(agent_id)
        except Exception:
            logger.warning("智能体日记清理失败，财务提交不受影响", exc_info=True)


def run_manual(tenant: str, profile: dict, phase: str, path: str, research_date: str | None = None):
    with tenant_scope(tenant), OpsStore(None) as ops:
        try:
            run_claimed(profile, phase, JobContext(ops_store=ops, palace_db=path), path, research_date)
        except Exception:
            logger.warning("智能体手动运行未完成，失败原因已写入日记", exc_info=True)
