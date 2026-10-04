"""自动公式池生命周期、模拟额度和最终提交竞态。"""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import time

import pytest

from src.ledger import StockAgentConflict, StockAgentStore
from src.ledger.domain.guardian_account import new_guardian_account
from src.ops.application.falcon_watch_pool import reconcile_falcon_watch_pool, sync_falcon_watch_pools
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.stock_agent_policy import simulate_stock_agent
from src.ops.domain.stock_agent import StockAgentConfig
from src.shared.tenancy import tenant_scope

NOW = datetime.fromisoformat("2026-09-30T10:00:00+08:00")


@pytest.fixture(autouse=True)
def no_live_quotes(monkeypatch):
    """所有原回归默认无网络；具体观察价案例可再次覆盖pool helper。"""
    monkeypatch.setattr("src.ops.application.stock_agent_workbench.research_quotes", lambda *_a, **_k: {})
    monkeypatch.setattr("src.ops.application.falcon_watch_pool.research_quotes", lambda *_a, **_k: {})


def candidate(code="301180", slug="formula-a", day="2026-09-29", *, origin="quant", eligible=True):
    return {"code": code, "name": code, "origin": origin, "strategy_slug": slug,
            "source": "job:screen" if origin == "quant" else "skill:" + slug,
            "date": day, "signal_date": day, "produced_at": day + "T14:50:00+08:00",
            "expires_on": "2026-10-13", "reason": "已产出合格信号", "score": 88,
            "evidence_id": f"candidate:{slug}:{code}:{day}:{eligible}", "entry_eligible": eligible}


def scope(*rows, ready=True):
    codes = sorted({row["code"] for row in rows if row["entry_eligible"]})
    automatic = sorted({row["code"] for row in rows if row["entry_eligible"] and row["origin"] == "quant"})
    return {"as_of": NOW.isoformat(), "research_date": "2026-09-30", "historical_review": False,
            "complete": True, "lifecycle_ready": ready, "candidate_codes": codes,
            "auto_observe_codes": automatic, "research_codes": sorted({row["code"] for row in rows}),
            "window": {"trading_days": 5, "dates": ["2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29", "2026-09-30"],
                       "start": "2026-09-23", "end": "2026-09-30", "calendar_basis": "official_calendar"},
            "candidates": deepcopy(list(rows)), "warnings": []}


def reconcile(state, source, *, now=NOW, agent_id="falcon-a"):
    return reconcile_falcon_watch_pool(state, source, as_of=now, agent_id=agent_id)


class GuardOps:
    def __init__(self):
        self.guards = []

    def guardian_commit_guard(self, run_id):
        self.guards.append(run_id)
        return nullcontext()


class TrackedGuardOps(GuardOps):
    def __init__(self):
        super().__init__()
        self.active = False

    @contextmanager
    def guardian_commit_guard(self, run_id):
        self.guards.append(run_id)
        self.active = True
        try:
            yield
        finally:
            self.active = False


def reference_quote(code="301180", price=12.3, *, at=NOW):
    return {"code": code, "price": price, "source": "fixture", "trade_date": at.date().isoformat(),
            "trade_time": at.time().isoformat(), "research_reference": True}


def config(*, enabled=True, watch_limit=0, kind="falcon", name="猎隼测试"):
    return StockAgentConfig(name=name, kind=kind, enabled=enabled, provider="fixture", model="fixture",
                            watch_limit=watch_limit).model_dump()


def test_all_formula_outputs_are_added_and_last_valid_source_controls_removal():
    a = candidate(slug="formula-a")
    b = candidate(slug="formula-b", day="2026-09-30")
    state, delta = reconcile(new_guardian_account(), scope(a, b))
    assert delta["added"] == ["301180"]
    assert len(state["watchlist"]) == 1
    assert len(state["watchlist"][0]["source_refs"]) == 2
    joined = state["watchlist"][0]["added_at"]
    state["watchlist"][0].update(reason="等待承接", entry_condition="放量再评估")
    kept, delta = reconcile(state, scope(b), now=NOW + timedelta(minutes=1))
    assert delta["removed"] == []
    assert kept["watchlist"][0]["added_at"] == joined
    assert kept["watchlist"][0]["reason"] == "等待承接"
    assert kept["watchlist"][0]["entry_condition"] == "放量再评估"
    assert kept["falcon_watch_pool"]["entries"][0]["last_signal_date"] == "2026-09-30"
    cleared, delta = reconcile(kept, scope(), now=NOW + timedelta(minutes=2))
    assert cleared["watchlist"] == [] and delta["removed"][0]["code"] == "301180"


