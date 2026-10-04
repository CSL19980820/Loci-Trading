"""双阶段候选流程的入口、闭市准备、租户与来源证据契约。"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import sys
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import src.market as market_api
import src.ops as ops_api
import src.strategy as strategy_api
from src.ledger import PalaceStore
from src.market import MarketStore
from src.ops import OpsStore
from src.ops.application.jobs.context import JobContext, JobError, JobSkipped
from src.ops.application.jobs.screen import execute_screen
from src.ops.application.jobs import screen_prepare
from src.shared.tenancy import tenant_scope
from src.strategy.api import router as strategy_router
from src.strategy.api import screen_today_router
from src.strategy.application import screen_run
from src.strategy.application.screener import ScreenResult
from src.strategy.domain.base import StrategyError

SLUG = "double-volume-yin-low-open-v1"
DAY = "2026-09-30"


def forbidden(*_args, **_kwargs):
    raise AssertionError("晨间入口禁止读取本地行情或触发同步")


@pytest.fixture
def flow(tmp_path, monkeypatch):
    engine = SimpleNamespace(
        slug=SLUG, name="大涨倍量阴次日低开", requires_realtime_inputs=True,
        screen_staggered=False, screen_push_wecom=False, screen_default_top_n=2,
        screen_allowed_boards=("main",),
        default_universe={"preset": "default_a_share", "boards": ["main"]},
        screen_schedule={"mode": "once", "run_hour": 9, "run_minute": 25},
        screen_prepare_schedule={"mode": "once", "run_hour": 15, "run_minute": 30},
        screen_job_config={"snapshot_time": "09:25", "snapshot_grace_minutes": 5,
                           "trading_days_only": True, "requires_realtime_inputs": True},
    )
    result = ScreenResult(
        strategy_slug=SLUG, strategy_revision="revision-fixture", trade_date=DAY,
        entry_timing="open", universe_size=5,
        picks=[{"code": "600001", "name": "现场名称甲", "open": 10.0, "close": 10.0,
                "factors": {"score": 91.2, "低位分": 40.0, "板块分散组": "科技"}},
               {"code": "600002", "name": "现场名称乙", "open": 12.0, "close": 12.0,
                "factors": {"score": 86.4, "均线距离分": 30.0, "板块分散组": "工业"}}],
        params={"top_n": 2}, effective_params={"top_n": 2},
        data_snapshot={"status": "success", "input_mode": "prepared_pool_and_live_auction",
                       "as_of": "2026-09-29", "quote_source": "sina",
                       "quote_observed_at": DAY + "T09:25:01+08:00"},
    )
    calls = []
    module = ModuleType("src.strategy.application.double_yin_realtime")

    def runner(current, **kwargs):
        assert current is engine
        calls.append(kwargs)
        return result

    module.screen_live_double_yin = runner
    module.prepare_double_yin_pool = lambda *_args, **_kwargs: forbidden()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(strategy_api, "get", lambda _slug: engine)
    monkeypatch.setattr(strategy_api, "all_strategies", lambda: [engine])
    monkeypatch.setattr(ops_api, "sync_falcon_watch_pools", lambda *_args, **_kwargs: {})
    monkeypatch.setenv("LOCI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCI_CONFIG_JSON", str(tmp_path / "missing-config.json"))
    return SimpleNamespace(engine=engine, result=result, runner_module=module, calls=calls,
                           palace=str(tmp_path / "palace.db"), ops=str(tmp_path / "ops.db"))


@pytest.mark.parametrize("endpoint", ["job", "sync", "today", "async"])
def test_all_morning_entrypoints_use_live_runner_and_preserve_selected_evidence(flow, monkeypatch, endpoint):
    monkeypatch.setattr(MarketStore, "__init__", forbidden)
    monkeypatch.setattr(JobContext, "market", forbidden)
    monkeypatch.setattr(JobContext, "market_hot", forbidden)
    monkeypatch.setattr(strategy_router, "market_store", forbidden)
    monkeypatch.setattr(screen_today_router, "market_store", forbidden)
    monkeypatch.setattr(screen_today_router, "market_hot_store", forbidden)
    monkeypatch.setattr(screen_today_router, "should_sync_today", forbidden)
    opts = {"strategy": SLUG, "record_candidates": True, "push_wecom": True,
            "use_ai_pick": True, "top_n": 1}
    if endpoint == "job":
        body = execute_screen(opts, JobContext(palace_db=flow.palace))
    elif endpoint == "async":
        screen_run.execute_screen_run(opts, market_factory=forbidden, palace_db=flow.palace)
        snap = screen_run.screen_run_snapshot(SLUG)
        assert snap["status"] == "done", snap
        body = snap["result"]
    else:
        app = FastAPI()
        app.include_router(strategy_router.build_strategy_router(
            write_dependency=lambda: None, ops_db=flow.ops, palace_db=flow.palace,
        ))
        with TestClient(app) as api:
            response = (api.post("/api/strategies/screen", json={key: value for key, value in opts.items()
                                                               if key not in {"push_wecom", "use_ai_pick"}}) if endpoint == "sync"
                        else api.get("/api/screen/today", params={"strategy": SLUG, "force_sync": True}))
        assert response.status_code == 200, response.text
        body = response.json()
    assert len(flow.calls) == 1
    assert body["picks"] == flow.result.picks
    assert body["data_snapshot"]["quote_source"] == "sina"
    assert body["recorded"]["written"] == 2
    with PalaceStore(flow.palace) as ledger:
        rows = ledger.candidates_payload(DAY, include_backfill=True)
    assert {row["name"] for row in rows} == {"现场名称甲", "现场名称乙"}
    assert {row["score"] for row in rows} == {91.2, 86.4}
    assert all(row["evidence"]["_data_snapshot"]["quote_source"] == "sina" for row in rows)


def test_user_limit_is_passed_to_runner_but_not_applied_again(flow):
    body = screen_run.execute_realtime_screen(
        flow.engine, {"strategy": SLUG, "top_n": 1, "record_candidates": False},
        palace_db=flow.palace, source="api:screen",
    )
    assert flow.calls[-1]["params"] == {"top_n": 1}
    assert len(body["picks"]) == 2


def test_candidate_persistence_resolves_current_tenant_for_each_call(flow, tmp_path, monkeypatch):
    from src.shared.paths import palace_db

    monkeypatch.delenv("PALACE_DB", raising=False)
    paths = []
    for tenant in ("sample-owner-a", "sample-owner-b"):
        with tenant_scope(tenant):
            paths.append(palace_db())
            body = screen_run.execute_realtime_screen(
                flow.engine, {"strategy": SLUG}, palace_db=None, source="api:screen",
            )
            assert body["recorded"]["written"] == 2
    assert paths[0] != paths[1]
    assert all(str(path).startswith(str(tmp_path)) for path in paths)
    for path in paths:
        with PalaceStore(path) as ledger:
            assert len(ledger.candidates_payload(DAY, include_backfill=True)) == 2


def test_ordinary_strategy_keeps_existing_tenant_stagger(flow):
    from src.ops.application.ensure_screen_jobs import _schedule_for_engine
    from src.ops.application.job_stagger import staggered_minute

    normal = SimpleNamespace(slug="legacy-strategy")
    with tenant_scope("integration-member"):
        schedule = _schedule_for_engine(normal, {"mode": "once", "run_hour": 15, "run_minute": 30})
        assert schedule["run_hour"] == 15 and schedule["run_minute"] == staggered_minute(30)


def test_multiday_request_is_rejected_before_live_fetch(flow):
    with pytest.raises(StrategyError, match="实时单日"):
        screen_run.execute_realtime_screen(
            flow.engine, {"strategy": SLUG, "start": "2026-09-29", "end": DAY},
            palace_db=flow.palace, source="api:screen",
        )
    assert not flow.calls


def test_non_trading_day_does_not_clear_or_write_candidates(flow, monkeypatch):
    flow.result.data_snapshot = {"status": "skipped_non_trading_day", "reason": "休市"}
    from src.strategy.application import persist
    monkeypatch.setattr(persist, "persist_screen_candidates", forbidden)
    with pytest.raises(JobSkipped, match="休市"):
        execute_screen({"strategy": SLUG, "record_candidates": True}, JobContext(palace_db=flow.palace))


def test_async_cancellation_before_persistence_never_writes_candidates(flow, monkeypatch):
    from src.strategy.application import persist
    monkeypatch.setattr(persist, "persist_screen_candidates", forbidden)
    monkeypatch.setattr(screen_run, "screen_run_cancel_requested", lambda: bool(flow.calls))
    screen_run.execute_screen_run({"strategy": SLUG}, market_factory=forbidden, palace_db=flow.palace)
    assert screen_run.screen_run_snapshot(SLUG)["status"] == "cancelled"


@pytest.mark.parametrize("tenant", ["__primary__", "integration-member"])
def test_managed_morning_is_fixed_925_and_prepare_follows_normal_eod_stagger(flow, monkeypatch, tenant):
    from src.ops.application.job_stagger import staggered_minute
    with tenant_scope(tenant), OpsStore(flow.ops) as store:
        store.create_job(name="screen:" + SLUG, kind="screen", cron="30 15 * * mon-fri",
                         config={"strategy": SLUG, "universe": {"preset": "default_a_share",
                                                               "boards": ["main", "chi_next"]}})
        store.ensure_managed_screen_jobs()
        morning = store.get_job_by_name("screen:" + SLUG)
        evening = store.get_job_by_name("screen-prepare:" + SLUG)
        assert morning["cron"] == "25 9 * * mon-fri"
        assert evening["cron"] == f"{staggered_minute(30)} 15 * * mon-fri"
        assert morning["config"]["top_n"] == 2
        assert evening["kind"] == "screen_prepare" and evening["config"]["top_n"] == 0
        assert not morning["config"]["push_wecom"] and not evening["config"]["push_wecom"]
        assert not evening["config"]["record_candidates"]
        assert morning["config"]["universe"]["boards"] == ["main"]
        assert evening["config"]["universe"]["boards"] == ["main"]
        store.set_screen_job_opt_out(SLUG)
        store.ensure_managed_screen_jobs()
        disabled_morning = store.get_job_by_name("screen:" + SLUG)
        assert disabled_morning is None or not disabled_morning["enabled"]
        assert not store.get_job_by_name("screen-prepare:" + SLUG)["enabled"]
        store.ensure_managed_screen_jobs()
        assert not store.get_job_by_name("screen-prepare:" + SLUG)["enabled"]


def test_off_reenable_and_unbind_update_both_tasks_and_never_enable_notifications(flow):
    app = FastAPI()
    app.include_router(strategy_router.build_strategy_router(
        write_dependency=lambda: None, ops_db=flow.ops, palace_db=flow.palace,
    ))
    with TestClient(app) as api:
        path = f"/api/strategies/{SLUG}/job"
        response = api.put(path, json={"schedule_mode": "once", "push_wecom": True, "use_ai_pick": True,
                                       "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]}})
        assert response.status_code == 200, response.text
        assert response.json()["cron"] == "25 9 * * mon-fri"
        assert not response.json()["config"]["push_wecom"]
        assert not response.json()["config"]["use_ai_pick"]
        assert response.json()["config"]["universe"]["boards"] == ["main"]
        with OpsStore(flow.ops) as store:
            assert store.get_job_by_name("screen-prepare:" + SLUG)["config"]["universe"]["boards"] == ["main"]
        assert api.put(path, json={"schedule_mode": "off"}).status_code == 200
        with OpsStore(flow.ops) as store:
            assert not store.get_job_by_name("screen-prepare:" + SLUG)["enabled"]
        assert api.put(path, json={"schedule_mode": "once"}).status_code == 200
        with OpsStore(flow.ops) as store:
            assert store.get_job_by_name("screen-prepare:" + SLUG)["enabled"]
        assert api.delete(path).status_code == 200
        with OpsStore(flow.ops) as store:
            assert not store.get_job_by_name("screen-prepare:" + SLUG)["enabled"]


def set_prepare_clock(monkeypatch, stamp=DAY + "T15:30:00+08:00"):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(stamp).astimezone(tz or ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(screen_prepare, "datetime", Clock)


def test_prepare_uses_ready_closed_store_and_preserves_all_candidates(flow, monkeypatch):
    from src.market.application import screen_spot
    set_prepare_clock(monkeypatch)
    store = SimpleNamespace(list_instruments=lambda: [{"code": "600001", "instrument_type": "STOCK"}])
    monkeypatch.setattr(market_api, "calendar_trading_day", lambda _day: True)
    monkeypatch.setattr(market_api, "guard_market_health", lambda current, **_kw: SimpleNamespace(to_dict=lambda: {"status": "ok"}))
    refresh = []
    monkeypatch.setattr(screen_spot, "ensure_today_quotes_for_screen",
                        lambda current, codes, **kw: refresh.append((current, codes, kw)) or {"status": "ready"})
    monkeypatch.setattr(JobContext, "market", lambda _self: nullcontext(store))
    prepared = []
    def prepare(engine, **kw):
        prepared.append(kw)
        assert kw["store"] is store and kw["as_of"] == DAY
        return {"status": "prepared", "candidate_count": 5, "as_of": DAY,
                "target_trade_date": "2026-10-09", "data_snapshot": {"market_revision": "closed"}}
    flow.runner_module.prepare_double_yin_pool = prepare
    body = screen_prepare.execute_screen_prepare({"strategy": SLUG, "top_n": 2}, JobContext())
    assert len(prepared) == len(refresh) == 1
    assert refresh[0][2]["trade_date"] == DAY
    assert body["candidate_count"] == 5 and not body["record_candidates"] and not body["push_wecom"]
    assert body["data_snapshot"]["market_revision"] == "closed"


@pytest.mark.parametrize("case", ["holiday", "too_early", "history", "calendar_failure"])
def test_prepare_invalid_session_does_not_fetch_or_overwrite_pool(flow, monkeypatch, case):
    set_prepare_clock(monkeypatch, DAY + ("T14:50:00+08:00" if case == "too_early" else "T15:30:00+08:00"))
    monkeypatch.setattr(JobContext, "market", forbidden)
    if case == "calendar_failure":
        monkeypatch.setattr(market_api, "calendar_trading_day", lambda _day: (_ for _ in ()).throw(ValueError("日历过期")))
    else:
        monkeypatch.setattr(market_api, "calendar_trading_day", lambda _day: case != "holiday")
    config = {"strategy": SLUG}
    if case == "history":
        config["as_of"] = "2026-09-29"
    with pytest.raises((JobSkipped, JobError)):
        screen_prepare.execute_screen_prepare(config, JobContext())


def test_prepare_checks_morning_optout_even_if_stale_evening_task_remains_enabled(flow):
    with OpsStore(flow.ops) as store:
        store.ensure_managed_screen_jobs()
        store.set_screen_job_opt_out(SLUG)
        with pytest.raises(JobSkipped, match="已停用"):
            screen_prepare.execute_screen_prepare({"strategy": SLUG}, JobContext(ops_store=store))


@pytest.mark.parametrize("status", ["partial", "failed", "unknown", ""])
def test_prepare_incomplete_status_is_never_reported_as_success(flow, monkeypatch, status):
    from src.market.application import screen_spot

    set_prepare_clock(monkeypatch)
    store = SimpleNamespace(list_instruments=lambda: [{"code": "600001", "instrument_type": "STOCK"}])
    monkeypatch.setattr(market_api, "calendar_trading_day", lambda _day: True)
    monkeypatch.setattr(market_api, "guard_market_health", lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {}))
    monkeypatch.setattr(screen_spot, "ensure_today_quotes_for_screen", lambda *_args, **_kwargs: {"status": "ready"})
    monkeypatch.setattr(JobContext, "market", lambda _self: nullcontext(store))
    flow.runner_module.prepare_double_yin_pool = lambda *_args, **_kwargs: {"status": status, "candidate_count": 0}
    with pytest.raises(JobError, match="未完整成功"):
        screen_prepare.execute_screen_prepare({"strategy": SLUG}, JobContext())


def test_registry_real_strategy_skips_local_market_queue_and_mutes_stale_push_config(flow, monkeypatch):
    from src.ops.application.jobs import registry
    monkeypatch.setattr(registry, "screen_memory_slot", forbidden)
    monkeypatch.setattr(registry, "market_heavy_slot", forbidden)
    observed = []
    def push(**kw):
        observed.append(kw)
        assert kw["job"]["config"]["push_wecom"] is False
    monkeypatch.setattr(registry, "_maybe_push_wecom", push)
    with OpsStore(flow.ops) as store:
        job_id = store.create_job(name="screen:" + SLUG, kind="screen",
                                  config={"strategy": SLUG, "push_wecom": True, "record_candidates": True})
        result = registry.run_job(store, job_id, context=JobContext(ops_store=store, palace_db=flow.palace))
        assert result["status"] == "success", result
        persisted = store.get_run(result["run_id"])
        assert persisted["result"]["data_snapshot"]["quote_source"] == "sina"
        assert len(observed) == 1
