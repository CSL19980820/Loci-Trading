from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.api.jobs import build_jobs_router
from src.ops.infrastructure.store import OpsStore


def test_batch_delete_rejects_a_running_job_run(tmp_path: Path) -> None:
    ops_db = tmp_path / "ops.db"
    with OpsStore(ops_db) as store:
        job_id = store.create_job(name="exclusive", kind="sync")
        job = store.get_job(job_id)
        assert job is not None
        run_id = store.start_run(job)

    app = FastAPI()
    app.include_router(build_jobs_router(write_dependency=lambda: None, ops_db=str(ops_db)))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/jobs/runs/batch-delete", json={"ids": [run_id]})

    assert response.status_code == 409
    assert "运行中的任务记录不可删除" in response.json()["detail"]
    with OpsStore(ops_db) as store:
        runs = store.list_runs(run_id=run_id)
        assert len(runs) == 1
        assert runs[0]["status"] == "running"