def test_latest_qualified_signal_defines_source_and_holiday_does_not_age_by_calendar_date():
    first = candidate(day="2026-09-23")
    latest = candidate(day="2026-09-29")
    rejected = candidate(day="2026-09-30", eligible=False)
    state, _ = reconcile(new_guardian_account(), scope(first, latest, rejected))
    refs = state["watchlist"][0]["source_refs"]
    assert len(refs) == 1 and refs[0]["evidence_id"] == latest["evidence_id"]
    assert refs[0]["signal_date"] == "2026-09-29"
    first["expires_on"] = "2026-09-30"
    holiday, _ = reconcile(new_guardian_account(), scope(first), now=datetime.fromisoformat("2026-10-07T12:00:00+08:00"))
    assert holiday["watchlist"][0]["code"] == "301180"
    expired, _ = reconcile(holiday, scope(), now=datetime.fromisoformat("2026-10-08T09:00:00+08:00"))
    assert expired["watchlist"] == []


def test_held_is_managed_without_watch_or_financial_changes_and_skill_observation_is_optional():
    state = new_guardian_account()
    state["positions"] = [{"code": "301180", "quantity": 100, "cost_cents": 100_000}]
    state["cash_cents"] -= 100_000
    state["watchlist"] = [{"code": "301180", "reason": "旧观察"}, {"code": "300852", "reason": "技能择时"}]
    before = deepcopy(state)
    source = scope(candidate(), candidate("300852", "skill-a", origin="skill"), candidate("301132", "skill-b", origin="skill"))
    updated, delta = reconcile(state, source)
    assert [row["code"] for row in updated["watchlist"]] == ["300852"]
    assert updated["watchlist"][0]["source_managed"] is False
    assert delta["removed"][0]["reason"] == "已持仓，转入持仓管理"
    assert {key: value for key, value in updated.items() if key not in {"watchlist", "falcon_watch_pool"}} == {
        key: value for key, value in before.items() if key != "watchlist"}
    assert state == before
    # 相同股票由公式自动观察转为仍有效的技能来源，不因一个来源关闭就清掉。
    formula, _ = reconcile(new_guardian_account(), scope(candidate()))
    skill, _ = reconcile(formula, scope(candidate(origin="skill", slug="skill-a")))
    assert skill["watchlist"][0]["code"] == "301180" and not skill["watchlist"][0]["source_managed"]


def test_incomplete_and_historical_evidence_cannot_clear_current_pool_and_ownership_is_enforced():
    with tenant_scope("tenant-a"):
        state, _ = reconcile(new_guardian_account(), scope(candidate()))
        assert reconcile(state, scope(ready=False))[0] == state
        historical = {**scope(), "historical_review": True}
        assert reconcile(state, historical)[0] == state
        with pytest.raises(ValueError, match="归属"):
            reconcile(state, scope(candidate()), agent_id="other-agent")
    with tenant_scope("tenant-b"), pytest.raises(ValueError, match="归属"):
        reconcile(state, scope(candidate()))


def test_no_model_sync_works_while_paused_is_idempotent_and_only_overlays_watch_state(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    source = scope(candidate())
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: source)
    ops = GuardOps()
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(enabled=False), now=NOW)
        other = ledger.create(config(kind="custom", name="其他智能体", enabled=False), now=NOW)
        original = deepcopy(profile["state"])
    result = sync_falcon_watch_pools(ops, path, as_of=NOW)
    assert result["items"][0]["changed"] and ops.guards == [""]
    with StockAgentStore(path) as ledger:
        synced = ledger.get(profile["id"])
        assert synced["state_version"] == profile["state_version"] + 1
        version = synced["state_version"]
        assert not synced["config"]["enabled"]
        assert ledger.get(other["id"])["state"] == other["state"]
    assert not sync_falcon_watch_pools(ops, path, as_of=NOW + timedelta(minutes=1))["items"][0]["changed"]
    with StockAgentStore(path) as ledger:
        current = ledger.get(profile["id"])
        assert current["state_version"] == version
        ledger.update_falcon_watch_pool(profile["id"], lambda state: {**state, "cash_cents": 0, "positions": []}, now=NOW)
        after = ledger.get(profile["id"])
        assert {key: value for key, value in after["state"].items() if key not in {"watchlist", "falcon_watch_pool"}} == {
            key: value for key, value in original.items() if key != "watchlist"}
        assert after["state_version"] == version


