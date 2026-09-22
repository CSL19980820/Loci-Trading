"""独立股票智能体运行器；所有成交由模拟账本执行，绝不连接券商。"""
from __future__ import annotations

import logging
import time
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
from src.ops.infrastructure.store import OpsStore
from src.shared.paths import palace_db
from src.shared.tenancy import current_tenant, tenant_scope

logger = logging.getLogger(__name__)


def phase_allowed(phase: str, now: datetime) -> bool:
    clock = now.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
    if phase == "intraday":
        return session_clock(now).phase == "regular" and clock < "14:57"
    if phase == "closeout":
        return session_clock(now).phase == "regular" and "14:50" <= clock < "14:57"
    if phase == "auction":
        return "09:25" <= clock < "09:30"
    if phase == "premarket":
        return "06:00" <= clock < "09:15"
    return phase == "review" and "15:00" <= clock <= "23:59"


def require_phase(phase: str, now: datetime) -> None:
    if phase not in PHASE_NAMES or not phase_allowed(phase, now):
        raise ValueError("当前不在所选工作阶段；竞价研判限09:25—09:30，盘前和盘后不模拟成交")
    if not calendar_trading_day(now.date().isoformat()):
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
        if phase != "review" or target > now.date() or (target == now.date() and now.hour < 15):
            raise ValueError("指定日期仅用于已收盘交易日的复盘，不回填历史成交")
        if not calendar_trading_day(target.isoformat()):
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
        payload = {"as_of": started.isoformat(), "phase": phase, "phase_name": PHASE_NAMES[phase],
                   "analysis_only": analysis_only, "portfolio": profile["state"],
                   "recent_work": recent, "research_plan": profile["state"].get("research_plan", ""),
                   "execution_deadline": (started + timedelta(seconds=budget)).isoformat(),
                   "independent_research": True, **scope}
        usage = {"model": "已保存的执行计划", "input_tokens": 0, "output_tokens": 0}
        if decision is None:
            decision, usage = decide_stock_agent(context.ops_store, profile, payload, palace_path=path,
                                                 checkpoint=checkpoint, deadline=deadline)
        checkpoint()
        codes = list(dict.fromkeys([p["code"] for p in profile["state"]["positions"]] + [o.code for o in decision.orders]))
        research_codes = leader_research_codes(profile["state"], config, phase)
        if research_codes is not None:
            codes = [code for code in codes if code in research_codes]
        quotes = snapshot(codes, force_refresh=True, check_cancelled=checkpoint, deadline=deadline,
                          require_order_book=True).quotes if codes and not analysis_only else {}
        now = agent_time()
        decision = bind_execution_references(decision, quotes, now)
        state, fills, rejects = simulate_stock_agent(profile["state"], decision, quotes, now, config,
                                                    analysis_only=analysis_only, phase=phase)
        plan = getattr(decision, "research_plan", None)
        if plan is not None:
            state.update(research_plan=plan, research_plan_date=scope["research_date"], research_plan_at=now.isoformat())
        from src.ops.application.guardian_risk_execution import finish_risk_execution
        state, risk_events = finish_risk_execution(state, risk_events, fills, quotes, now)
        # 以实际成交/接受观察标识动作；被拒绝的买单不能显示成“已买入”。
        rejected_codes = {(item.get("code"), item.get("action")) for item in rejects}
        actions = [{"code": order.code, "name": str(quotes.get(order.code, {}).get("name") or order.name),
                    "action": order.action, "quantity": order.quantity,
                    "status": "rejected" if (order.code, order.action) in rejected_codes else
                              ("filled" if any(f.get("code") == order.code and f.get("action") == order.action and f.get("quantity") == order.quantity for f in fills)
                               else "rejected" if order.action in TRADE_ACTIONS else "recorded")}
                   for order in decision.orders]
        result = {"summary": decision.summary, "phase": phase, "analysis_only": analysis_only, "risk_events": risk_events,
                  **scope, "research_plan": state.get("research_plan", ""), "workshop_access": False,
                  "actions": actions, "decisions": [o.model_dump(mode="json") for o in decision.orders],
                  "fills": fills, "rejects": rejects, "usage": usage,
                  "quotes": {code: {k: q.get(k) for k in ("name", "price", "trade_date", "trade_time", "source", "error", "order_book", "order_book_error")}
                             for code, q in quotes.items()}, "as_of": now.isoformat()}

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
