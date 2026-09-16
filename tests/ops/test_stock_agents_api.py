from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.ledger import StockAgentStore
from src.ops import OpsStore
from src.ops.api.stock_agents import build_stock_agents_router
from src.ops.application.stock_agent_service import ensure_stock_agent_jobs
from src.ops.domain.stock_agent import StockAgentConfig
from src.shared.tenancy import tenant_scope

BASE = "/api/ops/stock-agents"


def client(write=None):
    app = FastAPI()
    app.include_router(build_stock_agents_router(write_dependency=write or (lambda: None)))
    return TestClient(app)


def config():
    return StockAgentConfig(name="龙头选手", kind="leader").model_dump()


def test_create_read_fund_pause_and_history_contract():
    with client() as http:
        result = http.post(BASE, json=config())
        assert result.status_code == 201, result.text
        agent = result.json()
        identifier = agent["id"]
        assert agent["config"]["enabled"] is False
        assert http.get(BASE).json()["items"][0]["id"] == identifier
        assert "prompt" not in http.get(BASE).json()["items"][0]["config"]
        assert len(agent["schedules"]) == 5
        funds = {"amount_cents": 500_000, "request_id": "fund-api-one"}
        for _ in range(2):
            result = http.post(f"{BASE}/{identifier}/funds", json=funds)
            assert result.status_code == 200, result.text
        assert result.json()["state"]["cash_cents"] == 20_500_000
        assert result.json()["state"]["total_pnl_cents"] == 0
        assert http.get(f"{BASE}/{identifier}/history?kind=funding").json()["total"] == 2
        assert http.get(f"{BASE}/{identifier}/equity").json()["items"][-1]["pnl_cents"] == 0
        updated = http.put(f"{BASE}/{identifier}", json={"revision": agent["revision"], "config": {**agent["config"], "name": "接力计划"}})
        assert updated.status_code == 200, updated.text
        assert http.put(f"{BASE}/{identifier}", json={"revision": agent["revision"], "config": agent["config"]}).status_code == 409
        assert http.get(f"{BASE}/{identifier}/history?start=2026-09-20&end=2026-09-10").status_code == 422
        assert http.get(f"{BASE}/{identifier}/history?limit=1001").status_code == 422
        assert http.post(f"{BASE}/{identifier}/archive?revision={updated.json()['revision']}").status_code == 200
        assert http.get(BASE).json()["items"] == []
        assert http.get(BASE+"?include_archived=true").json()["items"][0]["archived"]
        assert http.get(f"{BASE}/{identifier}/history?kind=funding").json()["total"] == 2


def test_writes_require_existing_auth_dependency():
    def forbidden():
        raise HTTPException(403, "拒绝写入")
    with client(forbidden) as http:
        assert http.post(BASE, json=config()).status_code == 403
        assert http.put(BASE+"/guardian/storage", json={"days": 30, "max_entries": 2000, "cleanup_hours": 24}).status_code == 403
        assert http.post(BASE+"/guardian/cleanup").status_code == 403
        assert http.get(BASE).json()["items"] == []


def test_tenant_http_isolation_and_shared_guardian_stays_private():
    with client() as http:
        with tenant_scope("agent-tenant-one"):
            created = http.post(BASE, json=config())
            assert created.status_code == 201, created.text
            identifier = created.json()["id"]
            assert http.put(BASE+"/guardian/storage", json={"days": 90, "max_entries": 500, "cleanup_hours": 12}).status_code == 200
        with tenant_scope("agent-tenant-two"):
            assert http.get(BASE).json()["items"] == []
            assert http.get(BASE+"/"+identifier).status_code == 404
            assert http.post(f"{BASE}/{identifier}/funds", json={"amount_cents": 100, "request_id": "fund-foreign"}).status_code == 404
            assert http.get(BASE+"/guardian/storage").json()["retention"]["days"] == 30
        with tenant_scope("agent-tenant-one"):
            assert http.get(BASE+"/guardian/storage").json()["retention"]["days"] == 90
            assert http.get(BASE+"/guardian/overview").status_code == 200
            assert http.post(BASE+"/guardian/cleanup").status_code == 200


def test_model_required_and_funding_amounts_strict():
    with client() as http:
        assert http.post(BASE, json={**config(), "enabled": True}).status_code == 422
        assert http.post(BASE, json={**config(), "watch_limit": 4}).status_code == 422
        identifier = http.post(BASE, json=config()).json()["id"]
        for amount in (-1, 0, True, 1.2, "100"):
            assert http.post(f"{BASE}/{identifier}/funds", json={"amount_cents": amount, "request_id": "invalid-funds"}).status_code == 422


def test_managed_schedule_is_idempotent_and_pause_stops_all_five_jobs():
    with OpsStore(None) as ops, StockAgentStore() as ledger:
        agent = ledger.create({**config(), "enabled": True, "provider": "test", "model": "test"})
        ensure_stock_agent_jobs(ops)
        ensure_stock_agent_jobs(ops)
        jobs = [job for job in ops.list_jobs() if job["kind"] == "stock_agent"]
        assert len(jobs) == 5 and all(job["enabled"] for job in jobs)
        by_phase = {job["config"]["phase"]: job for job in jobs}
        assert by_phase["review"]["cron"] == "0 20 * * mon-fri"
        assert by_phase["auction"]["cron"] == "25 9 * * mon-fri"
        assert by_phase["premarket"]["cron"] == "50 8 * * mon-fri"
        assert by_phase["closeout"]["cron"] == "50,55 14 * * mon-fri"
        assert all(job["config"]["timezone"] == "Asia/Shanghai" for job in jobs)
        ledger.update_config(agent["id"], {**agent["config"], "enabled": False}, revision=1)
        ensure_stock_agent_jobs(ops)
        assert all(not job["enabled"] for job in ops.list_jobs() if job["kind"] == "stock_agent")
        assert [job for job in ops.list_jobs() if job["kind"] == "stock_agent_maintenance"][0]["enabled"]


def test_phase_gates_use_shanghai_not_machine_timezone():
    from src.ops.application.jobs.stock_agent import phase_allowed
    tz = ZoneInfo("Asia/Shanghai")
    assert phase_allowed("auction", datetime(2026, 9, 16, 9, 25, tzinfo=tz))
    assert not phase_allowed("intraday", datetime(2026, 9, 16, 9, 25, tzinfo=tz))
    assert not phase_allowed("intraday", datetime(2026, 9, 16, 12, 0, tzinfo=tz))
    assert phase_allowed("closeout", datetime(2026, 9, 16, 14, 50, tzinfo=tz))
    assert not phase_allowed("closeout", datetime(2026, 9, 16, 15, 0, tzinfo=tz))
    assert phase_allowed("review", datetime(2026, 9, 16, 20, 0, tzinfo=tz))