def test_first_source_observation_captures_reference_price_outside_both_write_locks(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    now = NOW.replace(hour=16)
    close = now.replace(hour=15)
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: scope(candidate()))
    path = tmp_path / "palace.db"
    ops = TrackedGuardOps()
    with StockAgentStore(path) as ledger:
        first = ledger.create(config(enabled=False), now=now)
        second = ledger.create(config(enabled=False, name="另一个猎隼"), now=now)
    calls = []
    def fetch(codes, **kwargs):
        assert not ops.active
        assert kwargs["now"] == now and 0 < kwargs["deadline"] - time.monotonic() <= 6
        # 如果同步持有ledger写锁，这个独立写事务会受阻。
        with StockAgentStore(path) as ledger, ledger._write():
            ledger.conn.execute("UPDATE stock_agent_profiles SET updated_at=updated_at WHERE id=?", (first["id"],))
        calls.append(codes)
        return {"301180": reference_quote(price=12.405, at=close)}
    monkeypatch.setattr(module, "research_quotes", fetch)
    result = sync_falcon_watch_pools(ops, path, as_of=now)
    assert calls == [["301180"]] and ops.guards == [""]
    assert all(item["added"] == ["301180"] for item in result["items"])
    with StockAgentStore(path) as ledger:
        for original in (first, second):
            profile = ledger.get(original["id"])
            row = profile["state"]["watchlist"][0]
            assert row["observed_at"] == now.isoformat()
            assert row["observed_price_cents"] == row["current_price_cents"] == 1241
            assert row["observed_price_at"] == row["current_price_at"] == close.isoformat()
            assert row.get("reviewed_at") is None and row.get("updated_at") is None
            assert profile["total_trades"] == 0 and profile["total_actions"] == 0
            assert {key: value for key, value in profile["state"].items() if key not in {"watchlist", "falcon_watch_pool"}} == {
                key: value for key, value in original["state"].items() if key != "watchlist"}
    assert not sync_falcon_watch_pools(ops, path, as_of=now + timedelta(minutes=1))["items"][0]["changed"]
    assert calls == [["301180"]]


@pytest.mark.parametrize("quote_offset, accepted", [(0.5, True), (1.5, False)])
def test_quote_clock_uses_elapsed_collection_time_and_still_rejects_real_future(tmp_path, monkeypatch, quote_offset, accepted):
    import src.ops.application.falcon_watch_pool as module
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: scope(candidate()))
    clock = [50.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def fetch(_codes, **kwargs):
        assert kwargs["now"] == NOW and kwargs["deadline"] == 56.0
        clock[0] += 1
        return {"301180": {**reference_quote(at=NOW+timedelta(seconds=quote_offset)),
                            "quote_received_at": (NOW+timedelta(seconds=1)).isoformat()}}
    monkeypatch.setattr(module, "research_quotes", fetch)
    result = sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    assert result["as_of"] == NOW.isoformat()
    with StockAgentStore(path) as ledger:
        saved = ledger.get(profile["id"])["state"]
        row = saved["watchlist"][0]
        assert row["added_at"] == row["observed_at"] == NOW.isoformat()
        assert row["observation_price_attempted_at"] == (NOW+timedelta(seconds=1)).isoformat()
        assert saved["falcon_watch_pool"]["synced_at"] == NOW.isoformat()
        if accepted:
            assert row["observed_price_cents"] == row["current_price_cents"] == 1230
            assert row["observed_price_at"] == (NOW+timedelta(seconds=quote_offset)).isoformat()
        else:
            assert row.get("observed_price_cents") is None and row.get("current_price_cents") is None


def test_existing_unknown_observation_is_never_backfilled_even_with_recent_added_time(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    old, new = candidate(), candidate("300852")
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, scope(old),
            now=NOW-timedelta(seconds=60), agent_id=profile["id"])[0], now=NOW)
        old_row = deepcopy(ledger.get(profile["id"])["state"]["watchlist"][0])
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: scope(old, new))
    calls = []
    def fetch(codes, **_kwargs):
        calls.append(codes)
        return {"301180": reference_quote(), "300852": reference_quote("300852", 9.7)}
    monkeypatch.setattr(module, "research_quotes", fetch)
    sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    assert calls == [["300852"]]
    with StockAgentStore(path) as ledger:
        rows = {row["code"]: row for row in ledger.get(profile["id"])["state"]["watchlist"]}
        assert rows["301180"] == old_row and rows["301180"].get("observed_price_cents") is None
        assert rows["300852"]["observed_price_cents"] == 970


