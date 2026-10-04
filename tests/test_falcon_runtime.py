"""猎隼的调度、完整复盘窗口及日记到账户记忆闭环（隔离数据库）。"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.ledger import StockAgentStore
from src.ops.application import stock_agent_service as service
from src.ops.application.falcon_review_evidence import falcon_review_evidence
from src.ops.application.jobs import stock_agent as runtime
from src.ops.application.jobs.context import JobContext
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.stock_agent_prompts import FALCON_PHASE_PROMPTS
from src.ops.application.trading_prompts import trading_prompt
from src.ops.domain.stock_agent import StockAgentConfig
from src.ops.infrastructure.store import OpsStore

NOW = datetime.fromisoformat("2026-09-30T20:00:00+08:00")


def test_templates_and_old_schedules_do_not_enable_new_work(monkeypatch):
    import src.ops.application.guardian_config as guardian
    monkeypatch.setattr(guardian, "get_config", lambda _: {"provider": "test", "model": "test-model"})
    templates = service.stock_agent_templates(None)
    assert templates["falcon"]["name"] == "猎隼"
    assert templates["falcon"]["schedule"]["weekly_review_enabled"]
    assert not templates["falcon"]["enabled"]
    assert "weekly_review" not in {row["phase"] for row in service.schedules({"config": templates["custom"]})}
    assert next(row for row in service.schedules({"config": templates["falcon"]}) if row["phase"] == "weekly_review")["cron"] == "30 20 * * fri"
    cfg = StockAgentConfig.model_validate(templates["falcon"]).model_dump()
    assert trading_prompt(cfg, "weekly_review") == cfg["common_prompt"] + "\n\n" + cfg["weekly_review_prompt"]
    assert cfg["premarket_prompt"] not in trading_prompt(cfg, "weekly_review")


def test_weekly_holiday_gate_and_historical_boundaries(monkeypatch):
    monkeypatch.setattr(runtime, "calendar_trading_day", lambda _: False)
    holiday = NOW.replace(month=10, day=2)
    assert runtime.research_scope("weekly_review", holiday)["research_date"] == "2026-10-02"
    assert runtime.research_scope("weekly_review", holiday, "2026-09-27")["historical_review"]
    with pytest.raises(ValueError, match="休市"):
        runtime.research_scope("review", holiday)
    with pytest.raises(ValueError):
        runtime.research_scope("weekly_review", holiday, "2026-10-03")
    with pytest.raises(ValueError):
        runtime.research_scope("weekly_review", holiday.replace(hour=10))


def test_immediate_research_is_allowed_during_lunch_without_trade_gate(monkeypatch):
    monkeypatch.setattr(runtime, "calendar_trading_day", lambda _: False)
    lunch = NOW.replace(hour=12)
    assert runtime.phase_allowed("research", lunch)
    scope = runtime.research_scope("research", lunch)
    assert scope["research_date"] == lunch.date().isoformat()
    assert not runtime.phase_allowed("intraday", lunch)
    with pytest.raises(ValueError):
        runtime.research_scope("research", lunch, "2026-09-29")


def test_weekly_schedule_disable_retires_previous_job(tmp_path):
    cfg = StockAgentConfig(name="猎隼", kind="falcon", enabled=True, provider="test", model="test-model",
                          schedule={"weekly_review_enabled": True}).model_dump()
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(cfg, now=NOW)
    with OpsStore(tmp_path / "ops.db") as ops:
        service.ensure_stock_agent_jobs(ops, palace_path=path)
        name = f"股票智能体:{profile['id']}:weekly_review"
        assert ops.get_job_by_name(name)["config"]["phase"] == "weekly_review"
        assert ops.get_job_by_name(name)["enabled"]
        with StockAgentStore(path) as ledger:
            cfg["schedule"]["weekly_review_enabled"] = False
            ledger.update_config(profile["id"], cfg, revision=profile["revision"])
        service.ensure_stock_agent_jobs(ops, palace_path=path)
        assert not ops.get_job_by_name(name)["enabled"]


def test_weekly_review_reads_all_pages_and_excludes_future_completion():
    rows = [{"id": f"r{i}", "finished_at": NOW.isoformat(), "status": "success"} for i in range(120)]
    rows.append({"id": "future", "finished_at": NOW.replace(hour=21).isoformat(), "status": "success"})
    calls = []

    def history(agent_id, *, kind, start, end, limit, offset):
        calls.append((kind, start, end, offset))
        items = rows if kind == "runs" else []
        return {"items": items[offset:offset+limit], "total": len(items)}

    ledger = SimpleNamespace(history=history, run_detail=lambda *_: {"detail": {"decisions": [], "fills": [], "candidate_scope": {}}})
    scope = {"research_date": "2026-09-30", "research_cutoff": NOW.isoformat()}
    result = falcon_review_evidence(ledger, "mine", "weekly_review", scope)
    assert len(result["runs"]) == 120
    assert ("runs", "2026-09-28", "2026-09-30", 100) in calls
    assert all(row["id"] != "future" for row in result["runs"])


def test_review_memory_persists_and_is_injected_into_next_run(tmp_path, monkeypatch):
    import src.ledger.infrastructure.stock_agent_store as agent_store
    import src.ledger.infrastructure.stock_agent_history as agent_history
    import src.ops.application.stock_agent_decide as model
    import src.ops.application.stock_agent_notify as notify
    import src.ops.application.falcon_candidates as candidates
    clock = [NOW]
    monkeypatch.setattr(runtime, "agent_time", lambda: clock[0])
    monkeypatch.setattr(agent_store, "agent_now", lambda value=None: value or clock[0])
    monkeypatch.setattr(agent_history, "agent_now", lambda value=None: value or clock[0])
    monkeypatch.setattr(runtime, "calendar_trading_day", lambda _: True)
    monkeypatch.setattr(notify, "notify_stock_agent", lambda *_: {"skipped": "test_no_send"})
    snapshot = {"as_of": NOW.isoformat(), "candidate_codes": ["600000"], "research_codes": ["600000"],
                "candidates": [{"code": "600000", "evidence_id": "candidate:123", "score": 80}], "warnings": []}
    monkeypatch.setattr(candidates, "load_falcon_candidates", lambda *_args, **_kwargs: snapshot)
    payloads = []
    lesson = {"id": "timing-1", "title": "高分仍需等待承接", "finding": "当前样本未确认承接，择时仍待验证",
              "conditions": "风险偏好走弱时", "status": "pending", "evidence_refs": ["candidate:123"],
              "sample_size": 1, "sample_basis": "observed", "sample_definition": "当日一只已产出候选",
              "validation_plan": "对比相同信号时点的等待与开盘参与，并记录反例"}

    def decide(_store, _profile, payload, **_kwargs):
        payloads.append(payload)
        learning = {"lessons": [lesson]} if payload["phase"] == "review" and not payload["historical_review"] else None
        return StockAgentDecision(summary="保留观察，等待证据", orders=[], research_plan="继续核验承接", learning=learning), {}

    monkeypatch.setattr(model, "decide_stock_agent", decide)
    path = str(tmp_path / "palace.db")
    cfg = StockAgentConfig(name="猎隼", kind="falcon", provider="test", model="test-model", enabled=True,
                          **FALCON_PHASE_PROMPTS).model_dump()
    with StockAgentStore(path) as ledger:
        profile = ledger.create(cfg, now=NOW)
        claimed = ledger.claim_run(profile["id"], NOW.date().isoformat()+":review:1", "review", now=NOW)
    with OpsStore(tmp_path / "ops.db") as ops:
        result = runtime.run_claimed(claimed, "review", JobContext(ops_store=ops, palace_db=path), path)
        assert result["ledger_committed"] and result["fills"] == 0
        with StockAgentStore(path) as ledger:
            saved = ledger.get(profile["id"])
            assert saved["state"]["falcon_learning"]["lessons"][0]["id"] == "timing-1"
            detail = ledger.run_detail(profile["id"], claimed["run_id"])["detail"]
            assert detail["candidate_scope"] == snapshot
            assert detail["learning"]["lessons"][0]["id"] == "timing-1"
            assert len(detail["learning_changes"]) == 1
            clock[0] = NOW.replace(day=1, month=10, hour=8, minute=50)
            claimed = ledger.claim_run(profile["id"], clock[0].date().isoformat()+":premarket:1", "premarket", now=clock[0])
        runtime.run_claimed(claimed, "premarket", JobContext(ops_store=ops, palace_db=path), path)
        with StockAgentStore(path) as ledger:
            assert ledger.run_detail(profile["id"], claimed["run_id"])["detail"]["learning_changes"] == []
        clock[0] = clock[0].replace(hour=20, minute=0)
        with StockAgentStore(path) as ledger:
            before = ledger.get(profile["id"])["state"]
            before["watchlist"] = [{"code": "600001", "name": "研究日后加入", "added_at": clock[0].isoformat()}]
            import json
            ledger.conn.execute("UPDATE stock_agent_profiles SET state_json=? WHERE id=?", (json.dumps(before), profile["id"]))
            claimed = ledger.claim_run(profile["id"], clock[0].date().isoformat()+":historical:1", "review", now=clock[0])
        runtime.run_claimed(claimed, "review", JobContext(ops_store=ops, palace_db=path), path, "2026-09-29")
        with StockAgentStore(path) as ledger:
            after = ledger.get(profile["id"])["state"]
            assert after["research_plan"] == before["research_plan"]
            assert after["research_plan_date"] == before["research_plan_date"]
            assert after["falcon_learning"] == before["falcon_learning"]
            assert ledger.run_detail(profile["id"], claimed["run_id"])["detail"]["learning_changes"] == []
    assert payloads[1]["learning"]["lessons"][0]["id"] == "timing-1"
    assert "falcon_learning" not in payloads[1]["portfolio"]
    assert not payloads[2]["recent_work"] and not payloads[2]["research_plan"]
    assert not payloads[2]["portfolio"]["historical_snapshot_available"]
    assert "cash_cents" not in payloads[2]["portfolio"]
    assert not payloads[2]["learning"]["lessons"]
    assert payloads[2]["watch_snapshot"] == {"quotes": {}, "missing_codes": []}


def test_legacy_prompt_selection_stays_unchanged():
    config = {"prompt": "intraday", "review_prompt": "daily", "common_prompt": "identity"}
    assert trading_prompt(config, "review") == "identity\n\ndaily"
    assert trading_prompt(config, "intraday") == "identity\n\nintraday"


def test_http_creation_and_legacy_update_preserve_weekly_configuration(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ops.api import stock_agents as api

    palace = tmp_path / "palace.db"
    ops_path = tmp_path / "ops.db"
    monkeypatch.setattr(api, "StockAgentStore", lambda: StockAgentStore(palace))
    monkeypatch.setattr(api, "OpsStore", lambda _: OpsStore(ops_path))
    app = FastAPI()
    app.include_router(api.build_stock_agents_router(write_dependency=lambda: True))
    cfg = StockAgentConfig(name="猎隼", kind="falcon", **FALCON_PHASE_PROMPTS,
                          schedule={"weekly_review_enabled": True, "weekly_review_time": "21:10"}).model_dump()
    with TestClient(app) as client:
        created = client.post("/api/ops/stock-agents", json=cfg)
        assert created.status_code == 201, created.text
        profile = created.json()
        assert profile["config"]["kind"] == "falcon"
        old_client_config = dict(cfg)
        old_client_config.pop("weekly_review_prompt")
        old_client_config["schedule"] = {key: value for key, value in cfg["schedule"].items() if not key.startswith("weekly_")}
        updated = client.put(f"/api/ops/stock-agents/{profile['id']}", json={"revision": profile["revision"], "config": old_client_config})
        assert updated.status_code == 200, updated.text
        saved = updated.json()["config"]
        assert saved["weekly_review_prompt"] == FALCON_PHASE_PROMPTS["weekly_review_prompt"]
        assert saved["schedule"]["weekly_review_enabled"]
        assert saved["schedule"]["weekly_review_time"] == "21:10"
