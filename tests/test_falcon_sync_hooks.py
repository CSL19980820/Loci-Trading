"""配置和选股持久化 hooks：提交后同步、完整批次、失败不伪装原写失败。"""
from datetime import datetime
import sqlite3
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import src.ops as ops_api
from src.ledger import PalaceStore
from src.ops import OpsStore
from src.ops.api.jobs import build_jobs_router
from src.strategy.api.router import build_strategy_router
from src.strategy.api.screen_skills_router import build_screen_skills_router
from src.strategy.application.persist import persist_screen_candidates

SLUG = "qianlong-close-v3"


def client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def observed_sync(monkeypatch, events, *, source_slug=SLUG):
    def sync(ops, palace_path, **_kwargs):
        assert not ops.conn.in_transaction
        # 真实 BEGIN 能取得锁，证明 hook 不处于原 source 写事务内。
        ops.conn.execute("BEGIN IMMEDIATE")
        ops.conn.rollback()
        events.append({"job": ops.get_job_by_name("screen:" + source_slug),
                       "opted_out": ops.is_screen_job_opted_out(source_slug),
                       "palace_path": palace_path})
        return {"items": [], "lifecycle_ready": True}
    monkeypatch.setattr(ops_api, "sync_falcon_watch_pools", sync)


def test_strategy_job_off_reenable_and_unbind_sync_after_committed_switch(tmp_path, monkeypatch):
    events = []
    observed_sync(monkeypatch, events)
    api = client(build_strategy_router(write_dependency=lambda: None,
                                     ops_db=str(tmp_path / "ops.db"), palace_db=str(tmp_path / "palace.db")))
    path = f"/api/strategies/{SLUG}/job"
    assert api.put(path, json={"schedule_mode": "once", "enabled": True}).status_code == 200
    assert events[-1]["job"]["enabled"] and not events[-1]["opted_out"]
    first_id = events[-1]["job"]["id"]
    assert api.put(path, json={"schedule_mode": "once", "enabled": False}).status_code == 200
    assert events[-1]["job"]["id"] == first_id and not events[-1]["job"]["enabled"]
    assert events[-1]["opted_out"]
    assert api.put(path, json={"schedule_mode": "off"}).status_code == 200
    assert events[-1]["job"] is None and events[-1]["opted_out"]
    assert api.put(path, json={"schedule_mode": "once"}).status_code == 200
    assert events[-1]["job"]["enabled"] and not events[-1]["opted_out"]
    assert api.delete(path).status_code == 200
    assert events[-1]["job"] is None and events[-1]["opted_out"]
    assert len(events) == 5
    assert all(item["palace_path"] == str(tmp_path / "palace.db") for item in events)


def test_generic_screen_job_mutations_sync_but_unrelated_job_does_not(tmp_path, monkeypatch):
    events = []
    observed_sync(monkeypatch, events)
    monkeypatch.setattr(ops_api, "check_job_quota", lambda _store: None)
    api = client(build_jobs_router(write_dependency=lambda: None,
                                 ops_db=str(tmp_path / "ops.db"), palace_db=str(tmp_path / "palace.db")))
    job = api.post("/api/jobs", json={"name": "screen:" + SLUG, "kind": "screen",
                                     "config": {"strategy": SLUG}})
    assert job.status_code == 201
    job_id = job.json()["id"]
    assert events[-1]["job"]["enabled"] and not events[-1]["opted_out"]
    assert api.patch("/api/jobs/" + job_id, json={"enabled": False}).status_code == 200
    assert not events[-1]["job"]["enabled"] and events[-1]["opted_out"]
    assert api.patch("/api/jobs/" + job_id, json={"enabled": True}).status_code == 200
    assert events[-1]["job"]["enabled"] and not events[-1]["opted_out"]
    assert api.delete("/api/jobs/" + job_id).status_code == 200
    assert events[-1]["job"] is None and events[-1]["opted_out"]
    assert api.patch("/api/jobs/missing", json={"enabled": False}).status_code == 404
    assert api.post("/api/jobs", json={"name": "unrelated", "kind": "notify"}).status_code == 201
    assert len(events) == 4