def test_closed_or_expired_source_cleanup_does_not_query_market(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, scope(candidate()), agent_id=profile["id"])[0], now=NOW)
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: scope())
    calls = []
    monkeypatch.setattr(module, "research_quotes", lambda *_a, **_k: calls.append(True))
    sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    assert calls == []
    with StockAgentStore(path) as ledger:
        assert ledger.get(profile["id"])["state"]["watchlist"] == []


@pytest.mark.parametrize("failure", ["exception", "unavailable"])
def test_market_failure_does_not_block_source_sync_or_fabricate_observation_price(tmp_path, monkeypatch, failure):
    import src.ops.application.falcon_watch_pool as module
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: scope(candidate()))
    def fetch(*_args, **_kwargs):
        if failure == "exception":
            raise TimeoutError("fixture quote failure")
        return {"301180": {"code": "301180", "error": "fixture unavailable"}}
    monkeypatch.setattr(module, "research_quotes", fetch)
    result = sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    assert result["items"][0]["added"] == ["301180"]
    with StockAgentStore(path) as ledger:
        saved = ledger.get(profile["id"])
        row = saved["state"]["watchlist"][0]
        assert row.get("observed_price_cents") is None and row.get("current_price_cents") is None
        assert row["observed_at"] == row["added_at"] == NOW.isoformat()
        assert row["observation_price_attempted_at"]
        assert saved["total_trades"] == 0 and saved["state_version"] == profile["state_version"] + 1


def test_source_is_rechecked_after_quote_and_only_final_new_codes_receive_prices(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    source = [scope(candidate())]
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: source[0])
    calls = []
    def fetch(codes, **_kwargs):
        calls.append(codes)
        source[0] = scope(candidate("300852", "new-formula"))
        return {"301180": reference_quote()}
    monkeypatch.setattr(module, "research_quotes", fetch)
    sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    assert calls == [["301180"]]
    with StockAgentStore(path) as ledger:
        rows = ledger.get(profile["id"])["state"]["watchlist"]
        assert [row["code"] for row in rows] == ["300852"]
        assert rows[0].get("observed_price_cents") is None and rows[0].get("current_price_cents") is None


def test_concurrent_existing_observation_is_not_backfilled_by_another_sync_quote(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    source = scope(candidate())
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: source)
    def fetch(*_args, **_kwargs):
        with StockAgentStore(path) as ledger:
            ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, source,
                now=NOW-timedelta(seconds=1), agent_id=profile["id"])[0], now=NOW)
        return {"301180": reference_quote()}
    monkeypatch.setattr(module, "research_quotes", fetch)
    result = sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    assert result["items"][0]["added"] == []
    with StockAgentStore(path) as ledger:
        row = ledger.get(profile["id"])["state"]["watchlist"][0]
        assert row.get("observed_price_cents") is None and row.get("current_price_cents") is None


def test_source_close_invalidates_active_model_lease_and_old_result_cannot_add_it_back(tmp_path, monkeypatch):
    import src.ops.application.falcon_watch_pool as module
    source = scope(candidate())
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: source)
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
    sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    with StockAgentStore(path) as ledger:
        claimed = ledger.claim_run(profile["id"], "2026-09-30:research:lease", "research", now=NOW)
    source = scope()
    sync_falcon_watch_pools(GuardOps(), path, as_of=NOW + timedelta(seconds=1))
    with StockAgentStore(path) as ledger:
        with pytest.raises(StockAgentConflict):
            ledger.assert_owner(profile["id"], claimed["run_id"], now=NOW + timedelta(seconds=2))
        with pytest.raises(StockAgentConflict):
            ledger.finish_run(profile["id"], claimed["run_id"], claimed["state"],
                              {"summary": "旧结果", "candidate_scope": scope(candidate()), "fills": []},
                              now=NOW + timedelta(seconds=2))
        assert ledger.get(profile["id"])["state"]["watchlist"] == []


