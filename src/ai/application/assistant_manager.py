"""全局助手的后台运行编排。断开 HTTP 客户端不会取消已提交运行。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
import os
from typing import Any

from src.ai import CryptoError, resolve_config
from src.ai.application.agent import ChatMessage, run_agent
from src.ai.application.system_toolbus import build_system_toolbus
from src.ai.domain.assistant import AssistantError, AssistantUnavailableError, assistant_system_prompt
from src.ai.infrastructure.assistant_store import AssistantStore
from src.ops import OpsError, OpsStore


DEFAULT_MONTHLY_TOKEN_BUDGET = 1_000_000


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
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ai-assistant")
        if self.ops_db:
            with AssistantStore(self.ops_db) as store:
                store.recover_interrupted_runs()

    def start_run(
        self, session_id: str, *, message: str, provider: str = "", model: str = ""
    ) -> str:
        prompt = message.strip()
        if not prompt:
            raise AssistantError("消息不能为空")
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
        except (OpsError, CryptoError) as exc:
            with AssistantStore(self.ops_db) as store:
                store.resolve_waiting_session(session_id)
                run_id = store.begin_run(session_id, user_message=prompt)
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
            store.resolve_waiting_session(session_id)
            run_id = store.begin_run(
                session_id,
                provider=config.name,
                model=config.model,
                user_message=prompt,
            )
            store.append_event(
                run_id,
                "start",
                {"session_id": session_id, "provider": config.name, "model": config.model},
            )
        try:
            self._pool.submit(self._run, run_id, session_id, prompt, config)
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

    def _run(self, run_id: str, session_id: str, prompt: str, config: Any) -> None:
        def event(payload: dict[str, Any]) -> None:
            with AssistantStore(self.ops_db) as store:
                store.append_event(run_id, str(payload.get("type") or "event"), payload)

        def issue(action: str, target: str, parameters: dict[str, Any]) -> dict[str, Any] | None:
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
            # 子 Agent 的自由文本只作为侧栏证据，不进入可写工具轮次的模型上下文。
            self._run_read_only_subagents(config, prompt, event)
            with AssistantStore(self.ops_db) as store:
                history = store.list_messages(session_id, limit=40)
            messages = [
                ChatMessage(role=str(item["role"]), content=str(item["content"]))
                for item in history
                if str(item.get("role")) in {"user", "assistant"}
            ]
            system = assistant_system_prompt()
            outcome = run_agent(
                config,
                system=system,
                user_prompt=prompt,
                messages=messages or None,
                tool_schemas=bus.schemas,
                tool_executor=bus.executor,
                on_event=event,
                emit_terminal_event=False,
                allow_hitl=True,
            )
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id) or {}
                cancelled = bool(run.get("cancel_requested"))
                if not cancelled:
                    store.append_message(
                        session_id,
                        role="assistant",
                        content=outcome.text,
                        metadata={"run_id": run_id, "stopped_reason": outcome.stopped_reason},
                    )

            def is_cancelled() -> bool:
                with AssistantStore(self.ops_db) as store:
                    current = store.get_run(run_id)
                    return bool(current and current.get("cancel_requested"))

            # HITL：先暂停给用户，再收口后台 Job，避免「等 Job 才出现等待条」。
            if outcome.stopped_reason == "waiting_user" and not cancelled:
                ask = outcome.pending_ask if isinstance(outcome.pending_ask, dict) else {}
                with AssistantStore(self.ops_db) as store:
                    store.pause_run_waiting_user(run_id, ask=ask)
                bus.wait_for_background_tasks(is_cancelled=is_cancelled)
                return

            # 后台 Job 已经向侧栏发出 subagent 事件；取消或超时后不无限占用 AI worker。
            background_complete = bus.wait_for_background_tasks(is_cancelled=is_cancelled)
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id) or {}
                cancelled = bool(run.get("cancel_requested"))
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
                store.finish_run(
                    run_id,
                    status="completed",
                    result={
                        "rounds": outcome.rounds,
                        "stopped_reason": outcome.stopped_reason,
                        "background_pending": not background_complete,
                    },
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                )
                # 非流式路径无 token 增量；done 必须带终稿，否则前端空气泡。
                final_text = str(outcome.text or "")
                store.append_event(
                    run_id,
                    "done",
                    {
                        "stopped_reason": outcome.stopped_reason,
                        "cancelled": False,
                        "text": final_text,
                        "content": final_text,
                    },
                )
        except Exception as exc:
            with AssistantStore(self.ops_db) as store:
                run = store.get_run(run_id) or {}
                if run.get("cancel_requested"):
                    store.finish_run(run_id, status="cancelled", result={"cancelled_during_failure": True})
                    store.append_event(run_id, "cancelled", {"cancelled": True})
                else:
                    error = f"{type(exc).__name__}: {exc}"
                    store.append_event(run_id, "error", {"message": error})
                    store.finish_run(run_id, status="failed", error=error)

    def _run_read_only_subagents(
        self, config: Any, prompt: str, event: Any,
    ) -> list[str]:
        specs = self._subagent_specs(prompt)
        if not specs:
            return []

        def run_one(agent_id: str, name: str, focus: str) -> str:
            event({"type": "subagent_start", "id": agent_id, "name": name, "progress": 5, "detail": "已启动"})

            def child_event(payload: dict[str, Any]) -> None:
                kind = str(payload.get("type") or "")
                if kind == "round_start":
                    event({"type": "subagent_progress", "id": agent_id, "name": name, "progress": 35, "detail": "正在整理证据"})
                elif kind == "tool_start":
                    event({"type": "subagent_progress", "id": agent_id, "name": name, "progress": 70, "detail": f"正在读取 {payload.get('name') or '数据'}"})

            try:
                bus = build_system_toolbus(
                    palace_db=self.palace_db,
                    market_db=self.market_db,
                    ops_db=self.ops_db,
                    protocol=config.protocol,
                    on_event=child_event,
                    read_only=True,
                )
                result = run_agent(
                    config,
                    system=(
                        "你是 Loci 的只读子 Agent。只能调用已给出的只读本机工具，"
                        "不得写入、不得使用网络、不得给出交易终裁。"
                    ),
                    user_prompt=f"任务：{focus}\n原始用户请求：{prompt}",
                    tool_schemas=bus.schemas,
                    tool_executor=bus.executor,
                    max_rounds=3,
                    max_tokens=1400,
                )
                text = (result.text or "未取得可用证据").strip()[:4000]
                event({"type": "subagent_end", "id": agent_id, "name": name, "ok": True, "progress": 100, "detail": text[:360]})
                return f"[{name}]\n{text}"
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                event({"type": "subagent_end", "id": agent_id, "name": name, "ok": False, "progress": 100, "detail": detail})
                return f"[{name}]\n子任务失败：{detail}"

        with ThreadPoolExecutor(max_workers=min(2, len(specs)), thread_name_prefix="ai-evidence") as pool:
            futures = [pool.submit(run_one, *spec) for spec in specs]
            return [future.result() for future in as_completed(futures)]

    @staticmethod
    def _subagent_specs(prompt: str) -> list[tuple[str, str, str]]:
        if any(token in prompt for token in ("潜龙", "候选", "精选", "选股")):
            return [
                ("candidate-evidence", "候选证据", "读取潜龙候选池，核对每只候选的既有裁决与证据缺口。"),
                ("market-evidence", "行情证据", "如原始请求含明确标的，读取本机日 K 并只汇报结构证据。"),
            ]
        if any(token in prompt for token in ("持仓", "买入", "卖出", "成交", "交割", "成本")):
            return [("ledger-evidence", "账本核对", "读取当前持仓和近期成交，核对可卖数量与成本口径。")]
        return []
