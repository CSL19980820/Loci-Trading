"""Return blocked trade intents to the model before any settlement is committed."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from src.ops.application.guardian_contract import completion_error
from src.ops.application.guardian_completion import run_accounted_agent
from src.ops.application.guardian_decision import GuardianDecision, TRADE_ACTIONS, parse_decision
from src.ops.application.guardian_research_context import evidence_snapshot


def validate_correction(original: GuardianDecision, corrected: GuardianDecision, *,
                        renewal_keys: set[tuple[str, str]] | None = None,
                        execution_deadline: datetime | None = None) -> None:
    renewal_keys = renewal_keys or set()
    if execution_deadline is not None and (execution_deadline.tzinfo is None or execution_deadline.utcoffset() is None):
        raise ValueError("本轮执行截止时间必须包含时区")
    old = {(o.code, o.action): o for o in original.orders if o.action in TRADE_ACTIONS}
    trades = [o for o in original.orders if o.action in TRADE_ACTIONS]
    if len(old) != len(trades):
        raise ValueError("重复交易意图不能自动修正")
    seen = set()
    for item in corrected.orders:
        if item.action not in TRADE_ACTIONS:
            continue
        key = (item.code, item.action)
        if key not in old or key in seen:
            raise ValueError("修正不得新增股票、改变方向或重复原意图")
        seen.add(key)
        before = old[key]
        if item.quantity > before.quantity:
            raise ValueError("修正不得扩大原申报数量")
        if item.execution is None:
            raise ValueError("修正仍需明确execution")
        expiry = datetime.fromisoformat(item.execution.valid_until)
        if execution_deadline is not None and expiry > execution_deadline:
            raise ValueError("修正有效期不得晚于本轮执行截止时间")
        prior = before.execution
        if key in renewal_keys:
            if item.quantity and item.execution.kind == "market" and item.execution.reference_price is None:
                raise ValueError("重新授权市价意图必须明确新的执行参考价")
            if prior is not None and execution_deadline is None and expiry > datetime.fromisoformat(prior.valid_until):
                raise ValueError("修正不得延长原意图有效期")
            continue
        if prior is None:
            continue
        if expiry > datetime.fromisoformat(prior.valid_until):
            raise ValueError("修正不得延长原意图有效期")
        if item.execution.reference_price != prior.reference_price:
            raise ValueError("修正不得移动已绑定的执行参考价")
        if prior.kind == "limit":
            if item.execution.kind != "limit":
                raise ValueError("修正不得将条件单变为市价意图")
            if prior.min_price is not None and (item.execution.min_price is None or item.execution.min_price < prior.min_price):
                raise ValueError("修正不得降低原价格下限")
            if prior.max_price is not None and (item.execution.max_price is None or item.execution.max_price > prior.max_price):
                raise ValueError("修正不得提高原价格上限")


def inherit_bound_terms(original: GuardianDecision, corrected: GuardianDecision, *,
                        renewal_keys: set[tuple[str, str]] | None = None) -> GuardianDecision:
    """沿用程序绑定到原意图上的参考价与竞价计划编号。

    修正轮模型通常照抄自己最初的输出——那时市价意图还没有 ``reference_price``
    （程序在首次有效报价时才绑定），也常漏掉 ``opening_plan_id``。原先
    ``validate_correction`` 会因“移动了参考价”把合法的缩量/撤回整体判失败，
    竞价计划关联丢失又会让整轮在复核校验处作废。只在模型省略时补回原值：
    参考价只会收窄执行范围，计划编号按原股票+方向一一对应。价格受阻或过期后
    允许模型重新授权的意图不补参考价，必须由模型显式给出。
    """
    old = {(o.code, o.action): o for o in original.orders if o.action in TRADE_ACTIONS}
    renewal_keys = renewal_keys or set()
    orders = []
    for item in corrected.orders:
        prior = old.get((item.code, item.action)) if item.action in TRADE_ACTIONS else None
        if prior is not None:
            update: dict = {"opening_plan_id": prior.opening_plan_id}
            if (item.execution is not None and prior.execution is not None
                    and item.execution.reference_price is None and prior.execution.reference_price is not None
                    and (item.code, item.action) not in renewal_keys):
                update["execution"] = item.execution.model_copy(
                    update={"reference_price": prior.execution.reference_price})
            item = item.model_copy(update=update)
        orders.append(item)
    return corrected.model_copy(update={"orders": orders})


def repair_preflight(store: Any, cfg: dict, decision: GuardianDecision, meta: dict, state: dict,
                     quotes: dict, rejects: list[dict], *, check_cancelled: Any, deadline: float,
                     execution_deadline: datetime | None = None, retry_payload: dict | None = None,
                     preflight_fills: list | None = None) -> GuardianDecision:
    allowed = {"quantity", "cash", "position_limit", "t_plus_one", "close_plan", "account_rule",
               "price_condition", "quote_unavailable", "liquidity_unconfirmed", "intent_expired",
               "risk_plan", "board_not_allowed"}
    rejected_keys = {(r.get("code"), r.get("action")) for r in rejects if r.get("reject_code") in allowed}
    blocked = decision.model_copy(update={
        "orders": [o for o in decision.orders if o.action in TRADE_ACTIONS and (o.code, o.action) in rejected_keys]})
    continuation = meta.get("_repair")
    if not blocked.orders or (not continuation and retry_payload is None):
        return decision
    rejected_keys = {(o.code, o.action) for o in blocked.orders}
    failures = [r for r in rejects if (r.get("code"), r.get("action")) in rejected_keys]
    renewal_keys = {(r.get("code"), r.get("action")) for r in failures
                    if r.get("reject_code") in {"price_condition", "intent_expired"}}
    previous_repair_error = meta.get("preflight_repair", {}).get("error")
    diagnostic = {"status": "failed", "original_rejects": failures}
    meta.setdefault("preflight_repair_attempts", []).append(diagnostic)
    meta["preflight_repair"] = diagnostic
    if deadline - time.monotonic() < 20:
        diagnostic.update(status="skipped", reason="剩余时间不足，保留拒单并等待下一轮")
        return decision
    from src.ai import ChatMessage, resolve_config
    from src.ai.application.agent_messages import messages_from_json
    from src.ops.application.jobs.context import JobCancelled, JobTimedOut

    prior_tools = list(meta.get("tools", []))
    prior_documents = dict(meta.get("context_documents", {}))
    if continuation and continuation.get("archive") is not None:
        archived_count = len(evidence_snapshot(continuation["archive"])["tools"])
        prior_tools = prior_tools[:-archived_count] if archived_count else prior_tools
    request = {"preflight_only": True, "retry_only": True, "ledger_committed": False,
               "portfolio": state, "quotes": quotes,
               "rejections": failures, "preflight_fills": preflight_fills or [],
               "original_decision": blocked.model_dump(mode="json"),
               "renewal_keys": [{"code": code, "action": action} for code, action in sorted(renewal_keys)],
               "instruction": ("尚未发生本轮任何落账；preflight_fills仅为预检通过结果，不是已成交。"
                   "只重新研判original_decision.orders中受阻的交易，可补查新鲜行情、修正、缩量或撤回。"
                   "程序保留其余预检通过交易和全部原非交易意图，禁止在输出中重复、修改它们。"
                   "不得新增股票、重复或改变买卖方向，不得扩大各原意图股数；不能由程序随意取整。"
                   "仅renewal_keys中的价格受阻或过期意图可由你明确重新授权价格及有效期："
                   "接受当前报价的market必须显式给出reference_price，limit必须给出明确价格边界；"
                   "这属于基于新证据的新授权，不沿用旧参考价叠加容差，程序不会替你移动参考价。"
                   "其他拒单仍保留原参考价、价格边界和有效期，不得放宽。"
                   "任何新有效期不得晚于本轮execution_deadline。"
                   "无法满足账户权限、资金、T+1或风险规则时自行缩量或撤回，不能绕过保护。"
                   "输出完整GuardianDecision JSON，但orders只包含这些受阻交易；撤回可省略或quantity=0。"
                   "本轮工具仍可用于补查、核算与预演，不必重复已完成研究。")}
    if execution_deadline is not None:
        request["execution_deadline"] = execution_deadline.isoformat()
    if previous_repair_error:
        request["previous_repair_error"] = previous_repair_error
    if retry_payload and "preflight_portfolio" in retry_payload:
        request["preflight_portfolio"] = retry_payload["preflight_portfolio"]

    def merge_usage(delta: dict) -> None:
        for key, value in delta.items():
            if key in {"input_tokens", "output_tokens", "rounds", "tool_calls", "elapsed_ms"}:
                meta[key] = meta.get(key, 0) + value
            elif key in {"tools", "attempts", "timeline"}:
                meta.setdefault(key, []).extend(value)
            elif key == "context_documents":
                meta.setdefault(key, {}).update(value)
            elif key not in {"preflight_repair", "preflight_repair_attempts"}:
                meta[key] = value

    try:
        check_cancelled()
        if continuation:
            provider = resolve_config(store, cfg["provider"], model=cfg["model"], timeout=max(0.001, deadline - time.monotonic()))
            if provider.model != cfg["model"]:
                raise ValueError("所选模型已停用")
            messages = messages_from_json(continuation["messages"])
            text = continuation.get("text") or decision.model_dump_json()
            if not messages or messages[-1].role != "assistant" or messages[-1].content != text:
                messages.append(ChatMessage(role="assistant", content=text))
            messages.append(ChatMessage(role="user", content=json.dumps(request, ensure_ascii=False)))
            result = run_accounted_agent(provider, store, meta, system=continuation["system"], messages=messages,
                               tool_schemas=continuation.get("tool_schemas"), tool_executor=continuation.get("tool_executor"),
                               max_rounds=None, max_calls_per_round=None, max_tool_result_chars=None,
                               max_parallel_tools=int(cfg.get("parallel_tools", 4)),
                               parallel_tool_names=continuation.get("parallel_tool_names", set()),
                               max_tokens=provider.max_output_tokens or 328000, temperature=0, thinking=cfg.get("thinking", ""),
                               deadline=deadline, check_cancelled=check_cancelled, allow_hitl=False)
            diagnostic["finish_reason"] = result.finish_reason
            error = completion_error(result, "订单修正")
            if error:
                raise ValueError(error)
            corrected = parse_decision(result.text, require_execution_terms=True)
            continuation.update(messages=result.messages, text=result.text)
        else:
            from src.ops.application.guardian_agent import decide
            payload = {**retry_payload, **request}
            try:
                corrected, usage = decide(store, cfg, payload, check_cancelled=check_cancelled, deadline=deadline,
                                          palace_db_path=retry_payload.get("palace_db_path"))
            except BaseException as exc:
                partial = getattr(exc, "usage", {})
                if isinstance(partial, dict):
                    merge_usage(partial)
                raise
            merge_usage(usage)
            continuation = meta.get("_repair")
        if any(o.action not in TRADE_ACTIONS for o in corrected.orders):
            raise ValueError("修正orders只能包含受阻交易，原非交易意图由程序保留")
        if retry_payload and retry_payload.get("risk_only") and any(o.risk_plans is not None for o in corrected.orders):
            raise ValueError("风险执行修正不得安装或撤回原持仓风险合同")
        corrected = inherit_bound_terms(blocked, corrected, renewal_keys=renewal_keys)
        validate_correction(blocked, corrected, renewal_keys=renewal_keys, execution_deadline=execution_deadline)
        check_cancelled()
        diagnostic.update(status="corrected", decision=corrected.model_dump(mode="json"))
        replacements = {(o.code, o.action): o for o in corrected.orders if o.quantity > 0}
        orders = []
        for item in decision.orders:
            key = (item.code, item.action)
            if item.action not in TRADE_ACTIONS or key not in rejected_keys:
                orders.append(item)
            elif key in replacements:
                orders.append(replacements[key])
        # 保留未受阻交易、非交易意图及竞价复核；只替换或撤回受阻意图。
        return decision.model_copy(update={
            "summary": corrected.summary, "orders": orders})
    except (JobCancelled, JobTimedOut, TimeoutError) as exc:
        exc.usage = meta
        raise
    except (ValueError, RuntimeError) as exc:
        diagnostic.update(status="failed", error=str(exc))
        return decision
    except BaseException as exc:
        exc.usage = meta
        raise
    finally:
        if continuation and continuation.get("archive") is not None:
            snapshot = evidence_snapshot(continuation["archive"])
            snapshot["tools"] = prior_tools + snapshot["tools"]
            snapshot["context_documents"] = {**prior_documents, **snapshot["context_documents"]}
            meta.update(**snapshot)
            meta["tool_calls"] = len(meta["tools"])