def test_auto_formula_pool_does_not_consume_manual_skill_watch_limit_and_unwatch_is_explicitly_rejected():
    rows = [candidate("30085" + str(i)) for i in range(3)]
    rows += [candidate("301132", "skill-a", origin="skill"), candidate("301578", "skill-b", origin="skill")]
    source = scope(*rows)
    state, _ = reconcile(new_guardian_account(), source)
    value = StockAgentDecision.model_validate({"summary": "调整观察", "orders": [
        {"code": "300850", "action": "unwatch", "reason": "模型暂不关注"},
        {"code": "301132", "action": "watch", "reason": "技能候选择时"},
        {"code": "301578", "action": "watch", "reason": "第二个技能候选"}]})
    updated, fills, rejects = simulate_stock_agent(state, value, {}, NOW, config(watch_limit=1), analysis_only=True,
        candidate_codes=source["candidate_codes"], auto_observe_codes=source["auto_observe_codes"])
    assert fills == [] and len(updated["watchlist"]) == 4
    assert any(row["code"] == "300850" and row["reject_code"] == "falcon_source_watch_pool" for row in rejects)
    assert any(row["code"] == "301578" and "观察上限" in row["reason"] for row in rejects)


def test_final_commit_allows_large_auto_pool_but_cannot_trust_forged_auto_metadata(tmp_path):
    rows = [candidate("30085" + str(i)) for i in range(3)]
    source = scope(*rows)
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(watch_limit=1), now=NOW)
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, source, agent_id=profile["id"])[0], now=NOW)
        claimed = ledger.claim_run(profile["id"], "2026-09-30:research:large", "research", now=NOW)
        ledger.finish_run(profile["id"], claimed["run_id"], claimed["state"],
            {"summary": "自动池超过自主名额仍可提交", "candidate_scope": source, "fills": []}, now=NOW + timedelta(seconds=1))
        assert len(ledger.get(profile["id"])["state"]["watchlist"]) == 3
        claimed = ledger.claim_run(profile["id"], "2026-09-30:research:forged", "research", now=NOW + timedelta(seconds=2))
        forged = deepcopy(claimed["state"])
        forged["falcon_watch_pool"]["auto_observe_codes"].append("600519")
        with pytest.raises(ValueError, match="元数据"):
            ledger.finish_run(profile["id"], claimed["run_id"], forged,
                {"summary": "伪造自动来源", "candidate_scope": source, "fills": []}, now=NOW + timedelta(seconds=3))


@pytest.mark.parametrize("closing", [False, True])
def test_precommit_checks_latest_sources_and_preserves_actual_model_input(tmp_path, monkeypatch, closing):
    import src.ops.application.falcon_candidates as candidates
    import src.ops.application.falcon_watch_pool as module
    import src.ops.application.jobs.stock_agent as jobs
    import src.ops.application.stock_agent_decide as decide
    import src.ops.application.stock_agent_notify as notify
    import src.ledger.infrastructure.stock_agent_store as storage
    from src.ops.application.jobs.context import JobContext
    from src.ops.infrastructure.store import OpsStore

    original = scope(candidate())
    later = scope() if closing else scope(candidate(), candidate(day="2026-09-30", eligible=False))
    path = tmp_path / "palace.db"
    monkeypatch.setattr(module, "load_falcon_candidates", lambda *_a, **_k: original)
    with StockAgentStore(path) as ledger:
        profile = ledger.create(config(), now=NOW)
    sync_falcon_watch_pools(GuardOps(), path, as_of=NOW)
    with StockAgentStore(path) as ledger:
        claimed = ledger.claim_run(profile["id"], "2026-09-30:research:latest", "research", now=NOW)
    calls = []

    def load(*_a, **_k):
        calls.append(True)
        return deepcopy(original if len(calls) == 1 else later)

    def model(_ops, _profile, payload, **_kwargs):
        assert payload["candidate_scope"] == original
        return StockAgentDecision.model_validate({"summary": "按原始证据研判", "orders": []}), {}

    monkeypatch.setattr(candidates, "load_falcon_candidates", load)
    monkeypatch.setattr(decide, "decide_stock_agent", model)
    monkeypatch.setattr(jobs, "agent_time", lambda: NOW)
    monkeypatch.setattr(storage, "agent_now", lambda now=None: now or NOW)
    monkeypatch.setattr(notify, "notify_stock_agent", lambda *_a, **_k: {"success": True})
    with OpsStore(tmp_path / "ops.db") as ops:
        context = JobContext(ops_store=ops, palace_db=str(path))
        if closing:
            with pytest.raises(StockAgentConflict):
                jobs.run_claimed(claimed, "research", context, str(path))
        else:
            assert jobs.run_claimed(claimed, "research", context, str(path))["status"] == "success"
    with StockAgentStore(path) as ledger:
        run = ledger.run_detail(profile["id"], claimed["run_id"])
        if closing:
            assert run["status"] == "cancelled" and ledger.get(profile["id"])["state"]["watchlist"] == []
        else:
            assert run["detail"]["candidate_scope"] == original
            assert run["detail"]["candidate_scope_at_commit"] == later
        assert ledger.get(profile["id"])["total_trades"] == 0


