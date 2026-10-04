"""HTTP手动运行先同步来源，再认领有效账户版本；无需调用模型。"""
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import StockAgentStore
from src.ops.api import stock_agents as api
from src.ops.application import falcon_watch_pool as pools
from src.ops.domain.stock_agent import StockAgentConfig
from src.ops.infrastructure.store import OpsStore

NOW = datetime.fromisoformat("2026-09-30T12:30:00+08:00")


def test_manual_claim_uses_account_version_after_automatic_pool_sync(tmp_path, monkeypatch):
    palace = tmp_path / "palace.db"
    ops_path = tmp_path / "ops.db"
    with StockAgentStore(palace) as ledger:
        original = ledger.create(StockAgentConfig(name="猎隼", kind="falcon", enabled=True,
                                                 provider="test", model="test-model").model_dump(), now=NOW)
    scope = {"as_of": NOW.isoformat(), "complete": True, "lifecycle_ready": True,
             "historical_review": False, "candidate_codes": ["600000"], "auto_observe_codes": ["600000"],
             "candidates": [{"code": "600000", "name": "测试候选", "origin": "quant", "strategy_slug": "test",
                             "source": "job:screen", "evidence_id": "candidate:test", "entry_eligible": True,
                             "date": "2026-09-29", "produced_at": "2026-09-29T16:00:00+08:00"}],
             "window": {"trading_days": 5, "dates": ["2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29", "2026-09-30"]}}
    monkeypatch.setattr(pools, "load_falcon_candidates", lambda *_a, **_k: scope)
    monkeypatch.setattr(pools, "research_quotes", lambda *_a, **_k: {})
    monkeypatch.setattr(api, "StockAgentStore", lambda: StockAgentStore(palace))
    monkeypatch.setattr(api, "OpsStore", lambda _: OpsStore(ops_path))
    monkeypatch.setattr(api, "agent_time", lambda: NOW)
    received = []

    def validate_claim(_tenant, profile, _phase, path, _target):
        with StockAgentStore(path) as ledger:
            fresh = ledger.assert_owner(profile["id"], profile["run_id"], now=NOW)
            assert [row["code"] for row in fresh["state"]["watchlist"]] == ["600000"]
            assert fresh["state_version"] == original["state_version"] + 1
            received.append(profile["run_id"])

    monkeypatch.setattr(api, "run_manual", validate_claim)
    app = FastAPI()
    app.include_router(api.build_stock_agents_router(write_dependency=lambda: True))
    with TestClient(app) as client:
        response = client.post(f"/api/ops/stock-agents/{original['id']}/run",
                               json={"phase": "research", "request_id": "manual-pool-sync"})
        assert response.status_code == 202, response.text
        assert received == [response.json()["run_id"]]
