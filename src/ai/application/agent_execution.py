"""按模型请求顺序执行工具；仅显式白名单内的独立只读工具可并发。"""
from __future__ import annotations

import time
from asyncio import CancelledError as AsyncCancelledError
from collections.abc import Callable, Collection
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from src.ai.infrastructure.client import ToolCall
from src.shared.tenancy import submit_with_tenant

ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]
NOT_EXECUTED_PREFIX = "TOOL_NOT_EXECUTED: "


@dataclass
class ToolInvocation:
    """一次工具请求的痕迹；拒绝执行的请求同样保留 ID。"""

    name: str
    arguments: dict[str, Any]
    ok: bool
    result_preview: str
    error: str = ""
    elapsed_ms: int = 0
    tool_call_id: str = ""
    executed: bool = True


@dataclass
class ToolOutcome:
    call: ToolCall
    text: str
    failed: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    executed: bool = True

    def invocation(self) -> ToolInvocation:
        return ToolInvocation(
            name=self.call.name, arguments=self.call.arguments, ok=not self.failed,
            result_preview=self.text[:600], error=self.text[:600] if self.failed else "",
            elapsed_ms=self.elapsed_ms, tool_call_id=self.call.id, executed=self.executed,
        )


def not_executed(call: ToolCall, reason: str) -> ToolOutcome:
    return ToolOutcome(
        call=call, text=f"{NOT_EXECUTED_PREFIX}工具未执行：{reason}",
        failed=True, executed=False,
    )


def reraise_stop(error: BaseException) -> None:
    """客户端会包装回调异常，沿显式原因链还原协作式终止。"""
    from src.ops import JobCancelled, JobTimedOut

    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, (TimeoutError, CancelledError, AsyncCancelledError,
                              JobCancelled, JobTimedOut)):
            raise cause
        seen.add(id(cause))
        cause = cause.__cause__


def _invoke(call: ToolCall, executor: ToolExecutor, aborted: Event) -> ToolOutcome:
    if aborted.is_set():
        raise CancelledError("Agent 工具批次已取消")
    started = time.monotonic()
    try:
        outcome = executor(call.name, call.arguments)
        text = str(outcome.get("text", ""))
        failed = bool(outcome.get("is_error"))
        meta = outcome.get("meta") if isinstance(outcome.get("meta"), dict) else {}
    except (TimeoutError, CancelledError):
        raise
    except Exception as exc:
        # 运维的协作式终止是控制流，不能伪装成可恢复的工具取数失败。
        reraise_stop(exc)
        text = f"工具调用失败：{type(exc).__name__}: {exc}"
        failed = True
        meta = {}
    return ToolOutcome(
        call=call, text=text, failed=failed, meta=meta,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


def _parallel_group(
    calls: list[ToolCall], executor: ToolExecutor, *,
    max_parallel_tools: int, checkpoint: Callable[[], None],
) -> list[ToolOutcome]:
    pool = ThreadPoolExecutor(max_workers=min(max_parallel_tools, len(calls)),
                              thread_name_prefix="agent-tool")
    pending: dict[Future[ToolOutcome], int] = {}
    results: dict[int, ToolOutcome] = {}
    aborted = Event()
    next_index = 0
    completed = False
    try:
        while next_index < len(calls) or pending:
            checkpoint()
            # 不向池无限排队，取消后不再启动尚未提交的工具。
            while next_index < len(calls) and len(pending) < max_parallel_tools:
                checkpoint()
                future = submit_with_tenant(pool, _invoke, calls[next_index], executor, aborted)
                pending[future] = next_index
                next_index += 1
            done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
            checkpoint()
            for future in sorted(done, key=pending.__getitem__):
                index = pending.pop(future)
                results[index] = future.result()
        completed = True
        return [results[index] for index in range(len(calls))]
    finally:
        aborted.set()
        for future in pending:
            future.cancel()
        # Python 不能强停已运行的同步工具；终止后仅让在途只读调用自行退出。
        pool.shutdown(wait=completed, cancel_futures=True)


def execute_tool_calls(
    calls: list[ToolCall], executor: ToolExecutor, *,
    max_calls_per_round: int | None, max_parallel_tools: int,
    parallel_tool_names: Collection[str] | None, allow_hitl: bool,
    checkpoint: Callable[[], None],
) -> list[ToolOutcome]:
    """白名单外工具形成顺序屏障；检查回调只在调用线程执行。"""
    whitelist = frozenset(parallel_tool_names or ()) - {"ask_user"}
    outcomes: list[ToolOutcome] = []
    admitted = calls[:max_calls_per_round]
    index = 0
    paused = False
    while index < len(admitted):
        checkpoint()
        call = admitted[index]
        if paused:
            outcomes.append(not_executed(call, "前序工具等待用户回复，请收到答复后重新请求"))
            index += 1
            continue
        end = index
        if max_parallel_tools > 1 and call.name in whitelist:
            while end < len(admitted) and admitted[end].name in whitelist:
                end += 1
        if end > index + 1:
            group = _parallel_group(admitted[index:end], executor,
                                    max_parallel_tools=max_parallel_tools, checkpoint=checkpoint)
            index = end
        else:
            group = [_invoke(call, executor, Event())]
            index += 1
        checkpoint()
        outcomes.extend(group)
        paused = allow_hitl and any(
            outcome.meta.get("pause") or outcome.meta.get("needs_hitl") for outcome in group
        )
    outcomes.extend(
        not_executed(call, f"超过本轮工具调用上限 {max_calls_per_round}，请在后续轮次重新请求")
        for call in (calls[max_calls_per_round:] if max_calls_per_round is not None else [])
    )
    return outcomes