def test_auto_watch_timing_updates_do_not_count_as_selection_but_real_buys_do(tmp_path):
    source = scope(candidate("300850"), candidate("300851"))
    cfg = {**config(watch_limit=1), "daily_selection_limit": 1}
    path = tmp_path / "palace.db"
    with StockAgentStore(path) as ledger:
        profile = ledger.create(cfg, now=NOW)
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, source, agent_id=profile["id"])[0], now=NOW)
        claimed = ledger.claim_run(profile["id"], "2026-09-30:research:annotations", "research", now=NOW)
        value = StockAgentDecision.model_validate({"summary": "两只自动公式股更新择时", "orders": [
            {"code": code, "action": "watch", "reason": "等待量价确认"} for code in source["auto_observe_codes"]]})
        state, fills, rejects = simulate_stock_agent(claimed["state"], value, {}, NOW, cfg, analysis_only=True,
            candidate_codes=source["candidate_codes"], auto_observe_codes=source["auto_observe_codes"])
        state, _ = reconcile(state, source, agent_id=profile["id"])
        assert not fills and not rejects and state["selected_today"]["codes"] == []
        ledger.finish_run(profile["id"], claimed["run_id"], state,
            {"summary": value.summary, "candidate_scope": source, "fills": fills}, now=NOW + timedelta(seconds=1))
        assert ledger.get(profile["id"])["state"]["selected_today"]["codes"] == []
        bought = ledger.claim_run(profile["id"], "2026-09-30:intraday:buy", "intraday", now=NOW + timedelta(seconds=2))
        execution = {"kind": "market", "valid_until": "2026-09-30T11:00:00+08:00"}
        value = StockAgentDecision.model_validate({"summary": "自动池买入也遵守入选名额", "orders": [
            {"code": code, "action": "buy", "quantity": 100, "reason": "盘口已确认", "execution": execution}
            for code in source["auto_observe_codes"]]})
        quotes = {}
        for code in source["candidate_codes"]:
            stamp = {"trade_date": "2026-09-30", "trade_time": "10:00:00"}
            book = {"code": code, "source": "tencent", "price": 10.0, **stamp,
                    "limit_up": 11.0, "limit_down": 9.0, "ask_price": 10.0, "ask_quantity": 1_000_000,
                    "bid_price": 10.0, "bid_quantity": 1_000_000}
            quotes[code] = {"code": code, "name": code, "price": 10.0, "source": "tencent", **stamp, "order_book": book}
        state, fills, rejects = simulate_stock_agent(bought["state"], value, quotes, NOW, cfg, phase="intraday",
            candidate_codes=source["candidate_codes"], auto_observe_codes=source["auto_observe_codes"])
        assert state["selected_today"]["codes"] == ["300850"]
        assert [(row["code"], row["side"]) for row in fills] == [("300850", "buy")]
        assert rejects[0]["code"] == "300851" and "每日累计" in rejects[0]["reason"]
        state, _ = reconcile(state, source, agent_id=profile["id"])
        ledger.finish_run(profile["id"], bought["run_id"], state,
            {"summary": value.summary, "candidate_scope": source, "fills": fills}, now=NOW + timedelta(seconds=3))
        assert ledger.get(profile["id"])["total_trades"] == 1


