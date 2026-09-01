"""助手 run 的后台执行：worker 线程里从建工具面到收口落库的那一整段。

从 `assistant_manager` 拆出（原 708 行）。分工：留在 manager 的是「进池之前」——
校验、配额、建 run 行、`submit_with_tenant` 投递；本文件是「进池之后」，也就是
工作线程真正跑的那一段（证据子 Agent、压缩、主环、HITL 暂停、收口与标题/记忆）。

**租户**：全程只经宿主的 `self.ops_db` / `self.palace_db` 属性取库路径，它们每次
读取都按当前租户现解析（见 `AssistantManager.ops_db`）。worker 的 Context 由
`submit_with_tenant` 从提交线程复制而来，所以这里解析出来的就是发起用户那份库。
禁止把这些路径提升成实例属性或模块常量——那等于把库钉死在第一个租户上。
"""
from __future__ import annotations

import json
from typing import Any

from src.ai.application.agent import ChatMessage, apply_hitl_tool_result, run_agent
from src.ai.application.assistant_context_feed import (
    context_feed_payload,
    feed_messages_for_session,
)
from src.ai.application.assistant_evidence_agents import (
    format_evidence_briefs,
    run_evidence_agents,
)
from src.ai.application.assistant_memory import maybe_auto_consolidate_memory
from src.ai.application.assistant_prompt import build_assistant_system_prompt
from src.ai.application.assistant_rich_state import (
    events_after_latest_resume,
    fold_run_rich_metadata,
)
from src.ai.application.assistant_session_title import maybe_summarize_session_title
from src.ai.application.assistant_stream_buffer import StreamEventBuffer
from src.ai.application.context_compact import DEFAULT_CONTEXT_WINDOW, compact_feed_messages
from src.ai.application.context_usage import estimate_tokens
from src.ai.application.quota import record_llm_usage
from src.ai.application.system_toolbus import build_system_toolbus
from src.ai.infrastructure.assistant_store import AssistantStore