@pytest.mark.parametrize("source,expected_calls", [("job:screen", 2), ("api:screen_run", 2),
                                                    ("api:screen_backfill", 0), ("api:screen:history", 0)])
def test_persist_sync_reads_complete_committed_batch_and_zero_result(tmp_path, monkeypatch, source, expected_calls):
    palace_path = str(tmp_path / "palace.db")
    observed = []
    def sync(ops, path, **_kwargs):
        assert ops.db_path == tmp_path / "ops.db" and path == palace_path
        with sqlite3.connect(path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            observed.append(conn.execute("SELECT COUNT(*) FROM candidate_reviews").fetchone()[0])
            conn.rollback()
        return {"items": [], "lifecycle_ready": True}
    monkeypatch.setattr(ops_api, "sync_falcon_watch_pools", sync)
    result = SimpleNamespace(strategy_slug=SLUG, trade_date="2026-09-30", entry_timing="next_open",
                             picks=[{"code": "600000", "factors": {}}, {"code": "600001", "factors": {}}],
                             watch_picks=[], params={})
    written = persist_screen_candidates(result, palace_db=palace_path, source=source)
    assert written["written"] == 2
    result.picks = []
    empty = persist_screen_candidates(result, palace_db=palace_path, source=source)
    assert empty["removed"] == (0 if source.endswith(":history") else 2)
    assert len(observed) == expected_calls
    if expected_calls:
        assert observed == [2, 0]


def test_sync_failure_preserves_successful_candidate_write_for_retry(tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("sync unavailable")
    monkeypatch.setattr(ops_api, "sync_falcon_watch_pools", broken)
    result = SimpleNamespace(strategy_slug=SLUG, trade_date="2026-09-30", entry_timing="next_open",
                             picks=[{"code": "600000", "factors": {}}], watch_picks=[], params={})
    response = persist_screen_candidates(result, palace_db=str(tmp_path / "palace.db"), source="job:screen")
    assert response["written"] == 1
    assert response["falcon_watch_sync"] == {"success": False, "pending_retry": True}
    with PalaceStore(tmp_path / "palace.db") as palace:
        assert len(palace.candidates_payload("2026-09-30")) == 1


def test_disabled_or_deleted_screen_package_sync_after_job_catalog_resync(tmp_path, monkeypatch):
    import src.strategy.application.screen_skills as screen_skills
    events = []
    observed_sync(monkeypatch, events, source_slug="formula-test")
    monkeypatch.setattr(OpsStore, "ensure_managed_screen_jobs", lambda _store: {})
    monkeypatch.setattr(screen_skills, "update_screen_skill", lambda slug, payload, **kwargs:
                        {"slug": slug, "enabled": payload.enabled})
    monkeypatch.setattr(screen_skills, "delete_screen_skill", lambda *args, **kwargs: True)
    with OpsStore(tmp_path / "ops.db") as store:
        store.create_job(name="screen:formula-test", kind="screen", config={"strategy": "formula-test"})
    api = client(build_screen_skills_router(write_dependency=lambda: None, ops_db=str(tmp_path / "ops.db")))
    payload = {"slug": "formula-test", "name": "测试公式", "description": "隔离公式开关",
               "code": "PICK:=CLOSE>OPEN;", "manifest": {}, "enabled": False,
               "expected_revision": "12345678"}
    assert api.put("/api/screen-skills/formula-test", json=payload).status_code == 200
    assert len(events) == 1
    assert api.request("DELETE", "/api/screen-skills/formula-test", json={"expected_revision": "12345678"}).status_code == 200
    assert events[-1]["job"] is None
    assert len(events) == 2


@pytest.mark.parametrize("default_path", [False, True])
def test_hourly_maintenance_syncs_before_diary_work_without_model_or_new_schedule(tmp_path, monkeypatch, default_path):
    import src.ops.application.falcon_watch_pool as watch_pool
    from src.ops.application.jobs import stock_agent_maintenance
    from src.ledger import StockAgentStore
    from src.ops.domain.stock_agent import StockAgentConfig
    events = []
    def sync(ops, path, **_kwargs):
        events.append((ops, path))
        return {"items": [], "lifecycle_ready": True}
    monkeypatch.setattr(watch_pool, "sync_falcon_watch_pools", sync)
    monkeypatch.setattr("src.shared.paths.palace_db", lambda: tmp_path / "palace.db")
    with StockAgentStore(tmp_path / "palace.db") as ledger:
        ledger.create(StockAgentConfig(name="暂停猎隼", kind="falcon", enabled=False).model_dump())
    with OpsStore(tmp_path / "ops.db") as ops:
        ctx = SimpleNamespace(ops_store=ops, palace_db=None if default_path else str(tmp_path / "palace.db"),
                              check_cancelled=lambda: None)
        response = stock_agent_maintenance.execute_stock_agent_maintenance({}, ctx)
        assert events == [(ops, str(tmp_path / "palace.db"))]
        assert response["falcon_watch_sync"]["lifecycle_ready"]
        assert len(response["agents"]) == 1


def test_actual_strategy_close_handler_clears_only_closed_source_watch_pool(tmp_path, monkeypatch):
    from src.ledger import StockAgentStore
    from src.ops.application.falcon_watch_pool import sync_falcon_watch_pools
    monkeypatch.setattr("src.ops.application.falcon_watch_pool.research_quotes", lambda *_a, **_k: {})
    from src.ops.domain.stock_agent import StockAgentConfig
    now = datetime(2026, 9, 30, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    palace_path, ops_path = str(tmp_path / "palace.db"), str(tmp_path / "ops.db")
    other = "sanyuan-tail-v1"
    with PalaceStore(palace_path) as palace:
        for code, slug in (("600000", SLUG), ("600001", other)):
            candidate = palace.record_candidate(code=code, name=code, decision="精选", reason="实际来源信号",
                occurred_on="2026-09-29", pool_id=f"{slug}@2026-09-29", strategy_slug=slug,
                rule_version=slug, score=80, source="job:screen")
            palace.conn.execute("UPDATE candidate_reviews SET created_at=? WHERE id=?",
                                ("2026-09-29T16:00:00+08:00", candidate))
        palace.conn.commit()
    with StockAgentStore(palace_path) as ledger:
        profile = ledger.create(StockAgentConfig(name="暂停猎隼", kind="falcon", enabled=False).model_dump())
    with OpsStore(ops_path) as ops:
        for slug in (SLUG, other):
            ops.create_job(name="screen:" + slug, kind="screen", config={"strategy": slug, "schedule": {"mode": "once"}})
        sync_falcon_watch_pools(ops, palace_path, as_of=now)
    with StockAgentStore(palace_path) as ledger:
        assert {item["code"] for item in ledger.get(profile["id"])["state"]["watchlist"]} == {"600000", "600001"}
    monkeypatch.setattr(ops_api, "sync_falcon_watch_pools", lambda ops, path, **kwargs:
                        sync_falcon_watch_pools(ops, path, as_of=now))
    api = client(build_strategy_router(write_dependency=lambda: None, ops_db=ops_path, palace_db=palace_path))
    assert api.put(f"/api/strategies/{SLUG}/job", json={"schedule_mode": "off"}).status_code == 200
    with StockAgentStore(palace_path) as ledger:
        after = ledger.get(profile["id"])
    assert [item["code"] for item in after["state"]["watchlist"]] == ["600001"]
    assert not after["config"]["enabled"] and after["total_trades"] == 0 and not after["state"]["positions"]