def test_config_rename_and_pause_allow_large_auto_pool_but_manual_skill_limit_is_enforced(tmp_path):
    automatic = [candidate("30085" + str(i)) for i in range(3)]
    with StockAgentStore(tmp_path / "palace.db") as ledger:
        profile = ledger.create(config(watch_limit=1), now=NOW)
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, scope(*automatic), agent_id=profile["id"])[0], now=NOW)
        renamed = ledger.update_config(profile["id"], {**profile["config"], "name": "新名称"}, revision=profile["revision"])
        paused = ledger.update_config(profile["id"], {**renamed["config"], "enabled": False}, revision=renamed["revision"])
        assert not paused["config"]["enabled"] and len(paused["state"]["watchlist"]) == 3
        expanded = ledger.update_config(profile["id"], {**paused["config"], "watch_limit": 2}, revision=paused["revision"])
        skills = [candidate("301132", "skill-a", origin="skill"), candidate("301578", "skill-b", origin="skill")]
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(
            {**state, "watchlist": [*state["watchlist"], *[{"code": row["code"], "reason": "自主观察"} for row in skills]]},
            scope(*automatic, *skills), agent_id=profile["id"])[0], now=NOW)
        with pytest.raises(ValueError, match="观察数量"):
            ledger.update_config(profile["id"], {**expanded["config"], "watch_limit": 1}, revision=expanded["revision"])


@pytest.mark.parametrize("historical", [False, True])
def test_unavailable_or_historical_source_keeps_trusted_auto_limit_exemption_without_authorizing_new_watch(tmp_path, historical):
    automatic = scope(*[candidate("30085" + str(i)) for i in range(3)])
    unavailable = {**scope(ready=False), "complete": False, "historical_review": historical}
    with StockAgentStore(tmp_path / "palace.db") as ledger:
        profile = ledger.create(config(watch_limit=1), now=NOW)
        ledger.update_falcon_watch_pool(profile["id"], lambda state: reconcile(state, automatic, agent_id=profile["id"])[0], now=NOW)
        claimed = ledger.claim_run(profile["id"], "2026-09-30:review:hold", "review", now=NOW)
        ledger.finish_run(profile["id"], claimed["run_id"], claimed["state"],
            {"summary": "历史/来源缺失只研究已有证据", "candidate_scope": unavailable, "fills": []}, now=NOW + timedelta(seconds=1))
        assert len(ledger.get(profile["id"])["state"]["watchlist"]) == 3
        claimed = ledger.claim_run(profile["id"], "2026-09-30:review:fake", "review", now=NOW + timedelta(seconds=2))
        forged = deepcopy(claimed["state"])
        forged["watchlist"].append({"code": "600519", "reason": "伪造新源"})
        forged["falcon_watch_pool"]["auto_observe_codes"].append("600519")
        fake = {**unavailable, "auto_observe_codes": ["600519"]}
        with pytest.raises(ValueError, match="候选快照"):
            ledger.finish_run(profile["id"], claimed["run_id"], forged,
                {"summary": "假候选不能新增或免额度", "candidate_scope": fake, "fills": []}, now=NOW + timedelta(seconds=3))
        deleted = deepcopy(claimed["state"])
        deleted["watchlist"] = deleted["watchlist"][1:]
        with pytest.raises(ValueError, match="保留已有自动观察"):
            ledger.finish_run(profile["id"], claimed["run_id"], deleted,
                {"summary": "未知来源不能删已有自动观察", "candidate_scope": unavailable, "fills": []}, now=NOW + timedelta(seconds=3))


def test_unavailable_source_rejects_auto_unwatch_per_order_without_authorizing_old_candidates():
    source = scope(candidate())
    state, _ = reconcile(new_guardian_account(), source)
    value = StockAgentDecision.model_validate({"summary": "未知源仅保持账户", "orders": [
        {"code": "301180", "action": "unwatch", "reason": "旧观察暂不关注"},
        {"code": "301180", "action": "watch", "reason": "旧自动池不能授权新观察"},
        {"code": "301180", "action": "buy", "quantity": 100, "reason": "旧自动池不能授权新买入"}]})
    updated, fills, rejects = simulate_stock_agent(state, value, {}, NOW, config(watch_limit=1), analysis_only=True,
        candidate_codes=[], auto_observe_codes=[])
    assert not fills and updated["watchlist"] == state["watchlist"]
    assert [(row["action"], row["reject_code"]) for row in rejects] == [
        ("unwatch", "falcon_source_watch_pool"), ("watch", "falcon_candidate_scope"), ("buy", "falcon_candidate_scope")]
