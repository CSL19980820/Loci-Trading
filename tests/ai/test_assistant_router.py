"""助手 HTTP 路由契约：写权限、默认库、run 载荷与会话详情。

从 `test_assistant_manager.py` 拆出（原 972 行）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.ai.api.assistant import build_assistant_router
from src.ai.application.assistant_manager import AssistantManager
from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store import AssistantStore


def test_assistant_router_enforces_write_auth_and_rejects_extra_fields(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(build_assistant_router(write_dependency=lambda: None, ops_db=str(tmp_path / "ops.db")))
    with TestClient(app) as client:
        assert client.post("/api/ai/sessions", json={"title": "x", "unexpected": True}).status_code == 422

    def deny() -> None:
        raise HTTPException(status_code=401, detail="unauthorized")

    blocked = FastAPI()
    blocked.include_router(build_assistant_router(write_dependency=deny, ops_db=str(tmp_path / "blocked.db")))
    with TestClient(blocked) as client:
        assert client.get("/api/ai/sessions").status_code == 401


def test_assistant_router_uses_default_ops_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALACE_OPS_DB", raising=False)
    monkeypatch.delenv("PALACE_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(build_assistant_router(write_dependency=lambda: None))

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/ai/sessions").json() == []
        created = client.post("/api/ai/sessions", json={})
        assert created.status_code == 201
        assert client.get("/api/ai/sessions").json()[0]["id"] == created.json()["id"]

    assert (tmp_path / "ops.db").is_file()


def test_assistant_router_returns_run_payload_and_archived_status(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, provider="p", model="m", user_message="取消")
    app = FastAPI()
    app.include_router(
        build_assistant_router(
            write_dependency=lambda: None,
            ops_db=str(db_path),
            manager=manager,
        )
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            archived_while_running = client.patch(
                f"/api/ai/sessions/{session_id}", json={"archived": True}
            )
            assert archived_while_running.status_code == 422
            deleted_while_running = client.delete(f"/api/ai/sessions/{session_id}")
            assert deleted_while_running.status_code == 422

            cancelled = client.post(f"/api/ai/runs/{run_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["id"] == run_id
            assert cancelled.json()["status"] == "cancelled"

            # 取消立即释放会话：无需再等 worker finish_run 即可归档
            archived = client.patch(f"/api/ai/sessions/{session_id}", json={"archived": True})
            assert archived.status_code == 200
            assert archived.json()["status"] == "archived"
    finally:
        manager.close()


def test_session_detail_includes_active_run_with_cursor(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    manager = AssistantManager(ops_db=str(db_path))
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, provider="p", model="m", user_message="进行中")
        event = store.append_event(run_id, "token", {"delta": "续拉"})
    app = FastAPI()
    app.include_router(
        build_assistant_router(
            write_dependency=lambda: None,
            ops_db=str(db_path),
            manager=manager,
        )
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            idle = client.get(f"/api/ai/sessions/{session_id}")
            assert idle.status_code == 200
            body = idle.json()
            assert body["active_run"]["id"] == run_id
            assert body["active_run"]["status"] == "running"
            assert body["active_run"]["cursor"] == event["id"]

            with AssistantStore(db_path) as store:
                store.pause_run_waiting_user(run_id, ask={"prompt": "是否继续？"})
            waiting = client.get(f"/api/ai/sessions/{session_id}")
            assert waiting.status_code == 200
            assert waiting.json()["active_run"]["status"] == "waiting_user"
            assert waiting.json()["status"] == "waiting_user"
            assert waiting.json()["active_run"]["pending_ask"]["prompt"] == "是否继续？"

            blocked = client.patch(f"/api/ai/sessions/{session_id}", json={"archived": True})
            assert blocked.status_code == 422

            with AssistantStore(db_path) as store:
                store.cancel_run(run_id)
            cleared = client.get(f"/api/ai/sessions/{session_id}")
            assert cleared.status_code == 200
            assert cleared.json()["active_run"] is None
    finally:
        manager.close()


def test_monthly_token_budget_rejects_before_persisting_a_new_run(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    with AssistantStore(db_path) as store:
        session_id = store.create_session()
        store.record_usage(provider="p", model="m", input_tokens=3, output_tokens=2)
    manager = AssistantManager(ops_db=str(db_path), monthly_token_budget=5)
    config = SimpleNamespace(name="p", model="m", protocol="openai_compatible")
    try:
        with patch("src.ai.application.assistant_manager.resolve_config", return_value=config), pytest.raises(
            AssistantError, match="本月 Token 预算已用尽"
        ):
            manager.start_run(session_id, message="预算已满时不能创建运行")

        with AssistantStore(db_path) as store:
            assert store.list_messages(session_id) == []
            assert store.conn.execute("SELECT COUNT(*) AS count FROM ai_agent_runs").fetchone()["count"] == 0
    finally:
        manager.close()
