"""助手 run 管理器：并发认领、线程池失败、启动期收尾与取消。

路由契约在 `test_assistant_router.py`，流式与多轮在 `test_assistant_streaming.py`。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.api.assistant import build_assistant_router
from src.ai.application.assistant_manager import AssistantManager
from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store import AssistantStore


def _wait_for_terminal_run(db_path: Path, run_id: str, *, timeout: float = 5.0) -> dict:
    deadline = monotonic() + timeout
    terminal_events = {"completed": "done", "failed": "error", "cancelled": "cancelled"}
    while monotonic() < deadline:
        with AssistantStore(db_path) as store:
            run = store.get_run(run_id)
            events = store.poll_events(run_id)
        if run is not None and run["status"] in terminal_events:
            expected = terminal_events[run["status"]]
            # done 之后还可能追加 session_title / memory_auto，不能要求末条必须是终态事件
            if any(row["event_type"] == expected for row in events):
                return run
        sleep(0.01)
    raise AssertionError(f"AI 运行 {run_id} 未在 {timeout} 秒内结束")


def test_missing_provider_creates_visible_failed_run(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
    manager = AssistantManager(ops_db=str(tmp_path / "ops.db"))
    with pytest.raises(AssistantError, match="provider 不可用"):
        manager.start_run(session_id, message="你好")
    with AssistantStore(tmp_path / "ops.db") as store:
        assert store.list_messages(session_id)[0]["role"] == "user"
        run = store.conn.execute("SELECT status FROM ai_agent_runs").fetchone()
        assert run["status"] == "failed"
    manager.close()


def test_concurrent_start_run_claims_session_once(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()

    barrier = Barrier(2)
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")

    def resolve(*_args, **_kwargs):
        barrier.wait(timeout=3)
        return config

    manager = AssistantManager(ops_db=str(db_path))
    try:
        with patch(
            "src.ai.application.assistant_manager.OpsStore",
            side_effect=lambda *_args, **_kwargs: nullcontext(object()),
        ), patch("src.ai.application.assistant_manager.resolve_config", side_effect=resolve), patch.object(
            AssistantManager, "_run", return_value=None
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(manager.start_run, session_id, message=f"并发消息 {index}")
                    for index in range(2)
                ]
                results = []
                errors = []
                for future in futures:
                    try:
                        results.append(future.result(timeout=5))
                    except AssistantError as exc:
                        errors.append(exc)

        assert len(results) == 1
        assert len(errors) == 1
        assert "已有运行" in str(errors[0])
        with AssistantStore(db_path) as store:
            assert len(store.list_messages(session_id)) == 1
            runs = store.conn.execute(
                "SELECT id FROM ai_agent_runs WHERE session_id = ?", (session_id,)
            ).fetchall()
            assert len(runs) == 1
    finally:
        manager.close()


def test_thread_pool_submit_failure_marks_run_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    manager = AssistantManager(ops_db=str(db_path))
    try:
        with patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch.object(
            manager._pool, "submit", side_effect=RuntimeError("executor closed")
        ), pytest.raises(AssistantError, match="后台运行启动失败"):
            manager.start_run(session_id, message="你好")

        with AssistantStore(db_path) as store:
            run = store.conn.execute("SELECT * FROM ai_agent_runs").fetchone()
            session = store.get_session(session_id)
            assert run["status"] == "failed"
            assert session is not None
            assert session["status"] == "error"
            events = store.poll_events(run["id"])
            types = [event["event_type"] for event in events]
            assert types[0] == "start"
            assert types[-1] == "error"
            # begin_run 后可能先发临时 session_title
            assert "session_title" in types or types == ["start", "error"]
            assert "RuntimeError: executor closed" in events[-1]["payload"]["message"]
    finally:
        manager.close()


def test_assistant_router_returns_503_when_thread_pool_is_unavailable(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
    manager = AssistantManager(ops_db=str(db_path))
    app = FastAPI()
    app.include_router(
        build_assistant_router(
            write_dependency=lambda: None,
            ops_db=str(db_path),
            manager=manager,
        )
    )
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    try:
        with patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch.object(
            manager._pool, "submit", side_effect=RuntimeError("executor closed")
        ), TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/api/ai/sessions/{session_id}/messages", json={"message": "你好"})

        assert response.status_code == 503
        assert "后台运行启动失败" in response.json()["detail"]
        with AssistantStore(db_path) as store:
            run = store.conn.execute("SELECT status FROM ai_agent_runs").fetchone()
            assert run["status"] == "failed"
    finally:
        manager.close()


def test_completed_background_run_does_not_remain_in_manager_memory(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
    completed = Event()
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    manager = AssistantManager(ops_db=str(tmp_path / "ops.db"))
    try:
        def finish_immediately(*_args, **_kwargs) -> None:
            completed.set()

        with patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch.object(
            AssistantManager, "_run", side_effect=finish_immediately
        ):
            manager.start_run(session_id, message="你好")
            assert completed.wait(timeout=1)
        assert "_futures" not in vars(manager)
    finally:
        manager.close()


def test_manager_marks_interrupted_runs_failed_on_startup(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, provider="p", model="m", user_message="服务重启前的请求")

    manager = AssistantManager(ops_db=str(db_path))
    try:
        with AssistantStore(db_path) as store:
            run = store.get_run(run_id)
            session = store.get_session(session_id)
            assert run is not None
            assert session is not None
            assert run["status"] == "failed"
            assert run["result"]["interrupted"] is True
            assert session["status"] == "error"
            assert store.poll_events(run_id)[-1]["event_type"] == "error"
    finally:
        manager.close()


def test_owner_full_executes_inferred_write_without_field_echo(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(
        ops_db=str(db_path),
        palace_db=str(tmp_path / "palace.db"),
        market_db=str(tmp_path / "market.db"),
    )
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="把这只记下来")
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    results: list[dict] = []

    def run_with_inferred_write(*_args, tool_executor, **_kwargs):
        results.append(
            tool_executor(
                "ledger_upsert_candidate",
                {"code": "600000", "name": "浦发银行", "decision": "观察", "reason": "等待确认"},
            )
        )
        return SimpleNamespace(
            text="已记录", stopped_reason="completed", rounds=1,
            input_tokens=1, output_tokens=1, model="m",
        )

    try:
        with patch("src.ai.application.assistant_manager.run_agent", side_effect=run_with_inferred_write):
            manager._run(run_id, session_id, "把这只记下来", config)
        assert results and not results[0]["is_error"]
        assert results[0]["structured"]["code"] == "600000"
        with AssistantStore(db_path) as store:
            run = store.get_run(run_id)
            assert run is not None and run["status"] == "completed"
            assert "execution_grant" in [event["event_type"] for event in store.poll_events(run_id)]
    finally:
        manager.close()


def test_evidence_brief_enters_main_system_without_write_tool_names(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="查询今日候选")
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    captured: dict[str, str] = {}
    outcome = SimpleNamespace(
        text="无写入",
        stopped_reason="completed",
        rounds=1,
        input_tokens=0,
        output_tokens=0,
        model="m",
    )

    def run_with_system(*_args, system: str, **_kwargs):
        captured["system"] = system
        return outcome

    try:
        with patch(
            "src.ai.application.assistant_manager.run_evidence_agents",
            return_value=[
                {
                    "id": "candidate-evidence",
                    "name": "候选核对",
                    "role": "qianlong",
                    "ok": True,
                    "text": "池内 1 只，待复核",
                }
            ],
        ), patch(
            "src.ai.application.assistant_manager.run_agent",
            side_effect=run_with_system,
        ):
            manager._run(run_id, session_id, "查询今日候选", config)
        assert "并行只读证据" in captured["system"]
        assert "池内 1 只" in captured["system"]
        assert "ledger_upsert_candidate" not in captured["system"]
    finally:
        manager.close()


def test_background_run_persists_events_and_does_not_need_client_lifetime(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(text="完成", stopped_reason="completed", rounds=1, input_tokens=2, output_tokens=3, model="m")
    order: list[str] = []

    class WaitingBus:
        schemas: list[dict] = []

        @staticmethod
        def executor(_name, _arguments):
            return {"text": ""}

        def wait_for_background_tasks(self, *, is_cancelled) -> bool:
            assert not is_cancelled()
            order.append("wait")
            return True

    original_finish = AssistantStore.finish_run

    def tracked_finish(store, *args, **kwargs):
        order.append("finish")
        return original_finish(store, *args, **kwargs)

    def run_without_terminal(*_args, **kwargs):
        assert kwargs["emit_terminal_event"] is False
        order.append("agent")
        return outcome

    manager = AssistantManager(ops_db=str(tmp_path / "ops.db"))
    with patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch(
        "src.ai.application.assistant_manager.run_agent", side_effect=run_without_terminal
    ), patch("src.ai.application.assistant_manager.build_system_toolbus", return_value=WaitingBus()), patch.object(
        AssistantStore, "finish_run", new=tracked_finish
    ):
        run_id = manager.start_run(session_id, message="你好")
        _wait_for_terminal_run(tmp_path / "ops.db", run_id)
    assert order.index("wait") < order.index("finish")
    with AssistantStore(tmp_path / "ops.db") as store:
        assert store.get_run(run_id)["status"] == "completed"
        events = store.poll_events(run_id)
        event_types = [event["event_type"] for event in events]
        assert event_types[0] == "start"
        assert event_types.count("done") == 1
        done = next(event for event in events if event["event_type"] == "done")
        assert done["payload"]["text"] == "完成"
        assert done["payload"]["content"] == "完成"
        assert store.list_messages(session_id)[-1]["content"] == "完成"
    manager.close()


def test_cancelled_run_stops_waiting_for_background_jobs(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(text="完成", stopped_reason="completed", rounds=1, input_tokens=2, output_tokens=3, model="m")
    waiting = Event()

    class WaitingBus:
        schemas: list[dict] = []

        @staticmethod
        def executor(_name, _arguments):
            return {"text": ""}

        def wait_for_background_tasks(self, *, is_cancelled) -> bool:
            waiting.set()
            for _ in range(100):
                if is_cancelled():
                    return False
                sleep(0.01)
            return True

    manager = AssistantManager(ops_db=str(tmp_path / "ops.db"))
    try:
        with patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch(
            "src.ai.application.assistant_manager.run_agent", return_value=outcome
        ), patch("src.ai.application.assistant_manager.build_system_toolbus", return_value=WaitingBus()):
            run_id = manager.start_run(session_id, message="你好")
            assert waiting.wait(timeout=1)
            assert manager.cancel_run(run_id)
            _wait_for_terminal_run(tmp_path / "ops.db", run_id, timeout=2)
        with AssistantStore(tmp_path / "ops.db") as store:
            run = store.get_run(run_id)
            assert run is not None
            assert run["status"] == "cancelled"
            assert store.get_session(session_id)["status"] == "idle"
            assert any(event["event_type"] == "cancelled" for event in store.poll_events(run_id))
    finally:
        manager.close()


def test_cancel_running_releases_session_for_immediate_next_send(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="先跑着")
        assert store.get_session(session_id)["status"] == "running"
        assert store.cancel_run(run_id)
        assert store.get_run(run_id)["status"] == "cancelled"
        assert store.get_session(session_id)["status"] == "idle"
        # 取消后应立刻能开下一轮，不必等 worker 收口
        next_id = store.begin_run(session_id, user_message="马上再问")
        assert next_id != run_id
        assert store.get_session(session_id)["status"] == "running"


def test_append_assistant_if_run_active_skips_after_cancel(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="旧轮")
        store.cancel_run(run_id)
        next_id = store.begin_run(session_id, user_message="新轮")
        assert store.append_assistant_if_run_active(run_id, session_id, content="迟到的旧答") is None
        assert store.append_assistant_if_run_active(next_id, session_id, content="新答") is not None
        contents = [row["content"] for row in store.list_messages(session_id)]
        assert contents == ["旧轮", "新轮", "新答"]
