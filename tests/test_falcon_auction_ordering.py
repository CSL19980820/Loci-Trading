"""同槽选股必须先完成；等待不占执行线程，也不提前认领智能体轮次。"""
from datetime import datetime, timedelta

import pytest

from src.ledger import StockAgentConflict, StockAgentStore
from src.ops.application.falcon_auction_inputs import falcon_auction_inputs
from src.ops.application.jobs import stock_agent as runtime
from src.ops.application.jobs.context import JobContext, JobSkipped
from src.ops.domain.stock_agent import StockAgentConfig
from src.ops.infrastructure.scheduler import JobScheduler
from src.ops.infrastructure.store import OpsStore
from src.shared.tenancy import PRIMARY_TENANT

NOW = datetime.fromisoformat("2026-09-30T09:25:00+08:00")
SLUG = "double-volume-yin-low-open-v1"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import src.ledger.infrastructure.stock_agent_store as agent_store
    import src.ops.application.falcon_candidates as candidates
    import src.ops.infrastructure.store_runs as runs

    clock = [NOW]
    monkeypatch.setattr(runtime, "agent_time", lambda: clock[0])
    monkeypatch.setattr(runtime, "calendar_trading_day", lambda _: True)
    monkeypatch.setattr("src.market.calendar_trading_day", lambda _: True)
    monkeypatch.setattr(agent_store, "agent_now", lambda value=None: value or clock[0])
    monkeypatch.setattr(runs, "_now", lambda: clock[0].isoformat())
    monkeypatch.setattr(candidates, "get_screen_package", lambda _: None)
    monkeypatch.setattr(candidates, "is_builtin_registered", lambda _: True)
    monkeypatch.setattr(runtime, "sync_falcon_watch_pools", lambda *_a, **_k: {})
    palace, ops_path = str(tmp_path / "palace.db"), str(tmp_path / "ops.db")
    with StockAgentStore(palace) as ledger:
        profile = ledger.create(StockAgentConfig(name="猎隼", kind="falcon", enabled=True,
            provider="fixture", model="fixture").model_dump(), now=NOW)
    with OpsStore(ops_path) as ops:
        source_id = ops.create_job(name="screen:" + SLUG, kind="screen", cron="25 9 * * mon-fri",
            config={"strategy": SLUG, "record_candidates": True})
        cfg = {"agent_id": profile["id"], "phase": "auction", "revision": profile["revision"]}
        job_id = ops.create_job(name="股票智能体:auction", kind="stock_agent", cron="25 9 * * mon-fri", config=cfg)
        yield clock, palace, ops, profile, cfg, source_id, job_id


def test_expected_slot_waits_before_source_starts_and_ignores_yesterday(setup):
    clock, _, ops, _, _, source_id, _ = setup
    clock[0] -= timedelta(days=1)
    run_id = ops.start_run(ops.get_job(source_id))
    ops.finish_run(run_id, status="success", result={"picks": []})
    clock[0] = NOW
    assert falcon_auction_inputs(ops, now=NOW) == {"pending": ["screen:" + SLUG], "failed": []}
    run_id = ops.start_run(ops.get_job(source_id))
    assert falcon_auction_inputs(ops, now=NOW)["pending"]
    # 零候选是已完成选股，不能因此永远等待。
    ops.finish_run(run_id, status="success", result={"picks": [], "recorded": {"written": 0}})
    assert falcon_auction_inputs(ops, now=NOW) == {"pending": [], "failed": []}


@pytest.mark.parametrize("status", ["failed", "cancelled", "timed_out", "skipped"])
def test_failed_source_stops_auction_without_claim_or_retry(setup, monkeypatch, status):
    _, palace, ops, profile, cfg, source_id, job_id = setup
    run_id = ops.start_run(ops.get_job(source_id))
    ops.finish_run(run_id, status=status)
    scheduler = JobScheduler(db_path=str(ops.db_path))
    assert not scheduler._defer_falcon_auction(PRIMARY_TENANT, ops, ops.get_job(job_id),
                                              JobContext(palace_db=palace), now=NOW)
    with pytest.raises(JobSkipped, match="竞价选股来源未成功"):
        runtime.execute_stock_agent(cfg, JobContext(ops_store=ops, palace_db=palace))
    assert not scheduler._scheduler.get_jobs()
    with StockAgentStore(palace) as ledger:
        assert ledger.history(profile["id"])["items"] == []


