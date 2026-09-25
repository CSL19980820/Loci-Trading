"""Complete, metered decisions and bounded output repair using existing evidence."""
from __future__ import annotations

import json
import time
from typing import Any

from src.ops.application.guardian_contract import completion_error
from src.ops.application.guardian_decision import GuardianDecision, OrderPolicyError, parse_decision
from src.ops.application.guardian_research_context import evidence_snapshot
from src.ops.application.guardian_output import JSON_OUTPUT_RULES, failed_response


def _record_agent_call(provider: Any, store: Any, usage: dict, delta: dict) -> None:
    from src.ai import record_llm_usage

    for key in ("input_tokens", "output_tokens", "rounds", "tool_calls"):
        usage[key] = usage.get(key, 0) + delta.get(key, 0)
    usage["model"] = delta.get("model") or provider.model
    record_llm_usage(provider=provider.name, model=usage["model"],
                     input_tokens=delta.get("input_tokens", 0), output_tokens=delta.get("output_tokens", 0),
                     ops_db=str(store.db_path))


def run_accounted_agent(provider: Any, store: Any, usage: dict, **arguments: Any) -> Any:
    """Bill this invocation's delta, then expose the full guardian usage on failure."""
    from src.ai.application.agent import run_agent

    try:
        result = run_agent(provider, **arguments)
    except BaseException as exc:
        partial = getattr(exc, "usage", {})
        _record_agent_call(provider, store, usage, partial if isinstance(partial, dict) else {})
        exc.usage = usage
        raise
    _record_agent_call(provider, store, usage, {
        "model": result.model, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "rounds": result.rounds, "tool_calls": len(result.invocations),
    })
    return result


