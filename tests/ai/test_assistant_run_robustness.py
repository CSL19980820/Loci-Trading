"""助手后台运行的收口：并发事件写入、取消传播、整轮期限与异常计费。"""
import threading
from concurrent.futures import CancelledError
from types import SimpleNamespace

import pytest

from src.ai.application import assistant_evidence_agents as evidence
from src.ai.application import assistant_run_executor as executor
from src.ai.application.assistant_evidence_agents import (
    EvidenceRoleSpec,
    run_evidence_agents,
)
from src.ai.application.assistant_run_executor import (
    AssistantRunExecutorMixin,
    RunCancelWatch,
)
from src.ai.application.assistant_stream_buffer import StreamEventBuffer
from src.ai.infrastructure.assistant_store import AssistantStore

CONFIG = SimpleNamespace(name="fixture", model="fixture-model", protocol="openai_compatible", context_window=None)


@pytest.fixture
def run(tmp_path):
    ops_db = str(tmp_path / "ops.db")
    with AssistantStore(ops_db) as store:
        session_id = store.create_session(title="t")
        run_id = store.begin_run(session_id, provider="fixture", model="fixture-model", user_message="你好")
    return SimpleNamespace(ops_db=ops_db, session_id=session_id, run_id=run_id)


def test_concurrent_emitters_share_one_connection_safely(run):
    """并行证据子 Agent 与后台任务在各自线程回调同一个缓冲，不得互踩事务。"""
    store = AssistantStore(run.ops_db)
    buffer = StreamEventBuffer(lambda kind, payload: store.append_event(run.run_id, kind, payload))
    errors = []

    def emit(worker):
        for index in range(150):
            try:
                buffer.emit({"type": "subagent_progress", "id": worker, "n": index})
                buffer.emit({"type": "token", "delta": "x"})
            except Exception as exc:  # noqa: BLE001 — 任何异常都记下，由下方断言为空
                errors.append(repr(exc))

    threads = [threading.Thread(target=emit, args=(worker,)) for worker in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    buffer.flush()
    seqs = [event["seq"] for event in store.poll_events(run.run_id, limit=500)]
    rows = store.conn.execute("SELECT COUNT(*) FROM ai_agent_events WHERE run_id=?", (run.run_id,)).fetchone()[0]
    store.close()
    assert errors == []
    assert seqs == list(range(1, len(seqs) + 1))
    assert rows >= 450


def test_cancel_watch_raises_once_run_is_cancelled(run):
    watch = RunCancelWatch(run.ops_db, run.run_id, interval=0)
    watch()
    with AssistantStore(run.ops_db) as store:
        assert store.cancel_run(run.run_id)
    with pytest.raises(CancelledError):
        watch()
    with pytest.raises(CancelledError):
        watch()  # 已判取消后不再读库
    watch.close()


class Host(AssistantRunExecutorMixin):
    def __init__(self, ops_db):
        self.ops_db = ops_db
        self.palace_db = ops_db
        self.market_db = None
        self.scheduler_reloader = None


class FakeBus:
    schemas: tuple = ()

    def executor(self, name, arguments):  # pragma: no cover - never called
        raise AssertionError(name)

    def wait_for_background_tasks(self, **_kwargs):
        return True


def run_host(monkeypatch, run, fake_agent):
    monkeypatch.setattr(executor, "build_system_toolbus", lambda **_kwargs: FakeBus())
    monkeypatch.setattr(executor, "run_evidence_agents", lambda **_kwargs: [])
    monkeypatch.setattr(executor, "run_agent", fake_agent)
    Host(run.ops_db)._run(run.run_id, run.session_id, "你好", CONFIG)
    with AssistantStore(run.ops_db) as store:
        current = store.get_run(run.run_id)
        events = store.poll_events(run.run_id, limit=500)
        usage = store.monthly_token_usage()
    return current, events, usage


def test_user_cancel_stops_agent_loop(monkeypatch, run):
    seen = {}

    def fake_agent(config, **kwargs):
        seen.update(kwargs)
        with AssistantStore(run.ops_db) as store:
            store.cancel_run(run.run_id)
        error = CancelledError("AI 运行已取消")
        for _ in range(3):
            try:
                kwargs["check_cancelled"]()
            except CancelledError as exc:
                error = exc
                break
        error.usage = {"model": "fixture-model", "input_tokens": 40, "output_tokens": 2}
        raise error

    current, events, usage = run_host(monkeypatch, run, fake_agent)
    assert seen["deadline"] is not None
    assert current["status"] == "cancelled"
    assert events[-1]["event_type"] == "cancelled"
    assert usage == 42


def test_run_deadline_failure_is_explained_and_billed(monkeypatch, run):
    monkeypatch.setenv(executor.RUN_TIMEOUT_ENV, "90")

    def fake_agent(config, **kwargs):
        error = TimeoutError("Agent 已超过本轮截止时间")
        error.usage = {"model": "fixture-model", "input_tokens": 100, "output_tokens": 5}
        raise error

    current, events, usage = run_host(monkeypatch, run, fake_agent)
    assert current["status"] == "failed"
    assert "90 秒上限" in current["error_text"]
    assert events[-1]["event_type"] == "error"
    assert usage == 105


def test_run_timeout_env_falls_back_on_invalid_values(monkeypatch):
    for raw in ("abc", "-5", "0", "inf"):
        monkeypatch.setenv(executor.RUN_TIMEOUT_ENV, raw)
        assert executor.assistant_run_timeout() == executor.DEFAULT_RUN_TIMEOUT_SECONDS


def test_evidence_agent_failures_never_break_main_answer(monkeypatch):
    specs = [EvidenceRoleSpec(id="a", name="甲", role="market", focus="x", allow_tools=frozenset()),
             EvidenceRoleSpec(id="b", name="乙", role="web", focus="y", allow_tools=frozenset())]
    monkeypatch.setattr(evidence, "build_system_toolbus", lambda **_kwargs: FakeBus())

    def fake_agent(config, **kwargs):
        assert kwargs["deadline"] is not None
        if "x" in kwargs["user_prompt"]:
            return SimpleNamespace(stopped_reason="completed", text="证据", model="m", input_tokens=7, output_tokens=3)
        error = RuntimeError("upstream down")
        error.usage = {"model": "m", "input_tokens": 5, "output_tokens": 0}
        raise error

    monkeypatch.setattr(evidence, "run_agent", fake_agent)
    calls = {"n": 0}

    def on_event(payload):
        # 事件落库失败只能让该子 Agent 记失败，不能从 future.result() 冒到主环。
        if payload.get("type") == "subagent_end" and payload.get("ok") is False:
            calls["n"] += 1
            raise OSError("disk full")

    rows = run_evidence_agents(config=CONFIG, prompt="q", palace_db=None, market_db=None, ops_db=None,
                               on_event=on_event, specs=specs, deadline=10**9)
    assert [row["id"] for row in rows] == ["a", "b"]
    assert rows[0]["ok"] and rows[0]["input_tokens"] == 7
    assert rows[1]["ok"] is False and "OSError" in rows[1]["text"]
    assert calls["n"] == 1


def test_worker_pool_size_is_configurable(monkeypatch):
    from src.ai.application import assistant_manager

    monkeypatch.delenv(assistant_manager.WORKERS_ENV, raising=False)
    assert assistant_manager._resolve_workers() == assistant_manager.DEFAULT_WORKERS
    for raw, expected in (("8", 8), ("0", 1), ("999", 32), ("abc", assistant_manager.DEFAULT_WORKERS)):
        monkeypatch.setenv(assistant_manager.WORKERS_ENV, raw)
        assert assistant_manager._resolve_workers() == expected
    assert assistant_manager._resolve_workers(3) == 3


def reply(text, tokens_in, tokens_out):
    from src.ai.infrastructure.client import ChatResponse

    return ChatResponse(text=text, model="fixture-model", input_tokens=tokens_in, output_tokens=tokens_out)


def test_title_and_memory_side_calls_are_billed(monkeypatch, run):
    from src.ai.application import assistant_memory, assistant_session_title

    monkeypatch.setattr(assistant_session_title, "chat", lambda *a, **k: reply("行情复盘", 30, 4))
    monkeypatch.setattr(assistant_memory, "chat", lambda *a, **k: reply('{"ops":[]}', 50, 6))
    with AssistantStore(run.ops_db) as store:
        titled = assistant_session_title.maybe_summarize_session_title(
            store, run.session_id, CONFIG, user_message="你好", assistant_text="回答")
        monkeypatch.setattr(store, "get_profile",
                            lambda: {"memory_enabled": True, "auto_memory_enabled": True, "auto_memory_min_turns": 2})
        monkeypatch.setattr(store, "count_dialog_messages", lambda _session: 10)
        memory = assistant_memory.maybe_auto_consolidate_memory(store, session_id=run.session_id, config=CONFIG)
        usage = store.monthly_token_usage()
    assert titled and titled["title"] == "行情复盘"
    assert memory["status"] == "ok"
    assert usage == 30 + 4 + 50 + 6