@pytest.mark.parametrize("change", ["disabled", "opted_out", "off", "later", "not_recording", "interval_outside"])
def test_inactive_or_not_due_sources_do_not_block(setup, change):
    _, _, ops, _, _, source_id, _ = setup
    config = ops.get_job(source_id)["config"]
    if change == "disabled":
        ops.update_job(source_id, enabled=False)
    elif change == "opted_out":
        ops.set_screen_job_opt_out(SLUG)
    elif change == "later":
        ops.update_job(source_id, cron="30 15 * * mon-fri")
    else:
        if change == "off":
            config["schedule"] = {"mode": "off"}
        elif change == "not_recording":
            config["record_candidates"] = False
        else:
            config["schedule"] = {"mode": "interval", "window_start_hour": 9, "window_start_minute": 30}
        ops.update_job(source_id, config=config)
    assert falcon_auction_inputs(ops, now=NOW) == {"pending": [], "failed": []}


def test_utc_legacy_run_time_is_compared_on_same_timeline(setup):
    _, _, ops, _, _, source_id, _ = setup
    run_id = ops.start_run(ops.get_job(source_id))
    ops.conn.execute("UPDATE job_runs SET started_at=? WHERE id=?", ("2026-09-30 01:25:00", run_id))
    ops.conn.commit()
    ops.finish_run(run_id, status="success")
    assert falcon_auction_inputs(ops, now=NOW) == {"pending": [], "failed": []}


def test_scheduler_defers_without_ops_or_ledger_claim_then_uses_refreshed_state(setup, monkeypatch, request):
    clock, palace, ops, profile, _, source_id, job_id = setup
    scheduler = JobScheduler(db_path=str(ops.db_path), context_factory=lambda: JobContext(palace_db=palace))
    scheduler._scheduler.start(paused=True)
    request.addfinalizer(lambda: scheduler._scheduler.shutdown(wait=False))
    scheduler._run(job_id, now=NOW)
    retry = scheduler._scheduler.get_jobs()[0]
    assert retry.id.endswith(":auction-inputs")
    assert retry.args == (PRIMARY_TENANT, job_id)
    assert ops.list_runs(job_id=job_id) == []
    with StockAgentStore(palace) as ledger:
        assert ledger.get(profile["id"])["active_run"] is None
        assert ledger.history(profile["id"])["items"] == []
    source_run = ops.start_run(ops.get_job(source_id))
    scheduler._run(job_id, now=NOW)
    assert len(scheduler._scheduler.get_jobs()) == 1
    assert ops.list_runs(job_id=job_id) == []
    clock[0] += timedelta(seconds=6)
    with StockAgentStore(palace) as ledger:
        ledger.update_falcon_watch_pool(profile["id"], lambda state: {**state,
            "watchlist": [{"code": "002799", "name": "来源完成后加入"}]}, now=clock[0])
        expected_version = ledger.get(profile["id"])["state_version"]
    ops.finish_run(source_run, status="success", result={"recorded": {"written": 1}})
    claimed = []

    def run(profile, *_a, **_k):
        claimed.append(profile)
        assert profile["state_version"] == expected_version
        assert profile["state"]["watchlist"][0]["code"] == "002799"
        with StockAgentStore(palace) as ledger:
            ledger.assert_owner(profile["id"], profile["run_id"])
        return {"ledger_committed": True}

    monkeypatch.setattr(runtime, "run_claimed", run)
    scheduler._run(job_id, now=clock[0])
    assert len(claimed) == 1
    assert ops.list_runs(job_id=job_id)[0]["status"] == "success"
    scheduler._run(job_id, now=clock[0])
    assert len(claimed) == 1
    # 来源继续变化时旧 owner 仍必须失效，不能以时序修复为由放宽最终提交。
    with StockAgentStore(palace) as ledger:
        ledger.update_falcon_watch_pool(profile["id"], lambda state: {**state, "watchlist": []}, now=clock[0])
        with pytest.raises(StockAgentConflict):
            ledger.assert_owner(profile["id"], claimed[0]["run_id"])