def complete_decision(provider: Any, store: Any, *, system: str, payload: dict, schemas: list,
                      execute: Any, archive: Any, checkpoint: Any, deadline: float, config: dict,
                      decision_parser: Any = parse_decision,
                      available_tool_names: list[str] | None = None) -> tuple[GuardianDecision, dict]:
    from src.ai import ChatMessage
    from src.ai.application.agent_messages import messages_from_json

    started = time.monotonic()
    usage = {"model": provider.model, "input_tokens": 0, "output_tokens": 0, "rounds": 0,
             "tool_calls": 0, "attempts": [], "thinking_requested": config.get("thinking") or "provider_default",
             "context_window": provider.context_window, "max_output_tokens": provider.max_output_tokens}
    timeline: list[dict] = []
    first_delta = False

    def event(payload: dict) -> None:
        nonlocal first_delta
        checkpoint(payload)
        kind = payload.get("type")
        if kind == "round_start":
            first_delta = False
            timeline.append({"event": kind, "round": payload.get("round"),
                             "elapsed_ms": int((time.monotonic() - started) * 1000),
                             "tool_schema_characters": len(json.dumps(arguments.get("tool_schemas") or [], ensure_ascii=False))})
        elif kind in {"think", "token"} and not first_delta:
            first_delta = True
            timeline.append({"event": "first_response", "elapsed_ms": int((time.monotonic() - started) * 1000)})
        elif kind == "model_retry":
            timeline.append({"event": kind, "attempt": payload.get("attempt"),
                             "reason": payload.get("reason"), "transport_error": payload.get("transport_error"),
                             "elapsed_ms": int((time.monotonic() - started) * 1000)})
        elif kind == "stream_status":
            timeline.append({"event": kind, "phase": payload.get("phase"),
                             "request_elapsed_ms": payload.get("request_elapsed_ms"),
                             "kind": payload.get("kind"), "status_code": payload.get("status_code"),
                             "elapsed_ms": int((time.monotonic() - started) * 1000)})

    usage["timeline"] = timeline
    safe_names = {"market_overview", "cls_news", "short_term_emotion", "kline", "minute_data",
                  "guardian_context_read", "guardian_account_read", "guardian_calculate",
                  "guardian_decision_history", "guardian_quote_refresh"}
    from src.ops.application.guardian_research_tools import PARALLEL_RESEARCH_TOOLS
    safe_names |= PARALLEL_RESEARCH_TOOLS
    names = available_tool_names or [(s.get("function") or s).get("name", "") for s in schemas]
    parallel = {name for name in names if name.split("__")[-1] in safe_names}
    system += '\n' + JSON_OUTPUT_RULES
    arguments = dict(system=system, user_prompt=json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
                     tool_schemas=schemas, tool_executor=execute,
                     max_rounds=None, max_calls_per_round=None,
                     max_tokens=provider.max_output_tokens or 328000, max_tool_result_chars=None,
                     temperature=0.2, thinking=config.get("thinking", ""), allow_hitl=False,
                     on_event=event, check_cancelled=checkpoint, deadline=deadline,
                     retry_stream_failures=True,
                     recover_interrupted_generation=True,
                     max_parallel_tools=int(config.get("parallel_tools", 4)), parallel_tool_names=parallel)
    def accepted(decision: GuardianDecision, result: Any) -> tuple[GuardianDecision, dict]:
        usage.update(raw=result.text, elapsed_ms=int((time.monotonic() - started) * 1000),
                     **evidence_snapshot(archive),
                     _repair={"messages": result.messages, "system": system, "text": result.text,
                              "tool_schemas": schemas, "tool_executor": execute, "archive": archive,
                              "parallel_tool_names": parallel})
        return decision, usage

    # 首轮完整、合契约但个别订单越权时的原决策；修复不成功就退回它，只拒越权订单。
    policy_fallback: tuple[GuardianDecision, Any] | None = None
    try:
        for attempt in range(2):
            checkpoint()
            result = run_accounted_agent(provider, store, usage, **arguments)
            diagnostic = {"finish_reason": result.finish_reason, "stopped_reason": result.stopped_reason,
                          "output_characters": len(result.text), "input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
            usage["attempts"].append(diagnostic)
            try:
                error = completion_error(result)
                if error:
                    raise ValueError(error)
                decision = decision_parser(result.text, require_execution_terms=True)
                return accepted(decision, result)
            except ValueError as exc:
                diagnostic["error"] = str(exc)[:1500]
                failed_response(diagnostic, result.text)
                if attempt and isinstance(exc, OrderPolicyError):
                    # 修复后仍越权：不再整轮作废（那会连同止损卖单一起丢掉），
                    # 越权订单交给撮合预检按 board_not_allowed 拒绝并保持可见。
                    diagnostic["accepted_with_policy_rejects"] = True
                    return accepted(exc.decision, result)
                if attempt and policy_fallback is not None:
                    diagnostic["fallback"] = "policy_rejected_original"
                    return accepted(*policy_fallback)
                if attempt or result.stopped_reason != "completed" or result.finish_reason not in {"", "stop", "end_turn", "length", "max_tokens"}:
                    raise
                if isinstance(exc, OrderPolicyError):
                    policy_fallback = (exc.decision, result)
                    # 旧提示“保留原判断、方向、数量”与“撤回越权买入”互相矛盾，模型往往原样重交。
                    instruction = (f"账户权限校验未通过：{diagnostic['error']}。仅撤回或替换这些不可买入/加仓的意图："
                                   "可改为watch记录，或在沪深主板/创业板范围内自主选择替代标的并按需用工具重新核验；"
                                   "其余订单的判断、方向、数量及条件保持不变。输出完整合法决策JSON，不拼接残片。")
                else:
                    instruction = (f"上次完整性/JSON契约校验失败：{diagnostic['error']}。修复格式时保留原判断、方向、数量及条件，不因重新输出而另换一套决策；若证据或执行校验要求改变意图，明确说明原因。基于已取得事实输出完整合法决策，不拼接残片。仍可按需调用本轮全部工具补查证据，不必重复已完成研究。买卖必须明确execution：原意图缺少时按原判断补全价格授权与有效期；只有你判断条件确实不成立或无法确认时才改为hold/watch，并在reason说明。")
                messages = messages_from_json(result.messages)
                if not messages:
                    messages = [ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False, default=str))]
                if messages[-1].role != "assistant" or messages[-1].content != result.text:
                    messages.append(ChatMessage(role="assistant", content=result.text))
                messages.append(ChatMessage(role="user", content=instruction))
                arguments = {key: value for key, value in arguments.items() if key != "user_prompt"}
                arguments.update(messages=messages, temperature=0)
    except BaseException as exc:
        usage.update(**evidence_snapshot(archive), elapsed_ms=int((time.monotonic() - started) * 1000))
        usage["tool_calls"] = len(usage["tools"])
        exc.usage = usage
        raise
    raise AssertionError("Decision completion did not terminate")
