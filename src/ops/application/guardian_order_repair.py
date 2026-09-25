"""One bounded preflight correction; never loosens a price limit or repeats a fill."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from src.ops.application.guardian_contract import completion_error
from src.ops.application.guardian_completion import run_accounted_agent
from src.ops.application.guardian_decision import GuardianDecision, TRADE_ACTIONS, parse_decision
from src.ops.application.guardian_research_context import evidence_snapshot


def validate_correction(original: GuardianDecision, corrected: GuardianDecision) -> None:
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
        prior = before.execution
        if prior is None:
            continue
        if datetime.fromisoformat(item.execution.valid_until) > datetime.fromisoformat(prior.valid_until):
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


def inherit_bound_terms(original: GuardianDecision, corrected: GuardianDecision) -> GuardianDecision:
    """沿用程序绑定到原意图上的参考价与竞价计划编号。

    修正轮模型通常照抄自己最初的输出——那时市价意图还没有 ``reference_price``
    （程序在首次有效报价时才绑定），也常漏掉 ``opening_plan_id``。原先
    ``validate_correction`` 会因“移动了参考价”把合法的缩量/撤回整体判失败，
    竞价计划关联丢失又会让整轮在复核校验处作废。只在模型省略时补回原值：
    参考价只会收窄执行范围，计划编号按原股票+方向一一对应，都不放宽任何约束。
    """
    old = {(o.code, o.action): o for o in original.orders if o.action in TRADE_ACTIONS}
    orders = []
    for item in corrected.orders:
        prior = old.get((item.code, item.action)) if item.action in TRADE_ACTIONS else None
        if prior is not None:
            update: dict = {"opening_plan_id": prior.opening_plan_id}
            if (item.execution is not None and prior.execution is not None
                    and item.execution.reference_price is None and prior.execution.reference_price is not None):
                update["execution"] = item.execution.model_copy(
                    update={"reference_price": prior.execution.reference_price})
            item = item.model_copy(update=update)
        orders.append(item)
    return corrected.model_copy(update={"orders": orders})


def repair_preflight(store: Any, cfg: dict, decision: GuardianDecision, meta: dict, state: dict,
                     quotes: dict, rejects: list[dict], *, check_cancelled: Any, deadline: float) -> GuardianDecision:
    allowed = {"quantity", "cash", "position_limit", "t_plus_one", "close_plan", "account_rule"}
    continuation = meta.get("_repair")
    if not continuation or not any(r.get("reject_code") in allowed for r in rejects):
        return decision
    if deadline - time.monotonic() < 20:
        meta["preflight_repair"] = {"status": "skipped", "reason": "剩余时间不足，保留拒单并等待下一轮"}
        return decision
    from src.ai import ChatMessage, resolve_config
    from src.ai.application.agent_messages import messages_from_json
    from src.ops.application.jobs.context import JobCancelled, JobTimedOut

    try:
        check_cancelled()
        provider = resolve_config(store, cfg["provider"], model=cfg["model"], timeout=max(0.001, deadline - time.monotonic()))
        if provider.model != cfg["model"]:
            raise ValueError("所选模型已停用")
        messages = messages_from_json(continuation["messages"])
        text = continuation.get("text") or decision.model_dump_json()
        if not messages or messages[-1].role != "assistant" or messages[-1].content != text:
            messages.append(ChatMessage(role="assistant", content=text))
        request = {"preflight_only": True, "portfolio": state, "quotes": quotes, "rejections": rejects,
                   "original_decision": decision.model_dump(mode="json"),
                   "instruction": "尚未发生任何成交。本次根据拒单原因自主降低股数或撤回不可执行意图；不得新增股票、重复或改变买卖方向，不得扩大股数、放宽价格边界或延长有效期。以自主选择的合法手数替代非法半手，不能由程序随意取整。输出完整决策JSON；本轮工具仍可用于补查、核算与预演，不必重复已完成研究。"}
        messages.append(ChatMessage(role="user", content=json.dumps(request, ensure_ascii=False)))
        result = run_accounted_agent(provider, store, meta, system=continuation["system"], messages=messages,
                           tool_schemas=continuation.get("tool_schemas"), tool_executor=continuation.get("tool_executor"),
                           max_rounds=None, max_calls_per_round=None, max_tool_result_chars=None,
                           max_parallel_tools=int(cfg.get("parallel_tools", 4)),
                           parallel_tool_names=continuation.get("parallel_tool_names", set()),
                           max_tokens=provider.max_output_tokens or 328000, temperature=0, thinking=cfg.get("thinking", ""),
                           deadline=deadline, check_cancelled=check_cancelled, allow_hitl=False)
        diagnostic = {"status": "failed", "finish_reason": result.finish_reason, "original_rejects": rejects}
        meta["preflight_repair"] = diagnostic
        error = completion_error(result, "订单修正")
        if error:
            raise ValueError(error)
        corrected = inherit_bound_terms(decision, parse_decision(result.text, require_execution_terms=True))
        validate_correction(decision, corrected)
        check_cancelled()
        diagnostic.update(status="corrected", decision=corrected.model_dump(mode="json"))
        # 修正只能缩量或撤回：竞价计划复核沿用原决策；0股交易即撤回，不留空单。
        return decision.model_copy(update={
            "summary": corrected.summary,
            "orders": [o for o in decision.orders if o.action not in TRADE_ACTIONS]
                      + [o for o in corrected.orders if o.action in TRADE_ACTIONS and o.quantity > 0]})
    except (JobCancelled, JobTimedOut, TimeoutError) as exc:
        exc.usage = meta
        raise
    except (ValueError, RuntimeError) as exc:
        meta.setdefault("preflight_repair", {}) .update(status="failed", error=str(exc))
        return decision
    except BaseException as exc:
        exc.usage = meta
        raise
    finally:
        if continuation.get("archive") is not None:
            meta.update(**evidence_snapshot(continuation["archive"]))
            meta["tool_calls"] = len(meta["tools"])