class AssistantRunExecutorMixin:
    """依赖宿主提供 `ops_db` / `palace_db` / `market_db` / `scheduler_reloader`。"""

    def _run(
        self,
        run_id: str,
        session_id: str,
        prompt: str,
        config: Any,
        thinking: str = "",
        skill_block: str = "",
        resume_hitl: bool = False,
    ) -> None:
        # 同 run 复用一条 ops 连接写事件，避免每次 flush 开库 + _init_schema。
        event_store = AssistantStore(self.ops_db)
        try:
            self._run_with_event_store(
                event_store,
                run_id=run_id,
                session_id=session_id,
                prompt=prompt,
                config=config,
                thinking=thinking,
                skill_block=skill_block,
                resume_hitl=resume_hitl,
            )
        finally:
            event_store.close()

    def _run_with_event_store(
        self,
        event_store: AssistantStore,
        *,
        run_id: str,
        session_id: str,
        prompt: str,
        config: Any,
        thinking: str,
        skill_block: str,
        resume_hitl: bool = False,
    ) -> None:
        def persist(event_type: str, payload: dict[str, Any]) -> None:
            event_store.append_event(run_id, event_type, payload)

        # token/think 内存批写；其它事件立即落库（SSE/轮询仍读持久化流）
        stream_buf = StreamEventBuffer(persist)

        def event(payload: dict[str, Any]) -> None:
            stream_buf.emit(payload)

        def issue(action: str, target: str, parameters: dict[str, Any]) -> dict[str, Any] | None:
            stream_buf.flush()
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id)
                if run is None or run["cancel_requested"]:
                    return None
                grant = store.issue_grant(session_id=session_id, run_id=run_id, user_message=prompt, action=action, target=target, parameters=parameters)
                store.append_event(run_id, "execution_grant", {"action": action, "target": target, "grant_id": grant["id"]})
                return grant

        def consume(grant_id: str, action: str, target: str, parameters: dict[str, Any]) -> str:
            with AssistantStore(self.ops_db) as store:
                return store.consume_grant(grant_id=grant_id, session_id=session_id, run_id=run_id, user_message=prompt, action=action, target=target, parameters=parameters)

        def complete(grant_id: str, result: dict[str, Any], status: str = "completed") -> None:
            with AssistantStore(self.ops_db) as store:
                store.complete_grant(grant_id, result, status=status)

        bus = build_system_toolbus(
            palace_db=self.palace_db,
            market_db=self.market_db,
            ops_db=self.ops_db,
            protocol=config.protocol,
            grant_issuer=issue,
            grant_consumer=consume,
            grant_completer=complete,
            on_event=event,
            scheduler_reloader=self.scheduler_reloader,
        )
        try:
            with AssistantStore(self.ops_db) as store:
                profile = store.get_profile()
                memories = store.list_memories() if profile.get("memory_enabled") else []
                run_row = store.get_run(run_id) or {}
                run_result = run_row.get("result") if isinstance(run_row.get("result"), dict) else {}

            resume_messages: list[ChatMessage] | None = None
            if resume_hitl:
                raw_messages = run_result.get("agent_messages")
                reply = str(run_result.get("hitl_reply") or prompt)
                if isinstance(raw_messages, list) and raw_messages:
                    resume_messages = apply_hitl_tool_result(raw_messages, reply)
                evidence_brief = ""
            else:
                # 角色化只读取证：侧栏 subagent_* + 截断 brief 注入主环 system（非终裁）。
                evidence_rows = run_evidence_agents(
                    config=config,
                    prompt=prompt,
                    palace_db=self.palace_db,
                    market_db=self.market_db,
                    ops_db=self.ops_db,
                    on_event=event,
                )
                evidence_brief = format_evidence_briefs(evidence_rows)
                with AssistantStore(self.ops_db) as store:
                    session_row = store.get_session(session_id) or {}
                    history = store.list_messages(session_id, limit=200)
                messages = feed_messages_for_session(session_row, history)
                resume_messages = messages or None

            system = build_assistant_system_prompt(profile=profile, memories=memories)
            if skill_block.strip():
                system = f"{system}\n\n{skill_block.strip()}"
            if evidence_brief:
                system = f"{system}\n\n{evidence_brief}"
            # 同 run HITL 续环用 agent 快照，不压；仅会话喂模历史超阈值才 compact
            if not resume_hitl and resume_messages:
                reserve = estimate_tokens(system)
                try:
                    reserve += estimate_tokens(json.dumps(bus.schemas or [], ensure_ascii=False))
                except (TypeError, ValueError):
                    pass
                window = int(getattr(config, "context_window", None) or DEFAULT_CONTEXT_WINDOW)
                compact = compact_feed_messages(
                    resume_messages,
                    context_window=window,
                    reserve_tokens=reserve,
                )
                if compact.compacted:
                    event(compact.event_payload())
                    resume_messages = compact.messages
                    # 同步写入 session 喂模快照，用量环与下次手动 /compact 共用
                    with AssistantStore(self.ops_db) as store:
                        session_row = store.get_session(session_id) or {}
                        hist = store.list_messages(session_id, limit=200)
                        through_seq = max((int(row.get("seq") or 0) for row in hist), default=0)
                        meta = dict(session_row.get("metadata") or {})
                        meta["context_feed"] = context_feed_payload(compact, through_seq=through_seq)
                        store.update_session(session_id, metadata=meta)
            outcome = run_agent(
                config,
                system=system,
                user_prompt=prompt or "请根据附图回答。",
                messages=resume_messages,
                tool_schemas=bus.schemas,
                tool_executor=bus.executor,
                on_event=event,
                emit_terminal_event=False,
                allow_hitl=True,
                thinking=thinking,
            )
            stream_buf.flush()
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id) or {}
                cancelled = bool(run.get("cancel_requested")) or str(run.get("status") or "") != "running"
                if not cancelled:
                    # 收口前折叠本 run 事件进 metadata，供 GET session 刷新复盘（ADR-006）
                    events = store.poll_events(run_id, limit=500)
                    # 同 run HITL 续跑：只 fold resume 之后，避免把暂停前 hitl 灌进续写气泡
                    if resume_hitl:
                        events = events_after_latest_resume(events)
                    rich = fold_run_rich_metadata(events)
                    ask_meta = (
                        outcome.pending_ask
                        if outcome.stopped_reason == "waiting_user"
                        and isinstance(outcome.pending_ask, dict)
                        else None
                    )
                    metadata: dict[str, Any] = {
                        "run_id": run_id,
                        "stopped_reason": outcome.stopped_reason,
                        **rich,
                    }
                    if ask_meta:
                        # 优先保留 fold 出的 hitl；否则用 pending_ask 兜底（刷新后仍能还原选项）
                        metadata["hitl"] = rich.get("hitl") if isinstance(rich.get("hitl"), dict) else ask_meta
                    # 原子：仅 running 未取消时写入，避免取消释放会话后迟到助手消息插到新 user 后
                    stored = store.append_assistant_if_run_active(
                        run_id,
                        session_id,
                        content=outcome.text,
                        metadata=metadata,
                    )
                    if stored is None:
                        cancelled = True

            def is_cancelled() -> bool:
                with AssistantStore(self.ops_db) as store:
                    current = store.get_run(run_id)
                    return bool(current and current.get("cancel_requested"))

            # HITL：先暂停给用户，再收口后台 Job，避免「等 Job 才出现等待条」。
            if outcome.stopped_reason == "waiting_user" and not cancelled:
                ask = outcome.pending_ask if isinstance(outcome.pending_ask, dict) else {}
                with AssistantStore(self.ops_db) as store:
                    current = store.get_run(run_id) or {}
                    if current.get("cancel_requested") or str(current.get("status") or "") != "running":
                        cancelled = True
                    else:
                        raw_msgs = getattr(outcome, "messages", None)
                        store.pause_run_waiting_user(
                            run_id,
                            ask=ask,
                            agent_messages=raw_msgs if isinstance(raw_msgs, list) else None,
                        )
                if not cancelled:
                    bus.wait_for_background_tasks(is_cancelled=is_cancelled)
                    stream_buf.flush()
                    return

            # 后台 Job 已经向侧栏发出 subagent 事件；取消或超时后不无限占用 AI worker。
            background_complete = bus.wait_for_background_tasks(is_cancelled=is_cancelled)
            stream_buf.flush()
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id) or {}
                cancelled = bool(run.get("cancel_requested")) or str(run.get("status") or "") == "cancelled"
                if cancelled:
                    record_llm_usage(
                        store=store,
                        provider=config.name,
                        model=outcome.model or config.model,
                        input_tokens=outcome.input_tokens,
                        output_tokens=outcome.output_tokens,
                    )
                    store.finish_run(
                        run_id,
                        status="cancelled",
                        result={
                            "rounds": outcome.rounds,
                            "stopped_reason": outcome.stopped_reason,
                            "background_pending": not background_complete,
                        },
                        input_tokens=outcome.input_tokens,
                        output_tokens=outcome.output_tokens,
                    )
                    store.append_event(run_id, "cancelled", {"stopped_reason": outcome.stopped_reason, "cancelled": True})
                    return

                record_llm_usage(
                    store=store,
                    provider=config.name,
                    model=outcome.model or config.model,
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                )
                reason = str(outcome.stopped_reason or "completed")
                # 工具后 LLM 失败 / 空终稿不应伪装成成功 completed
                failed = reason.startswith("llm_error") or reason == "empty_completion"
                store.finish_run(
                    run_id,
                    status="failed" if failed else "completed",
                    result={
                        "rounds": outcome.rounds,
                        "stopped_reason": reason,
                        "background_pending": not background_complete,
                    },
                    error=outcome.text if failed else "",
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                )
                # 若取消已抢先收口，finish_run 为 no-op，禁止再发 done / 标题
                current = store.get_run(run_id) or {}
                current_status = str(current.get("status") or "")
                if current_status == "cancelled":
                    return
                if failed:
                    if current_status != "failed":
                        return
                    store.append_event(
                        run_id,
                        "error",
                        {
                            "message": str(outcome.text or reason),
                            "stopped_reason": reason,
                        },
                    )
                    return
                if current_status != "completed":
                    return
                final_text = str(outcome.text or "")
                # done 必须先于标题 LLM：否则 SSE 见 completed 会提前关流，前端停在「正在整理回复…」
                store.append_event(
                    run_id,
                    "done",
                    {
                        "stopped_reason": reason,
                        "cancelled": False,
                        "text": final_text,
                        "content": final_text,
                    },
                )
            # 标题 / 记忆在 done 之后另开短连接，避免 LLM 占库拖死 SSE
            with AssistantStore(self.ops_db) as store:
                titled = maybe_summarize_session_title(
                    store,
                    session_id,
                    config,
                    user_message=prompt,
                    assistant_text=str(outcome.text or ""),
                )
                if titled:
                    store.append_event(run_id, "session_title", titled)
                consolidate = maybe_auto_consolidate_memory(
                    store, session_id=session_id, config=config
                )
                if consolidate.get("status") == "ok":
                    store.append_event(run_id, "memory_auto", consolidate)
        except Exception as exc:
            stream_buf.flush()
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id) or {}
                if run.get("cancel_requested"):
                    store.finish_run(run_id, status="cancelled", result={"cancelled_during_failure": True})
                    store.append_event(run_id, "cancelled", {"cancelled": True})
                else:
                    error = f"{type(exc).__name__}: {exc}"
                    store.append_event(run_id, "error", {"message": error})
                    store.finish_run(run_id, status="failed", error=error)
