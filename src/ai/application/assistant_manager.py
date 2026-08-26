"""全局助手的后台运行编排。断开 HTTP 客户端不会取消已提交运行。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
import json
import os
from typing import Any

from src.ai import resolve_config
from src.ai.application.agent import ChatMessage, apply_hitl_tool_result, run_agent
from src.ai.application.assistant_evidence_agents import (
    format_evidence_briefs,
    run_evidence_agents,
)
from src.ai.application.assistant_images import images_from_metadata, normalize_user_images
from src.ai.application.assistant_memory import maybe_auto_consolidate_memory
from src.ai.application.assistant_prompt import build_assistant_system_prompt
from src.ai.application.assistant_rich_state import (
    events_after_latest_resume,
    fold_run_rich_metadata,
)
from src.ai.application.assistant_session_title import (
    maybe_apply_provisional_title,
    maybe_summarize_session_title,
)
from src.ai.application.assistant_skill_prompt import skill_prompt_block
from src.ai.application.assistant_stream_buffer import StreamEventBuffer
from src.ai.application.context_compact import DEFAULT_CONTEXT_WINDOW, compact_feed_messages
from src.ai.application.context_usage import estimate_tokens
from src.ai.application.system_toolbus import build_system_toolbus
from src.ai.domain.assistant import AssistantError, AssistantUnavailableError
from src.ai.infrastructure.assistant_store import AssistantStore
from src.ops import OpsError, OpsStore


DEFAULT_MONTHLY_TOKEN_BUDGET = 1_000_000
_THINKING_LEVELS = frozenset({"off", "low", "medium", "high", "xhigh", "max"})


def _normalize_run_thinking(value: str) -> str:
    """Map API thinking to client levels; empty/off means no reasoning_effort."""
    level = (value or "").strip().lower()
    if level in {"", "off", "none", "false", "0"}:
        return ""
    if level in _THINKING_LEVELS:
        return "" if level == "off" else level
    return ""


def _history_to_chat_messages(history: list[dict[str, Any]]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for item in history:
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "")
        images = images_from_metadata(
            item.get("metadata") if isinstance(item.get("metadata"), dict) else None
        )
        if role == "assistant" and not content.strip() and not images:
            continue
        messages.append(ChatMessage(role=role, content=content, images=images))
    for msg in messages:
        if msg.role == "user" and msg.images and msg.content.strip() == "（附图）":
            msg.content = ""
    return messages


def _feed_messages_for_session(
    session_row: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[ChatMessage]:
    """优先用手动/上次压缩写入的 context_feed，再拼 through_seq 之后的新消息。"""
    meta = session_row.get("metadata") if isinstance(session_row.get("metadata"), dict) else {}
    feed = meta.get("context_feed") if isinstance(meta, dict) else None
    if not isinstance(feed, dict):
        return _history_to_chat_messages(history)
    raw_rows = feed.get("messages")
    if not isinstance(raw_rows, list) or not raw_rows:
        return _history_to_chat_messages(history)
    base: list[ChatMessage] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        base.append(ChatMessage(role=role, content=str(row.get("content") or "")))
    through_seq = int(feed.get("through_seq") or 0)
    newer = [row for row in history if int(row.get("seq") or 0) > through_seq]
    if not newer:
        return base
    return [*base, *_history_to_chat_messages(newer)]


def _resolve_monthly_token_budget(value: int | None) -> int:
    raw = value if value is not None else os.getenv(
        "LOCI_AI_MONTHLY_TOKEN_BUDGET", str(DEFAULT_MONTHLY_TOKEN_BUDGET)
    )
    try:
        budget = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("LOCI_AI_MONTHLY_TOKEN_BUDGET 必须是正整数") from exc
    if budget < 1:
        raise ValueError("LOCI_AI_MONTHLY_TOKEN_BUDGET 必须是正整数")
    return budget


def _resolve_monthly_assistant_run_quota(value: int | None = None) -> int:
    """0 = 不限制；正整数为自然月助手 run 硬顶。"""
    raw = value if value is not None else os.getenv("LOCI_AI_ASSISTANT_RUN_MONTHLY_QUOTA", "0")
    try:
        quota = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("LOCI_AI_ASSISTANT_RUN_MONTHLY_QUOTA 必须是非负整数") from exc
    if quota < 0:
        raise ValueError("LOCI_AI_ASSISTANT_RUN_MONTHLY_QUOTA 必须是非负整数")
    return quota


class AssistantManager:
    """进程内有限线程池；每个 worker 自建 SQLite 连接，避免跨线程连接复用。"""

    def __init__(
        self, *, ops_db: str | None, palace_db: str | None = None, market_db: str | None = None,
        max_workers: int = 2, scheduler_reloader: Callable[[], None] | None = None,
        monthly_token_budget: int | None = None,
    ) -> None:
        self.ops_db, self.palace_db, self.market_db = ops_db, palace_db, market_db
        self.scheduler_reloader = scheduler_reloader
        self.monthly_token_budget = _resolve_monthly_token_budget(monthly_token_budget)
        self.monthly_assistant_run_quota = _resolve_monthly_assistant_run_quota()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ai-assistant")
        if self.ops_db:
            with AssistantStore(self.ops_db) as store:
                store.recover_interrupted_runs()

    def compact_session(self, session_id: str) -> dict[str, Any]:
        """手动 /compact：强制压缩喂模快照写入 session.metadata.context_feed（不删库原文）。"""
        with AssistantStore(self.ops_db) as store:
            session = store.get_session(session_id)
            if session is None or session["status"] == "archived":
                raise AssistantError("AI 会话不存在或已归档")
            if str(session.get("status") or "") in {"running", "waiting_user"}:
                raise AssistantError("会话占用中，请先结束或取消本轮再压缩")
            history = store.list_messages(session_id, limit=200)
            through_seq = max((int(row.get("seq") or 0) for row in history), default=0)
            messages = _history_to_chat_messages(history)
            if len(messages) < 2:
                raise AssistantError("对话太短，无需压缩")
            compact = compact_feed_messages(messages, force=True)
            if not compact.compacted:
                # force 仍可能因单轮无法切分而走 few_turns；若仍未压则回报
                raise AssistantError("当前上下文无法进一步压缩")
            meta = dict(session.get("metadata") or {})
            meta["context_feed"] = {
                "messages": [
                    {"role": msg.role, "content": str(msg.content or "")}
                    for msg in compact.messages
                ],
                "through_seq": through_seq,
                "tokens_before": compact.tokens_before,
                "tokens_after": compact.tokens_after,
                "message": compact.event_payload().get("message"),
                "method": compact.method,
            }
            store.update_session(session_id, metadata=meta)
            return {
                "compacted": True,
                "tokens_before": compact.tokens_before,
                "tokens_after": compact.tokens_after,
                "removed": compact.removed_count,
                "kept": compact.kept_count,
                "method": compact.method,
                "message": str(compact.event_payload().get("message") or ""),
            }

    def start_run(
        self,
        session_id: str,
        *,
        message: str,
        provider: str = "",
        model: str = "",
        thinking: str = "",
        images: list[str] | None = None,
        skill_slug: str = "",
    ) -> str:
        prompt = message.strip()
        attached = normalize_user_images(images)
        if not prompt and not attached:
            raise AssistantError("消息不能为空")
        thinking_level = _normalize_run_thinking(thinking)
        skill = str(skill_slug or "").strip()
        skill_block = skill_prompt_block(skill) if skill else ""
        user_meta = {"images": attached} if attached else None
        if skill:
            user_meta = {**(user_meta or {}), "skill_slug": skill}
        title_seed = prompt or "附图提问"
        with AssistantStore(self.ops_db) as store:
            session = store.get_session(session_id)
            if session is None or session["status"] == "archived":
                raise AssistantError("AI 会话不存在或已归档")
        try:
            with OpsStore(self.ops_db) as ops:
                config = resolve_config(
                    ops,
                    provider or str(session.get("provider") or ""),
                    model=model or str(session.get("model") or ""),
                )
        except OpsError as exc:
            with AssistantStore(self.ops_db) as store:
                session_now = store.get_session(session_id)
                if session_now and session_now.get("status") == "waiting_user":
                    run_id = store.resume_waiting_run(
                        session_id, user_message=prompt, metadata=user_meta
                    )
                else:
                    run_id = store.begin_run(
                        session_id, user_message=prompt, metadata=user_meta
                    )
                store.append_event(run_id, "error", {"message": f"LLM provider 不可用：{exc}"})
                store.finish_run(run_id, status="failed", error=f"LLM provider 不可用：{exc}")
            raise AssistantError(f"LLM provider 不可用：{exc}") from exc
        with AssistantStore(self.ops_db) as store:
            used_tokens = store.monthly_token_usage()
            if used_tokens >= self.monthly_token_budget:
                raise AssistantError(
                    "本月 Token 预算已用尽"
                    f"（{used_tokens} / {self.monthly_token_budget}），请下月再试或提高 LOCI_AI_MONTHLY_TOKEN_BUDGET"
                )
            if self.monthly_assistant_run_quota > 0:
                used_runs = store.monthly_assistant_run_count()
                if used_runs >= self.monthly_assistant_run_quota:
                    raise AssistantError(
                        "本月助手运行次数已达上限"
                        f"（{used_runs} / {self.monthly_assistant_run_quota}），"
                        "请下月再试或提高 LOCI_AI_ASSISTANT_RUN_MONTHLY_QUOTA"
                    )
            session_now = store.get_session(session_id) or {}
            resume_hitl = str(session_now.get("status") or "") == "waiting_user"
            if resume_hitl:
                run_id = store.resume_waiting_run(
                    session_id, user_message=prompt, metadata=user_meta
                )
                store.append_event(
                    run_id,
                    "resume",
                    {
                        "session_id": session_id,
                        "provider": config.name,
                        "model": config.model,
                        "thinking": thinking_level or "off",
                        "hitl": True,
                    },
                )
            else:
                run_id = store.begin_run(
                    session_id,
                    provider=config.name,
                    model=config.model,
                    user_message=prompt,
                    metadata=user_meta,
                )
                store.append_event(
                    run_id,
                    "start",
                    {
                        "session_id": session_id,
                        "provider": config.name,
                        "model": config.model,
                        "thinking": thinking_level or "off",
                        "image_count": len(attached),
                    },
                )
                titled = maybe_apply_provisional_title(store, session_id, title_seed)
                if titled:
                    store.append_event(run_id, "session_title", titled)
        try:
            self._pool.submit(
                self._run,
                run_id,
                session_id,
                prompt,
                config,
                thinking_level,
                skill_block,
                resume_hitl,
            )
        except Exception as exc:
            error = f"AI 后台运行启动失败：{type(exc).__name__}: {exc}"
            with AssistantStore(self.ops_db) as store:
                store.append_event(run_id, "error", {"message": error})
                store.finish_run(run_id, status="failed", error=error)
            raise AssistantUnavailableError(error) from exc
        return run_id

    def cancel_run(self, run_id: str) -> bool:
        """只接受显式取消；客户端关闭不会调用此方法。"""
        with AssistantStore(self.ops_db) as store:
            return store.cancel_run(run_id)

    def close(self) -> None:
        """不取消已提交的未来任务，进程退出策略由组合根决定。"""
        self._pool.shutdown(wait=False, cancel_futures=False)

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
                messages = _feed_messages_for_session(session_row, history)
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
                        meta["context_feed"] = {
                            "messages": [
                                {"role": msg.role, "content": str(msg.content or "")}
                                for msg in compact.messages
                            ],
                            "through_seq": through_seq,
                            "tokens_before": compact.tokens_before,
                            "tokens_after": compact.tokens_after,
                            "message": compact.event_payload().get("message"),
                            "method": compact.method,
                        }
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
                    store.record_usage(
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

                store.record_usage(
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