def test_missing_source_stops_retry_at_auction_deadline(setup):
    clock, palace, ops, profile, _, _, job_id = setup
    scheduler = JobScheduler(db_path=str(ops.db_path), context_factory=lambda: JobContext(palace_db=palace))
    clock[0] = NOW.replace(minute=29, second=50)
    scheduler._run(job_id, now=clock[0])
    assert not scheduler._scheduler.get_jobs()
    assert ops.list_runs(job_id=job_id)[0]["status"] == "skipped"
    with StockAgentStore(palace) as ledger:
        assert ledger.history(profile["id"])["items"] == []


def test_sync_crossing_window_does_not_claim(setup, monkeypatch):
    clock, palace, ops, profile, cfg, source_id, _ = setup
    run_id = ops.start_run(ops.get_job(source_id))
    ops.finish_run(run_id, status="success")
    monkeypatch.setattr(runtime, "sync_falcon_watch_pools",
                        lambda *_a, **_k: clock.__setitem__(0, NOW.replace(minute=30)))
    with pytest.raises(JobSkipped, match="竞价研判限"):
        runtime.execute_stock_agent(cfg, JobContext(ops_store=ops, palace_db=palace))
    with StockAgentStore(palace) as ledger:
        assert ledger.history(profile["id"])["items"] == []


def test_reload_keeps_pending_retry_and_disabling_removes_it(setup, monkeypatch, request):
    import src.ops.infrastructure.scheduler as scheduler_module
    _, palace, ops, _, _, _, job_id = setup
    monkeypatch.setattr(scheduler_module, "active_tenant_roster", lambda: {
        "tenants": [PRIMARY_TENANT], "total": 1, "truncated": False, "degraded": False})
    monkeypatch.setattr(scheduler_module, "tenant_job_rows", lambda *_a, **_k: ops.list_jobs(enabled_only=True))
    scheduler = JobScheduler(db_path=str(ops.db_path), context_factory=lambda: JobContext(palace_db=palace))
    scheduler._scheduler.start(paused=True)
    request.addfinalizer(lambda: scheduler._scheduler.shutdown(wait=False))
    scheduler._run(job_id, now=NOW)
    scheduler.reload()
    assert len([job for job in scheduler._scheduler.get_jobs() if job.id.endswith(":auction-inputs")]) == 1
    ops.update_job(job_id, enabled=False)
    scheduler.reload()
    assert not [job for job in scheduler._scheduler.get_jobs() if job.id.endswith(":auction-inputs")]


def test_tenant_retry_releases_gate_and_preserves_tenant_route(setup, monkeypatch):
    import src.ops.infrastructure.scheduler as scheduler_module
    from src.shared.tenancy import current_tenant
    _, palace, ops, _, _, _, job_id = setup
    scopes = []

    def tenant_store(_path):
        scopes.append(current_tenant())
        return OpsStore(ops.db_path)

    monkeypatch.setattr(scheduler_module, "OpsStore", tenant_store)
    scheduler = JobScheduler(db_path=str(ops.db_path), context_factory=lambda: JobContext(palace_db=palace))
    scheduler._run_tenant("tenant-ordering", job_id, now=NOW)
    retry = scheduler._scheduler.get_jobs()[0]
    assert scopes == ["tenant-ordering"]
    assert retry.executor == scheduler_module.TENANT_EXECUTOR
    assert retry.args == ("tenant-ordering", job_id)
    assert scheduler._job_index[retry.id] == ("tenant-ordering", job_id)
    assert scheduler._tenant_gate.acquire(blocking=False)
    scheduler._tenant_gate.release()
    assert ops.list_runs(job_id=job_id) == []


def test_manual_auction_rejects_unready_inputs_before_claim(setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ops.api import stock_agents as api
    _, palace, ops, profile, _, _, _ = setup
    monkeypatch.setattr(api, "agent_time", lambda: NOW)
    monkeypatch.setattr(api, "StockAgentStore", lambda: StockAgentStore(palace))
    monkeypatch.setattr(api, "OpsStore", lambda _: OpsStore(ops.db_path))
    app = FastAPI()
    app.include_router(api.build_stock_agents_router(write_dependency=lambda: True))
    with TestClient(app) as client:
        result = client.post(f"/api/ops/stock-agents/{profile['id']}/run",
                             json={"phase": "auction", "request_id": "auction-test"})
    assert result.status_code == 409
    assert "等待竞价选股完成" in result.json()["detail"]
    with StockAgentStore(palace) as ledger:
        assert ledger.history(profile["id"])["items"] == []
