"""全局助手的后台运行编排。断开 HTTP 客户端不会取消已提交运行。

本文件只留「进池之前」的编排：会话校验、provider 解析、配额、建 run 行、投递。
worker 线程里真正跑的那一段在 `assistant_run_executor.AssistantRunExecutorMixin`
（`_run` / `_run_with_event_store`）；喂模历史与 `context_feed` 快照的读写在
`assistant_context_feed.py`。三者共用同一套惰性库路径属性，见 `ops_db`。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
import os
from typing import Any

from src.ai import resolve_config
from src.ai.application.assistant_context_feed import (
    context_feed_payload,
    history_to_chat_messages,
)
from src.ai.application.assistant_images import normalize_user_images
from src.ai.application.assistant_run_executor import AssistantRunExecutorMixin
from src.ai.application.assistant_session_title import maybe_apply_provisional_title
from src.ai.application.assistant_skill_prompt import skill_prompt_block
from src.ai.application.context_compact import compact_feed_messages
from src.ai.application.quota import (
    QuotaExceeded,
    check_llm_quota,
    current_llm_quota,
    env_llm_quota,
)
from src.ai.domain.assistant import AssistantError, AssistantUnavailableError
from src.ai.infrastructure.assistant_store import AssistantStore
from src.ai.infrastructure.tenant_db import ops_db_for, palace_db_for
from src.ops import OpsError, OpsStore
from src.shared.tenancy import submit_with_tenant


_THINKING_LEVELS = frozenset({"off", "low", "medium", "high", "xhigh", "max"})


def _normalize_run_thinking(value: str) -> str:
    """Map API thinking to client levels; empty/off means no reasoning_effort."""
    level = (value or "").strip().lower()
    if level in {"", "off", "none", "false", "0"}:
        return ""
    if level in _THINKING_LEVELS:
        return "" if level == "off" else level
    return ""


def _resolve_monthly_token_budget(value: int | None) -> int:
    """显式传入的月度 Token 硬顶。

    只服务「调用方自己钉死预算」这一种情况（测试、单机固定额度）。没显式传就
    不该走这里——每用户配额在 ``application/quota.current_llm_quota()``，
    环境变量只是它拿不到身份库时的兜底。
    """
    raw = value if value is not None else env_llm_quota()["llm_monthly_tokens"]
    try:
        budget = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("月度 Token 预算必须是正整数") from exc
    if budget < 1:
        raise ValueError("月度 Token 预算必须是正整数")
    return budget


WORKERS_ENV = "LOCI_AI_ASSISTANT_WORKERS"
DEFAULT_WORKERS = 4


def _resolve_workers(value: int | None = None) -> int:
    """助手后台并发数（全进程、跨租户共用）。

    原先写死 2：两个慢回答（或此前取消后仍在跑的 run）就能让所有用户的新消息排队，
    界面上一直“运行中”却没有任何输出。运行是 I/O 等待为主，默认 4，可用环境变量调整；
    非法值回落默认，范围 1–32。
    """
    raw: Any = value if value is not None else os.getenv(WORKERS_ENV, "")
    try:
        workers = int(raw) if str(raw).strip() else DEFAULT_WORKERS
    except (TypeError, ValueError):
        return DEFAULT_WORKERS
    return min(32, max(1, workers))


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


class AssistantManager(AssistantRunExecutorMixin):
    """进程内有限线程池；每个 worker 自建 SQLite 连接，避免跨线程连接复用。"""

    def __init__(
        self, *, ops_db: str | None, palace_db: str | None = None, market_db: str | None = None,
        max_workers: int | None = None, scheduler_reloader: Callable[[], None] | None = None,
        monthly_token_budget: int | None = None,
    ) -> None:
        # 只留「显式覆盖」。None = 随当前租户惰性解析（见 ops_db / palace_db 属性）。
        # 这个 manager 是 build_assistant_router 里 new 出来的**进程内单例**：构造期
        # 把路径解析成字符串存下来，等于让所有用户共用装配那一刻那个租户的库。
        self._ops_db_override = ops_db
        self._palace_db_override = palace_db
        self.market_db = market_db
        self.scheduler_reloader = scheduler_reloader
        # 同理：预算不能在构造期定死。显式传值仍然优先（测试 / 单机固定额度）。
        self._monthly_token_budget_override = (
            _resolve_monthly_token_budget(monthly_token_budget)
            if monthly_token_budget is not None
            else None
        )
        self.monthly_assistant_run_quota = _resolve_monthly_assistant_run_quota()
        # 池子本身是进程内共享的，**工作线程的 Context 是线程创建那一刻的快照**，
        # 与提交任务的那个请求毫无关系。所以任何投递都必须经 submit_with_tenant，
        # 见 start_run 里那段注释——直接 self._pool.submit(...) 会让 self.ops_db
        # 在线程内解析成主租户的库。
        self._pool = ThreadPoolExecutor(max_workers=_resolve_workers(max_workers), thread_name_prefix="ai-assistant")
        # 已经收口过遗留 running 的库。key 是**解析后的库路径**（已含租户），
        # 不是租户 id：单机钉库与多租户共用同一套判断。
        self._recovered: set[str] = set()
        self._recover_interrupted_once()

    def _recover_interrupted_once(self) -> None:
        """当前租户的库第一次被本进程用到时，把跨进程续不了的 running 收成失败。

        原来只在构造期做一次，等于只救得了装配那一刻的那个租户；别人的中断 run
        会永远挂在 running 上，那个会话再也发不出下一轮。
        """
        path = self.ops_db
        if path in self._recovered:
            return
        self._recovered.add(path)
        with AssistantStore(path) as store:
            store.recover_interrupted_runs()

    @property
    def ops_db(self) -> str:
        """当前租户的 ops.db。**每次读取都重新解析**，绝不缓存。"""
        return ops_db_for(self._ops_db_override)

    @property
    def palace_db(self) -> str:
        """当前租户的 palace.db；账本工具面要用，PalaceStore 不接受 None。"""
        return palace_db_for(self._palace_db_override)

    @property
    def monthly_token_budget(self) -> int:
        """本次调用生效的月度 Token 硬顶：显式覆盖 > 每用户配额 > 环境变量。"""
        if self._monthly_token_budget_override is not None:
            return self._monthly_token_budget_override
        return current_llm_quota()["llm_monthly_tokens"]

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
            messages = history_to_chat_messages(history)
            if len(messages) < 2:
                raise AssistantError("对话太短，无需压缩")
            compact = compact_feed_messages(messages, force=True)
            if not compact.compacted:
                # force 仍可能因单轮无法切分而走 few_turns；若仍未压则回报
                raise AssistantError("当前上下文无法进一步压缩")
            meta = dict(session.get("metadata") or {})
            meta["context_feed"] = context_feed_payload(compact, through_seq=through_seq)
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
        self._recover_interrupted_once()
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
            # 配额按**人**判，不再按进程。显式钉了预算的调用方（测试 / 单机固定额度）
            # 只走那一条硬顶；否则交给 quota 模块，它同时管月度 Token 与日调用次数，
            # 并在身份库不可用时自动退回环境变量。
            if self._monthly_token_budget_override is not None:
                used_tokens = store.monthly_token_usage()
                budget = self._monthly_token_budget_override
                if used_tokens >= budget:
                    raise AssistantError(
                        "本月 Token 预算已用尽"
                        f"（{used_tokens} / {budget}），请下月再试或提高该额度"
                    )
            else:
                try:
                    check_llm_quota(ops_db=self.ops_db)
                except QuotaExceeded as exc:
                    raise AssistantError(str(exc)) from exc
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
            # **不要改回 self._pool.submit(self._run, ...)。**
            # 上面那条 run 行是在**请求线程**里建的，用的是发起用户的 ops.db；
            # 而 ThreadPoolExecutor 的工作线程不继承 ContextVar，裸 submit 之后
            # `self.ops_db`（每次读取现解析）在 worker 里会落回主租户的老 data/。
            # 后果不是报错而是静默错库：`_run` 开头的 store.get_run(run_id) 在主
            # 租户库里查不到这条 run，直接 return，于是**会话永久卡在 running**、
            # 用户再也发不出下一轮，日志里一行红都没有。
            submit_with_tenant(
                self._pool,
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
