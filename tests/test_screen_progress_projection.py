"""Progress polling excludes completed bulk results while full reads stay compatible."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.shared.tenancy import tenant_scope
from src.strategy.api.screen_run_router import build_screen_run_router
from src.strategy.application.screen_run_state import (
    _STATES, screen_run_snapshot, screen_run_snapshot_all, screen_run_update,
)


def test_progress_projection_keeps_state_and_does_not_mutate_full_results():
    with tenant_scope("progress-projection"):
        _STATES.pop("progress-projection", None)
        try:
            result = {"picks": [{"code": "000001", "factors": {"score": 90}}]}
            screen_run_update(strategy="completed", status="done", result=result, log_line="完成")
            screen_run_update(strategy="running", status="running", percent=35, log_line="读取行情")
            progress = screen_run_snapshot_all(include_results=False)
            assert progress["status"] == "running" and progress["running_strategies"] == ["running"]
            assert progress["result_omitted"] is True and "result" not in progress
            assert progress["runs"]["completed"]["log"] == ["完成"]
            assert all(slot["result_omitted"] and "result" not in slot for slot in progress["runs"].values())
            assert screen_run_snapshot("completed")["result"] is result
            progress["runs"]["completed"]["log"].append("caller change")
            assert screen_run_snapshot("completed")["log"] == ["完成"]
            with tenant_scope("other-progress-tenant"):
                assert screen_run_snapshot_all(include_results=False)["runs"] == {}
        finally:
            _STATES.pop("progress-projection", None)
            _STATES.pop("other-progress-tenant", None)


def test_http_progress_view_and_single_completed_result_read():
    app = FastAPI()
    app.include_router(build_screen_run_router(write_dependency=lambda: None))
    with tenant_scope("progress-http"):
        _STATES.pop("progress-http", None)
        try:
            screen_run_update(strategy="one", status="done", result={"picks": [{"code": "000001"}]})
            with TestClient(app) as client:
                progress = client.get("/api/screen/run", params={"view": "progress"}).json()
                assert "result" not in progress and "result" not in progress["runs"]["one"]
                full = client.get("/api/screen/run", params={"strategy": "one"}).json()
                assert full["result"]["picks"] == [{"code": "000001"}]
                assert "result_omitted" not in full
                assert client.get("/api/screen/run", params={"view": "invalid"}).status_code == 422
        finally:
            _STATES.pop("progress-http", None)
