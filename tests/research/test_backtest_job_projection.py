"""后台job只存run_id；同步读取run card仍保持完整HTTP契约。"""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.research.api import backtest_router as module
from src.research.infrastructure.backtest_jobs import ResearchBacktestJobStore


@pytest.mark.parametrize("endpoint", ["/api/research/backtest-jobs", "/api/research/backtest-runs"])
def test_background_uses_only_run_id_and_get_keeps_full_card(tmp_path, monkeypatch, endpoint):
    body = {
        "run_id": "run-projection", "strategy_slug": "demo", "status": "awaiting_human_review",
        "data_snapshot": {"source_evidence": {"linked": [{"label": "完整来源详情", "values": [1, 2, 3]}]}},
        "source_evidence": [{"provider": "fixture", "raw": "不能因job投影裁剪原始详情"}],
        "metrics": {"trades": 1}, "conclusion": {"status": "awaiting_human_review"},
    }
    card_to_dict = Mock(return_value=body)
    card = SimpleNamespace(run_id=body["run_id"], strategy_slug="demo", artifact_manifest=(),
                           to_dict=card_to_dict)
    outcome_to_dict = Mock(side_effect=AssertionError("后台不得展开完整outcome"))
    outcome = SimpleNamespace(run_card=card, to_dict=outcome_to_dict)
    backtest = Mock(return_value=outcome)
    monkeypatch.setattr(module, "run_research_backtest", backtest)
    engine = SimpleNamespace(backtest_config={}, strategy_revision="fixture-revision")
    monkeypatch.setattr("src.strategy.get", lambda _: engine)
    monkeypatch.setattr(module, "get_strategy", lambda _: engine)
    # 同步执行被提交的闭包，确定性验证后台结束后的状态；线程租户另有专门回归。
    monkeypatch.setattr(module, "submit_with_tenant", lambda _executor, call: call())
    jobs = ResearchBacktestJobStore(tmp_path / "jobs.json")
    cards = SimpleNamespace(root=tmp_path, require=lambda *_a, **_kw: card, list=lambda: [card])
    app = FastAPI()
    app.include_router(module.build_research_backtest_router(
        write_dependency=lambda: None,
        market_store_factory=lambda _: nullcontext(SimpleNamespace(market_revision=lambda: "fixture-market")),
        run_card_store_factory=lambda: cards,
        workflow_store_factory=lambda: SimpleNamespace(root=tmp_path),
        membership_store_factory=lambda: SimpleNamespace(),
        backtest_job_store_factory=lambda: jobs,
    ))
    request = {
        "strategy": "demo", "start": "2025-01-01", "end": "2025-12-31",
        "split": {"train_start": "2025-01-01", "train_end": "2025-06-30",
                  "oos_start": "2025-07-01", "oos_end": "2025-12-31"},
    }
    with TestClient(app) as client:
        submitted = client.post(endpoint, json=request)
        assert submitted.status_code == 202
        assert set(submitted.json()) == {"job"}
        assert submitted.json()["job"]["status"] == "queued"
        assert submitted.json()["job"]["run_id"] == ""
        job_id = submitted.json()["job"]["id"]
        status = client.get(f"/api/research/backtest-jobs/{job_id}")
        assert status.status_code == 200
        job = status.json()["job"]
        assert job["status"] == "completed" and job["run_id"] == body["run_id"]
        assert set(job) == {"id", "status", "request", "run_id", "error", "created_at", "updated_at"}
        outcome_to_dict.assert_not_called()
        card_to_dict.assert_not_called()
        backtest.assert_called_once()
        assert jobs.get(job_id) == job

        detail = client.get(f"/api/research/backtest-runs/{body['run_id']}")
        assert detail.status_code == 200
        for key, value in body.items():
            assert detail.json()[key] == value
        assert len(detail.json()["manifest_sha256"]) == 64
        card_to_dict.assert_called_once()

        listed = client.get("/api/research/backtest-runs")
        assert listed.status_code == 200 and listed.json()["total"] == 1
        for key, value in body.items():
            assert listed.json()["items"][0][key] == value
