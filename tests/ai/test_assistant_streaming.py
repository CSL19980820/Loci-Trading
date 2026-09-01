"""助手流式与多轮：事件回放、批量落库、等待用户、空回复与上下文压缩。

从 `test_assistant_manager.py` 拆出（原 972 行）。
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.api.assistant import build_assistant_router
from src.ai.application.assistant_manager import AssistantManager
from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store import AssistantStore


def test_assistant_event_stream_replays_persisted_events_and_keeps_polling_compatible(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, provider="p", model="m", user_message="测试流")
        start = store.append_event(run_id, "start", {"session_id": session_id})
        token = store.append_event(run_id, "token", {"delta": "已持久化"})
        done = store.append_event(run_id, "done", {"stopped_reason": "completed"})
        store.finish_run(run_id, status="completed")
    app = FastAPI()
    app.include_router(build_assistant_router(write_dependency=lambda: None, ops_db=str(db_path), manager=manager))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            polled = client.get(f"/api/ai/runs/{run_id}/events")
            assert polled.status_code == 200
            assert [item["id"] for item in polled.json()["events"]] == [start["id"], token["id"], done["id"]]

            streamed = client.get(
                f"/api/ai/runs/{run_id}/events/stream",
                headers={"Last-Event-ID": start["id"]},
            )
        assert streamed.status_code == 200
        assert "text/event-stream" in streamed.headers["content-type"]
        assert f"id: {start['id']}" not in streamed.text
        assert f"id: {token['id']}\nevent: token\ndata: {{\"delta\":\"已持久化\"}}" in streamed.text
        assert f"id: {done['id']}\nevent: done" in streamed.text
    finally:
        manager.close()

def test_stream_token_think_are_batched_before_persist(tmp_path: Path) -> None:
    """token/think 走内存批写；收口前 flush；tool 事件立即落库。"""
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="流式")
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(
        text="你好世界",
        stopped_reason="completed",
        rounds=1,
        input_tokens=1,
        output_tokens=2,
        model="m",
    )

    def run_streaming(*_args, on_event=None, **_kwargs):
        assert on_event is not None
        on_event({"type": "token", "delta": "你"})
        on_event({"type": "token", "delta": "好"})
        on_event({"type": "tool_start", "name": "noop", "arguments": {}})
        on_event({"type": "think", "delta": "想"})
        on_event({"type": "think", "delta": "一下"})
        on_event({"type": "token", "delta": "世界"})
        return outcome

    try:
        with patch("src.ai.application.assistant_run_executor.run_agent", side_effect=run_streaming):
            manager._run(run_id, session_id, "流式", config)
        with AssistantStore(db_path) as store:
            events = store.poll_events(run_id)
            types = [e["event_type"] for e in events]
            # 两个小 token 在 tool_start 前合并为一条
            token_payloads = [e["payload"]["delta"] for e in events if e["event_type"] == "token"]
            think_payloads = [e["payload"]["delta"] for e in events if e["event_type"] == "think"]
            assert "你好" in token_payloads
            assert "世界" in token_payloads
            assert think_payloads == ["想一下"]
            assert types.index("token") < types.index("tool_start") < types.index("think")
            assert "done" in types
            # done 之后允许 session_title / memory_auto，但正文终态事件必须先于它们
            done_at = types.index("done")
            for later in ("session_title", "memory_auto"):
                if later in types:
                    assert done_at < types.index(later)
            rich = store.list_messages(session_id)[-1]["metadata"]
            assert rich.get("thinking") == "想一下"
    finally:
        manager.close()


def test_waiting_user_pauses_run_instead_of_completing(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="请确认")
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(
        text="是否继续？",
        stopped_reason="waiting_user",
        rounds=1,
        input_tokens=1,
        output_tokens=1,
        model="m",
        pending_ask={"prompt": "是否继续？", "options": ["是", "否"]},
    )
    try:
        with patch("src.ai.application.assistant_run_executor.run_agent", return_value=outcome):
            manager._run(run_id, session_id, "请确认", config)
        with AssistantStore(db_path) as store:
            run = store.get_run(run_id)
            session = store.get_session(session_id)
            events = [event["event_type"] for event in store.poll_events(run_id)]
            assert run is not None and run["status"] == "waiting_user"
            assert session is not None and session["status"] == "waiting_user"
            assert run["result"].get("pending_ask", {}).get("prompt") == "是否继续？"
            assert run["result"]["pending_ask"]["options"] == ["是", "否"]
            messages = store.list_messages(session_id)
            assistant = next(row for row in messages if row["role"] == "assistant")
            meta = assistant.get("metadata") if isinstance(assistant.get("metadata"), dict) else {}
            assert meta.get("hitl", {}).get("prompt") == "是否继续？"
            assert "done" not in events
            assert store.cancel_run(run_id) is True
            assert store.get_run(run_id)["status"] == "cancelled"
            assert store.get_session(session_id)["status"] == "idle"
    finally:
        manager.close()


def test_empty_completion_finishes_failed_with_error_not_done(tmp_path: Path) -> None:
    """Hermes/OpenClaw：空终稿耗尽后 manager 落 failed+error，禁止伪装 done。"""
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="平账")
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(
        text="本轮模型未产出可读终稿。",
        stopped_reason="empty_completion",
        rounds=3,
        input_tokens=1,
        output_tokens=1,
        model="m",
        pending_ask={},
    )
    try:
        with patch("src.ai.application.assistant_run_executor.run_agent", return_value=outcome):
            manager._run(run_id, session_id, "平账", config)
        with AssistantStore(db_path) as store:
            run = store.get_run(run_id)
            events = store.poll_events(run_id)
            types = [event["event_type"] for event in events]
            assert run is not None and run["status"] == "failed"
            assert "done" not in types
            assert "error" in types
            err = next(event for event in events if event["event_type"] == "error")
            assert err["payload"]["stopped_reason"] == "empty_completion"
            assert "未产出可读终稿" in err["payload"]["message"]
    finally:
        manager.close()


def test_reply_after_waiting_user_resumes_same_run(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    agent_messages = [
        {"role": "user", "content": "请确认"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "ask_user",
                    "arguments": {"prompt": "是否继续？", "options": ["是", "否"]},
                }
            ],
        },
        {"role": "tool", "content": "是否继续？", "tool_call_id": "c1"},
    ]
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        waiting_run = store.begin_run(session_id, user_message="请确认")
        store.pause_run_waiting_user(
            waiting_run,
            ask={"prompt": "是否继续？"},
            agent_messages=agent_messages,
        )
        store.append_message(session_id, role="assistant", content="是否继续？")

    manager = AssistantManager(ops_db=str(db_path))
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    captured: dict[str, object] = {}

    def capture_run(*_args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        return SimpleNamespace(
            text="好的，继续执行",
            stopped_reason="completed",
            rounds=1,
            input_tokens=1,
            output_tokens=1,
            model="m",
            pending_ask={},
            messages=[],
        )

    try:
        with patch(
            "src.ai.application.assistant_manager.OpsStore",
            side_effect=lambda *_args, **_kwargs: nullcontext(object()),
        ), patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch.object(
            AssistantManager, "_run", return_value=None
        ) as mocked_run:
            next_run = manager.start_run(session_id, message="继续")
        assert next_run == waiting_run
        mocked_run.assert_called_once()
        assert mocked_run.call_args.args[0] == waiting_run
        assert mocked_run.call_args.args[-1] is True  # resume_hitl
        with AssistantStore(db_path) as store:
            assert store.get_run(waiting_run)["status"] == "running"
            assert store.get_session(session_id)["status"] == "running"
            assert store.list_messages(session_id)[-1]["content"] == "继续"

        # 续环：用户答复进入末条 tool result，最终可 completed
        with patch(
            "src.ai.application.assistant_run_executor.run_agent", side_effect=capture_run
        ), patch(
            "src.ai.application.assistant_run_executor.build_system_toolbus",
            return_value=SimpleNamespace(
                schemas=[],
                executor=lambda *_a, **_k: {"text": ""},
                wait_for_background_tasks=lambda **_k: True,
            ),
        ), patch(
            "src.ai.application.assistant_run_executor.run_evidence_agents",
            return_value=[],
        ):
            manager._run(waiting_run, session_id, "继续", config, "", "", True)
        with AssistantStore(db_path) as store:
            assert store.get_run(waiting_run)["status"] == "completed"
            assert store.get_session(session_id)["status"] == "idle"
            assert "好的，继续执行" in store.list_messages(session_id)[-1]["content"]
        tool_msgs = [
            m for m in (captured.get("messages") or [])  # type: ignore[union-attr]
            if getattr(m, "role", None) == "tool"
        ]
        assert tool_msgs and tool_msgs[-1].content == "继续"
    finally:
        manager.close()


def test_reply_after_waiting_user_keeps_run_id_without_begin_run(tmp_path: Path) -> None:
    """反向：同 run resume，禁止再 begin_run 出第二 id。"""
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        waiting_run = store.begin_run(session_id, user_message="请确认")
        store.pause_run_waiting_user(
            waiting_run,
            ask={"prompt": "是否继续？"},
            agent_messages=[
                {"role": "user", "content": "请确认"},
                {"role": "tool", "content": "?", "tool_call_id": "c1"},
            ],
        )

    manager = AssistantManager(ops_db=str(db_path))
    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    try:
        with patch(
            "src.ai.application.assistant_manager.OpsStore",
            side_effect=lambda *_args, **_kwargs: nullcontext(object()),
        ), patch("src.ai.application.assistant_manager.resolve_config", return_value=config), patch.object(
            AssistantManager, "_run", return_value=None
        ):
            next_run = manager.start_run(session_id, message="继续")
        with AssistantStore(db_path) as store:
            assert next_run == waiting_run
            assert store.get_run(waiting_run)["status"] == "running"
            assert store.get_session(session_id)["status"] == "running"
            runs = store.conn.execute(
                "SELECT id, status FROM ai_agent_runs WHERE session_id=?", (session_id,)
            ).fetchall()
            assert len(runs) == 1
            assert runs[0]["id"] == waiting_run
    finally:
        manager.close()


def test_multi_turn_skips_empty_assistant_when_building_model_history(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        store.append_message(session_id, role="user", content="第一问")
        store.append_message(session_id, role="assistant", content="第一答")
        store.append_message(session_id, role="user", content="中间问")
        store.append_message(session_id, role="assistant", content="")  # 空气泡不得喂模
        run_id = store.begin_run(session_id, user_message="第二问")

    config = SimpleNamespace(name="test", model="m", protocol="openai_compatible")
    outcome = SimpleNamespace(
        text="第二答",
        stopped_reason="completed",
        rounds=1,
        input_tokens=1,
        output_tokens=1,
        model="m",
        pending_ask={},
    )
    captured: dict[str, object] = {}

    def capture_run(*_args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        return outcome

    class IdleBus:
        schemas: list[dict] = []

        @staticmethod
        def executor(_name, _arguments):
            return {"text": ""}

        def wait_for_background_tasks(self, *, is_cancelled) -> bool:
            return True

    manager = AssistantManager(ops_db=str(db_path))
    try:
        with patch(
            "src.ai.application.assistant_run_executor.run_evidence_agents",
            return_value=[],
        ), patch(
            "src.ai.application.assistant_run_executor.build_system_toolbus",
            return_value=IdleBus(),
        ), patch(
            "src.ai.application.assistant_run_executor.run_agent",
            side_effect=capture_run,
        ):
            manager._run(run_id, session_id, "第二问", config)
        messages = captured["messages"]
        assert messages is not None
        assert [(row.role, row.content) for row in messages] == [  # type: ignore[union-attr]
            ("user", "第一问"),
            ("assistant", "第一答"),
            ("user", "中间问"),
            ("user", "第二问"),
        ]
    finally:
        manager.close()


def test_public_run_keeps_completed_when_cancel_flag_races(tmp_path: Path) -> None:
    """completed + cancel_requested must not be published as cancelled."""
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="竞态")
        store.finish_run(run_id, status="completed")
        store.conn.execute("UPDATE ai_agent_runs SET cancel_requested = 1 WHERE id = ?", (run_id,))
        store.conn.commit()
    app = FastAPI()
    app.include_router(build_assistant_router(write_dependency=lambda: None, ops_db=str(db_path), manager=manager))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(f"/api/ai/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "done"
    finally:
        manager.close()


def test_finish_run_clears_cancel_requested_on_completed(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        run_id = store.begin_run(session_id, user_message="清旗")
        store.conn.execute("UPDATE ai_agent_runs SET cancel_requested = 1 WHERE id = ?", (run_id,))
        store.conn.commit()
        store.finish_run(run_id, status="completed")
        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "completed"
        assert not run["cancel_requested"]


def test_compact_session_writes_context_feed(tmp_path: Path) -> None:
    """手动 /compact：写入 metadata.context_feed，不删库原文。"""
    db_path = tmp_path / "ops.db"
    fat = "持仓复盘。" * 80
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        for i in range(8):
            store.append_message(session_id, role="user", content=f"用户问{i}：{fat}")
            store.append_message(session_id, role="assistant", content=f"助手答{i}：{fat}")
        before_count = len(store.list_messages(session_id, limit=200))

    manager = AssistantManager(ops_db=str(db_path))
    try:
        result = manager.compact_session(session_id)
        assert result["compacted"] is True
        assert result["tokens_after"] <= result["tokens_before"]
        assert result["message"]

        app = FastAPI()
        app.include_router(
            build_assistant_router(write_dependency=lambda: None, ops_db=str(db_path), manager=manager)
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/api/ai/sessions/{session_id}/compact")
        assert response.status_code == 200
        body = response.json()
        assert body["compacted"] is True
    finally:
        manager.close()

    with AssistantStore(db_path) as store:
        after_count = len(store.list_messages(session_id, limit=200))
        assert after_count == before_count  # 库内原文保留
        session = store.get_session(session_id)
        assert session is not None
        feed = (session.get("metadata") or {}).get("context_feed")
        assert isinstance(feed, dict)
        assert feed.get("through_seq")
        assert isinstance(feed.get("messages"), list)
        assert feed["messages"]


def test_compact_session_rejects_short_or_busy(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        store.append_message(session_id, role="user", content="短")

    manager = AssistantManager(ops_db=str(db_path))
    try:
        with pytest.raises(AssistantError, match="太短"):
            manager.compact_session(session_id)

        with AssistantStore(db_path) as store:
            store.append_message(session_id, role="assistant", content="答")
            store.append_message(session_id, role="user", content="再问")
            store.append_message(session_id, role="assistant", content="再答")
            store.conn.execute(
                "UPDATE ai_sessions SET status = ? WHERE id = ?",
                ("running", session_id),
            )
            store.conn.commit()
        with pytest.raises(AssistantError, match="占用"):
            manager.compact_session(session_id)
    finally:
        manager.close()
