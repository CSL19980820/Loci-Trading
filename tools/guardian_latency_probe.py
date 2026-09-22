"""Read-only production research timing probe; never calls settlement or notifications.

Run inside the configured application environment:
    python -m tools.guardian_latency_probe
It uses the selected provider and records its normal token usage. Output contains
timings and tool names, never credentials or model reasoning text.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def main() -> None:
    from src.ai.application import agent
    from src.ai.infrastructure import client_stream
    from src.ledger import GuardianStore, mark_guardian_account
    from src.ops.application import guardian_tools
    from src.ops.application.guardian_agent import decide
    from src.ops.application.guardian_config import get_config
    from src.ops.application.guardian_context import active_strategies, premarket_plan_context
    from src.ops.application.jobs.context import JobContext
    from src.ops.infrastructure.store import OpsStore
    from src.strategy import describe_all

    def emit(event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    profiles = []
    active = {}
    real_lines = client_stream._iter_sse_data_lines
    real_chat = agent.chat_stream
    real_tools = guardian_tools.agent_tools

    def lines(response):
        active["headers_ms"] = round((time.monotonic() - active["started"]) * 1000)
        emit({"event": "headers", "round": active["round"], "elapsed_ms": active["headers_ms"], "http_status": response.status_code})
        for payload in real_lines(response):
            active.setdefault("first_event_ms", round((time.monotonic() - active["started"]) * 1000))
            if payload != "[DONE]":
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    chunk = {}
                if chunk.get("usage"):
                    active["usage"] = chunk["usage"]
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    for field in ("content", "reasoning_content", "tool_calls"):
                        if delta.get(field):
                            active.setdefault("first_" + field + "_ms", round((time.monotonic() - active["started"]) * 1000))
            yield payload

    def chat(config, messages, **kwargs):
        active.clear()
        active.update(started=time.monotonic(), round=len(profiles) + 1,
                      request_timeout_seconds=config.timeout,
                      input_characters=len(kwargs.get("system", "")) + sum(len(m.content) for m in messages),
                      tool_schema_characters=len(json.dumps(kwargs.get("tools") or [], ensure_ascii=False)))
        emit({"event": "request", **{k: v for k, v in active.items() if k != "started"}})
        try:
            response = real_chat(config, messages, **kwargs)
            active.update(input_tokens=response.input_tokens, output_tokens=response.output_tokens,
                          requested_tools=[call.name for call in response.tool_calls])
            return response
        finally:
            active["total_ms"] = round((time.monotonic() - active["started"]) * 1000)
            profile = {k: v for k, v in active.items() if k != "started"}
            profiles.append(profile)
            emit({"event": "response", **profile})

    def readonly_tools(protocol, **kwargs):
        return real_tools(protocol, read_only=True, deadline=kwargs.get("deadline"))

    with OpsStore() as store, GuardianStore() as ledger:
        config = get_config(store)
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        recent = ledger.recent()
        last = next((r for r in recent if r["result"].get("decision_context")), None)
        if last is None:
            raise ValueError("No saved research context is available for the timing probe")
        candidates = last["result"]["decision_context"]["candidates"]
        state = mark_guardian_account(ledger.state(), {}, now)
        wanted = {s for row in candidates for s in row.get("strategies", [])}
        payload = {"as_of": now.isoformat(), "portfolio": state, "candidates": candidates,
            "preopen_plan": premarket_plan_context(ledger.report("premarket", now.date().isoformat()), state),
            "active_strategies": active_strategies(store),
            "strategy_rules": [s for s in describe_all() if s["slug"] in wanted],
            "trading_days": last["result"].get("trading_days", []),
            "recent_trades": ledger.trades(), "stock_performance": ledger.performance(),
            "recent_runs": [{"slot": r["slot"], "status": r["status"], "body": r["result"].get("analysis"),
                **{k: r["result"].get(k, []) for k in ("fills", "rejects", "deferred")},
                "orders": r["result"].get("decisions", [])} for r in recent if r["status"] != "running"],
            "analysis_only": True, "execution_deadline": (now + timedelta(seconds=300)).isoformat(),
            "cadence_minutes": 5,
            "validation_note": "只读性能验证；按正常研究深度核验现有持仓与机会，区分最新事实与历史材料。不提交交易、不通知。"}
        context = JobContext(ops_store=store, run_id="guardian-latency-readonly")
        client_stream._iter_sse_data_lines = lines
        agent.chat_stream = chat
        guardian_tools.agent_tools = readonly_tools
        started = time.monotonic()
        try:
            decision, usage = decide(store, config, payload, check_cancelled=context.check_cancelled,
                                     deadline=started + 270, palace_db_path=str(ledger.db_path))
            result = {"status": "success", "summary": decision.summary, "decisions": len(decision.orders)}
        except Exception as exc:
            usage = getattr(exc, "usage", {})
            result = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        finally:
            client_stream._iter_sse_data_lines = real_lines
            agent.chat_stream = real_chat
            guardian_tools.agent_tools = real_tools
        emit({"event": "result", **result, "elapsed_seconds": round(time.monotonic()-started, 3),
            "ledger_commit_called": False, "profiles": profiles,
            "usage": {k: usage.get(k) for k in ("model", "rounds", "tool_calls", "input_tokens", "output_tokens", "context_usage", "timeline")},
            "tools": [{**{k: t.get(k) for k in ("name", "ok", "elapsed_ms")},
                       "arguments": {k: v for k, v in (t.get("arguments") or {}).items()
                                     if k in {"codes", "ref", "path", "fields", "offset", "limit"}},
                       "result_characters": len(t.get("text", ""))}
                      for t in usage.get("tools", [])]})


if __name__ == "__main__":
    main()
