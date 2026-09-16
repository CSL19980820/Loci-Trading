"""工具执行顺序、预算回执、终止传播与跨线程租户隔离。"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import pytest

from src.ai import ChatResponse, ProviderConfig, ToolCall
from src.ai.application import agent
from src.ops import JobCancelled, JobTimedOut
from src.shared.paths import ops_db
from src.shared.tenancy import current_tenant, submit_with_tenant, tenant_scope

CONFIG = ProviderConfig(
    name="test", protocol="openai_compatible", base_url="https://example.test/v1",
    api_key="test", model="test",
)


def _calls(*names: str) -> list[ToolCall]:
    return [ToolCall(id=f"call-{index}", name=name, arguments={"index": index})
            for index, name in enumerate(names)]


def _run(
    monkeypatch: pytest.MonkeyPatch, calls: list[ToolCall], executor: Any, **kwargs: Any,
) -> agent.AgentResult:
    def chat(_config: Any, messages: Any, **_kwargs: Any) -> ChatResponse:
        if any(message.role == "tool" for message in messages):
            return ChatResponse(text="完成")
        return ChatResponse(text="取数", tool_calls=calls, reasoning_content="原始推理")

    monkeypatch.setattr(agent, "chat", chat)
    return agent.run_agent(
        CONFIG, system="系统", user_prompt="请求", tool_executor=executor, stream=False, **kwargs,
    )


@pytest.mark.parametrize("options", [{}, {"max_parallel_tools": 3},
                                      {"parallel_tool_names": {"read_a", "read_b"}}])
def test_parallel_requires_both_an_explicit_limit_and_whitelist(
    monkeypatch: pytest.MonkeyPatch, options: dict[str, Any],
) -> None:
    caller = threading.get_ident()
    seen: list[str] = []

    def execute(name: str, _arguments: Any) -> dict[str, Any]:
        assert threading.get_ident() == caller
        seen.append(name)
        return {"text": name}

    result = _run(monkeypatch, _calls("read_a", "write", "read_b"), execute, **options)
    assert seen == ["read_a", "write", "read_b"]
    assert all(item.ok for item in result.invocations)


def test_read_groups_overlap_but_writes_are_ordered_barriers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = threading.get_ident()
    barriers = [threading.Barrier(2), threading.Barrier(2)]
    faster_done = [threading.Event(), threading.Event()]
    lock = threading.Lock()
    active = peak = 0
    finished: list[str] = []
    callbacks: list[int] = []
    names = ["read_a", "read_b", "write", "read_c", "read_d"]

    def checkpoint() -> None:
        callbacks.append(threading.get_ident())

    def execute(name: str, _arguments: Any) -> dict[str, Any]:
        nonlocal active, peak
        if name == "write":
            assert threading.get_ident() == caller
            assert active == 0 and finished == ["read_b", "read_a"]
            finished.append(name)
            return {"text": name}
        assert threading.get_ident() != caller
        group = 0 if name in {"read_a", "read_b"} else 1
        with lock:
            active += 1
            peak = max(peak, active)
        barriers[group].wait(timeout=5)
        if name in {"read_a", "read_c"}:
            assert faster_done[group].wait(5)
        with lock:
            finished.append(name)
            active -= 1
        if name in {"read_b", "read_d"}:
            faster_done[group].set()
        return {"text": name}

    result = _run(
        monkeypatch, _calls(*names), execute, max_parallel_tools=2,
        parallel_tool_names=set(names) - {"write"}, check_cancelled=checkpoint,
        on_event=lambda _event: callbacks.append(threading.get_ident()),
    )
    assert peak == 2
    assert finished == ["read_b", "read_a", "write", "read_d", "read_c"]
    assert callbacks and set(callbacks) == {caller}
    assert [item.name for item in result.invocations] == names
    messages = [row for row in result.messages if row["role"] == "tool"]
    assert [row["content"] for row in messages] == names
    assert [row["tool_call_id"] for row in messages] == [f"call-{i}" for i in range(5)]


@pytest.mark.parametrize("limit", [0, 1])
def test_over_budget_calls_keep_ids_and_explicit_unexecuted_results(
    monkeypatch: pytest.MonkeyPatch, limit: int,
) -> None:
    seen: list[int] = []

    def execute(_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        seen.append(arguments["index"])
        return {"text": "确实执行"}

    result = _run(monkeypatch, _calls("read", "read", "read"), execute,
                  max_calls_per_round=limit, max_tool_result_chars=1)
    assert seen == list(range(limit))
    request = next(row for row in result.messages if row["role"] == "assistant")
    assert [call["id"] for call in request["tool_calls"]] == [f"call-{i}" for i in range(3)]
    assert request["reasoning_content"] == "原始推理"
    replies = [row for row in result.messages if row["role"] == "tool"]
    assert [row["tool_call_id"] for row in replies] == [f"call-{i}" for i in range(3)]
    for reply in replies[limit:]:
        assert "工具未执行" in reply["content"] and "后续轮次重新请求" in reply["content"]
    trace = result.to_dict()["tool_calls"]
    assert [row["executed"] for row in trace] == [i < limit for i in range(3)]
    assert [row["tool_call_id"] for row in trace] == [f"call-{i}" for i in range(3)]
    assert not any(row["ok"] for row in trace[limit:])


@pytest.mark.parametrize("error_type", [TimeoutError, CancelledError, asyncio.CancelledError,
                                          JobCancelled, JobTimedOut])
@pytest.mark.parametrize("parallel", [False, True])
def test_executor_cancellation_and_timeout_propagate(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException], parallel: bool,
) -> None:
    writes: list[str] = []

    def execute(name: str, _arguments: Any) -> dict[str, Any]:
        if name == "write":
            writes.append(name)
        raise error_type("停止")

    with pytest.raises(error_type, match="停止"):
        _run(monkeypatch, _calls("read_a", "read_b", "write"), execute,
             max_parallel_tools=2 if parallel else 1,
             parallel_tool_names={"read_a", "read_b"})
    assert writes == []


def test_cancel_while_waiting_does_not_wait_for_or_queue_more_read_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = threading.get_ident()
    started = threading.Barrier(2)
    both_started = threading.Event()
    release = threading.Event()
    all_finished = threading.Event()
    lock = threading.Lock()
    seen: list[str] = []
    finished: list[str] = []

    def execute(name: str, _arguments: Any) -> dict[str, Any]:
        with lock:
            seen.append(name)
        started.wait(timeout=5)
        both_started.set()
        release.wait(5)
        with lock:
            finished.append(name)
            if len(finished) == 2:
                all_finished.set()
        return {"text": name}

    def checkpoint() -> None:
        assert threading.get_ident() == caller
        if both_started.is_set():
            raise JobCancelled("用户取消")

    try:
        with pytest.raises(JobCancelled, match="用户取消"):
            _run(monkeypatch, _calls("read_a", "read_b", "read_c", "write"), execute,
                 max_parallel_tools=2, parallel_tool_names={"read_a", "read_b", "read_c"},
                 check_cancelled=checkpoint)
        assert not finished, "取消不应等待在途只读调用完成"
        assert set(seen) == {"read_a", "read_b"}
    finally:
        release.set()
        assert all_finished.wait(5)


def test_parallel_tools_keep_each_run_tenant_and_other_context_vars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    marker: ContextVar[str] = ContextVar("agent_test_marker", default="missing")
    barrier = threading.Barrier(4)
    tenants = ["agent_alice", "agent_bob"]
    for tenant in tenants:
        with tenant_scope(tenant):
            path = ops_db()
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE test_owner (name TEXT)")
                connection.execute("INSERT INTO test_owner VALUES (?)", (tenant,))

    def execute(_name: str, _arguments: Any) -> dict[str, Any]:
        barrier.wait(timeout=5)
        with sqlite3.connect(ops_db()) as connection:
            owner = connection.execute("SELECT name FROM test_owner").fetchone()[0]
        return {"text": f"{current_tenant()}:{marker.get()}:{owner}"}

    def chat(_config: Any, messages: Any, **_kwargs: Any) -> ChatResponse:
        if any(message.role == "tool" for message in messages):
            return ChatResponse(text="完成")
        return ChatResponse(text="", tool_calls=_calls("read_a", "read_b"))

    monkeypatch.setattr(agent, "chat", chat)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for tenant in tenants:
            with tenant_scope(tenant):
                token = marker.set(f"marker-{tenant}")
                try:
                    futures.append(submit_with_tenant(
                        pool, agent.run_agent, CONFIG, system="系统", user_prompt="请求",
                        tool_executor=execute, stream=False, max_parallel_tools=2,
                        parallel_tool_names={"read_a", "read_b"},
                    ))
                finally:
                    marker.reset(token)
        results = [future.result(timeout=10) for future in futures]
    for tenant, result in zip(tenants, results):
        assert len(result.invocations) == 2
        assert all(item.ok for item in result.invocations)
        assert [item.result_preview for item in result.invocations] == [
            f"{tenant}:marker-{tenant}:{tenant}",
        ] * 2


def test_hitl_keeps_all_replies_and_resumes_the_actual_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def execute(name: str, _arguments: Any) -> dict[str, Any]:
        seen.append(name)
        return {"text": "选择什么？", "meta": {"pause": True, "ask": {"prompt": "选择什么？"}}}

    result = _run(monkeypatch, _calls("ask_user", "write", "read"), execute,
                  max_calls_per_round=2, max_parallel_tools=3,
                  parallel_tool_names={"ask_user", "read"}, allow_hitl=True)
    assert seen == ["ask_user"]
    assert result.stopped_reason == "waiting_user"
    assert len([row for row in result.messages if row["role"] == "tool"]) == 3
    resumed = agent.apply_hitl_tool_result(result.messages, "选择甲")
    replies = [message for message in resumed if message.role == "tool"]
    assert replies[0].tool_call_id == "call-0" and replies[0].content == "选择甲"
    assert all("工具未执行" in message.content for message in replies[1:])
