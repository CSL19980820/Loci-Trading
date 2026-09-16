"""风险合同从研判安装到定时撮合的回归；行情、模型和通知均隔离。"""
from __future__ import annotations

import copy
from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore, mark_guardian_account, new_guardian_account, settle_guardian_order
from src.ops.application import guardian_agent
from src.ops.application.guardian_config import DEFAULTS, JOB_NAME, save_config
from src.ops.application.guardian_decision import GuardianDecision, GuardianOrder, simulate
from src.ops.application.guardian_risk import evaluate_risk_plans, install_risk_plans
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobCancelled, JobContext, JobError
from src.ops.infrastructure.store import OpsStore
from src.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
CODE = "603920"


def plan(**changes) -> dict:
    return {"action": "stop_loss", "quantity": 500, "trigger_price": 9, "reason": "已确认风险",
            "execution": {"kind": "market", "valid_until": (NOW + timedelta(days=3)).isoformat()}, **changes}


def quote(price=9, code=CODE, now=NOW) -> dict:
    return {"code": code, "name": "测试持仓", "price": price, "source": "risk_fixture",
            "trade_date": now.date().isoformat(), "trade_time": now.strftime("%H:%M:%S")}


def order(action="hold", quantity=0, code=CODE, **changes) -> dict:
    return {"code": code, "action": action, "quantity": quantity, "reason": "研究确认",
            "execution": {"kind": "market", "valid_until": (NOW + timedelta(days=3)).isoformat()}, **changes}


def decision(*orders, **changes) -> GuardianDecision:
    return GuardianDecision.model_validate({"summary": "研究确认", "orders": list(orders), **changes})


def account(count=1, *, bought_today=False) -> tuple[dict, list[dict]]:
    state, fills = new_guardian_account(), []
    for index, code in enumerate([CODE, "600001", "600002", "600003", "600004", "600005"][:count]):
        opened = NOW if bought_today else NOW - timedelta(days=3 - index // 4)
        fills.append(settle_guardian_order(state, order("buy", 1000, code), quote(10, code, opened), opened, {}))
    return state, fills


def seed(context, state, fills) -> None:
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.claim("seed-risk")
        ledger.finish("seed-risk", {"status": "success", "fills": fills}, state)


def saved(context) -> tuple[dict, dict]:
    with GuardianStore(context.palace_db) as ledger:
        return ledger.state(), ledger.recent()[0]["result"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append("external connection")
        raise AssertionError("测试不允许真实出网")
    monkeypatch.setattr("socket.socket.connect", denied)
    monkeypatch.setattr("urllib.request.urlopen", denied)
    yield
    assert not attempts, attempts


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    clock = [NOW]
    monkeypatch.setattr(guardian, "datetime", SimpleNamespace(now=lambda tz: clock[0]))
    monkeypatch.setattr(guardian, "calendar_trading_day", lambda day: True)
    model = Mock(return_value=(decision(), {}))
    notify = Mock(return_value={"success": True})
    observe = Mock(return_value=[])
    repair = Mock(side_effect=lambda store, cfg, intent, *a, **kw: intent)
    def snapshot(codes, **kwargs):
        return SimpleNamespace(quotes={code: quote(9, code, clock[0]) for code in codes})
    snapshots = Mock(side_effect=snapshot)
    monkeypatch.setattr(guardian, "decide", model)
    monkeypatch.setattr(guardian, "dispatch_text", notify)
    monkeypatch.setattr(guardian, "observe", observe)
    monkeypatch.setattr(guardian, "repair_preflight", repair)
    monkeypatch.setattr(guardian, "build_monitor_snapshot", snapshots)
    monkeypatch.setattr(guardian, "data_source", lambda: {"mode": "risk_fixture"})
    with OpsStore(tmp_path / "ops.db") as ops:
        cfg = {**DEFAULTS, "enabled": True, "provider": "fixture", "model": "fixture", "notify": True}
        ops.create_job(name=JOB_NAME, kind="guardian", enabled=True, config=cfg)
        context = JobContext(ops_store=ops, palace_db=str(tmp_path / "palace.db"))
        market = Mock(side_effect=lambda: nullcontext(SimpleNamespace(trading_days=lambda **kw: ["2026-09-15"])))
        monkeypatch.setattr(context, "market", market)
        yield SimpleNamespace(context=context, model=model, notify=notify, observe=observe, repair=repair,
                              clock=clock, snapshots=snapshots, snapshot=snapshot, market=market, config=cfg)


def test_schema_bounds_and_observation_cannot_change_risk() -> None:
    GuardianOrder.model_validate(order(risk_plans=[plan()] * 16))
    with pytest.raises(ValueError):
        GuardianOrder.model_validate(order(risk_plans=[plan()] * 17))
    for action in ("watch", "unwatch"):
        GuardianOrder.model_validate(order(action, risk_plans=None))
        for value in ([], [plan()]):
            with pytest.raises(ValueError):
                GuardianOrder.model_validate(order(action, risk_plans=value))


def test_hold_installs_preserves_and_withdraws_contracts() -> None:
    state, _ = account()
    updated, fills, rejects = simulate(state, decision(order(risk_plans=[plan()])), [], {}, NOW)
    assert not fills and not rejects and "risk_plans" not in state["positions"][0]
    rows = copy.deepcopy(updated["positions"][0]["risk_plans"])
    assert rows[0]["basis_quantity"] == 1000 and rows[0]["status"] == "active"
    kept, _, _ = simulate(updated, decision(order()), [], {}, NOW)
    assert kept["positions"][0]["risk_plans"] == rows
    removed, _, _ = simulate(kept, decision(order(risk_plans=[])), [], {}, NOW)
    assert removed["positions"][0]["risk_plans"] == []


@pytest.mark.parametrize("action,quantity,risk_quantity,expected", [
    ("buy", 1000, 1000, 1000), ("add", 500, 1500, 1500), ("reduce", 500, 500, 500),
])
def test_trade_installs_against_actual_post_trade_holdings(action, quantity, risk_quantity, expected) -> None:
    state = new_guardian_account() if action == "buy" else account()[0]
    updated, fills, rejects = simulate(state, decision(order(action, quantity, risk_plans=[plan(quantity=risk_quantity)])),
                                       [], {CODE: quote()}, NOW)
    assert len(fills) == 1 and not rejects
    position = updated["positions"][0]
    assert position["quantity"] == expected == position["risk_plans"][0]["basis_quantity"]
    assert position["risk_plans"][0]["contract"]["quantity"] == risk_quantity


@pytest.mark.parametrize("action,quantity,risk_quantity", [
    ("buy", 1000, 1100), ("add", 500, 1600), ("reduce", 500, 600), ("sell", 1000, 100),
])
def test_invalid_plan_rolls_back_trade_atomically(action, quantity, risk_quantity) -> None:
    state = new_guardian_account() if action == "buy" else account()[0]
    before = copy.deepcopy(state)
    updated, fills, rejects = simulate(state, decision(order(action, quantity, risk_plans=[plan(quantity=risk_quantity)])),
                                       [], {CODE: quote()}, NOW)
    assert fills == [] and rejects[0]["reject_code"] == "risk_plan"
    assert state == before
    assert updated == mark_guardian_account(before, {CODE: quote()}, NOW)


def test_invalid_hold_plan_does_not_change_review_or_old_contract() -> None:
    state, _ = account()
    install_risk_plans(state["positions"][0], [plan()], NOW)
    expected = mark_guardian_account(state, {}, NOW)
    updated, fills, rejects = simulate(state, decision(order(risk_plans=[plan(quantity=1100)],
                                                           holding_plan="不应保存")), [], {}, NOW)
    assert not fills and rejects[0]["reject_code"] == "risk_plan" and updated == expected


def test_legacy_natural_language_is_not_a_risk_order() -> None:
    state, _ = account()
    updated, _, _ = simulate(state, decision(order(stop_loss_plan="跌到9元卖500股")), [], {}, NOW)
    _, orders, events = evaluate_risk_plans(updated, {CODE: quote(8)}, NOW)
    assert orders == events == [] and "risk_plans" not in updated["positions"][0]


@pytest.mark.parametrize("action", ["buy", "add", "sell", "reduce", "hold", "watch", "unwatch"])
def test_risk_only_rejects_other_actions(action) -> None:
    state, _ = account()
    quantity = 0 if action in ("hold", "watch", "unwatch") else 100
    updated, fills, rejects = simulate(state, decision(order(action, quantity)), [], {CODE: quote()}, NOW, risk_only=True)
    assert not fills and rejects[0]["reject_code"] == "risk_only"
    assert updated == mark_guardian_account(state, {CODE: quote()}, NOW)


def test_risk_only_cannot_replace_contract_or_repeat_stock() -> None:
    state, _ = account()
    install_risk_plans(state["positions"][0], [plan()], NOW)
    _, fills, rejects = simulate(state, decision(order("stop_loss", 500, risk_plans=[])),
                                 [], {CODE: quote()}, NOW, risk_only=True)
    assert not fills and rejects[0]["reject_code"] == "risk_only"
    updated, fills, rejects = simulate(state, decision(order("stop_loss", 500), order("take_profit", 500)),
                                       [], {CODE: quote()}, NOW, risk_only=True)
    assert len(fills) == 1 and updated["positions"][0]["quantity"] == 500
    assert len(rejects) == 1 and rejects[0]["reject_code"] == "risk_only"


def armed(runtime, *, quantity=500, count=1, bought_today=False) -> dict:
    state, fills = account(count, bought_today=bought_today)
    install_risk_plans(state["positions"][0], [plan(quantity=quantity)], NOW)
    seed(runtime.context, state, fills)
    runtime.model.side_effect = AssertionError("风险执行不能等待模型")
    runtime.market.side_effect = AssertionError("风险执行不能查询候选市场")
    return state


def test_saved_stop_bypasses_model_and_candidate_failures(runtime) -> None:
    armed(runtime)
    result = guardian.execute_guardian({}, runtime.context)
    state, stored = saved(runtime.context)
    assert result["status"] == "success" and result["risk_only"]
    assert len(result["fills"]) == 1 and result["fills"][0]["quote_source"] == "risk_fixture"
    assert state["positions"][0]["quantity"] == 500
    assert state["positions"][0]["risk_plans"][0]["status"] == "executed"
    assert stored["risk_events"][0]["status"] == "executed"
    assert result["usage"]["source"] == "saved_risk_plan"
    assert runtime.snapshots.call_count == 2 and runtime.notify.call_count == 1
    calls = runtime.snapshots.call_args_list
    assert calls[1].kwargs["deadline"] - calls[0].kwargs["deadline"] == pytest.approx(270)
    runtime.model.assert_not_called()
    runtime.market.assert_not_called()
    runtime.observe.assert_not_called()
    runtime.repair.assert_not_called()


def test_rebound_reject_keeps_contract_for_next_slot_retry(runtime) -> None:
    armed(runtime)
    runtime.snapshots.side_effect = [SimpleNamespace(quotes={CODE: quote(9)}), SimpleNamespace(quotes={CODE: quote(9.19)})]
    result = guardian.execute_guardian({}, runtime.context)
    state, _ = saved(runtime.context)
    assert result["status"] == "failed" and not result["fills"]
    assert result["rejects"][0]["reject_code"] == "price_condition"
    assert state["positions"][0]["risk_plans"][0]["status"] == "active"
    assert result["risk_events"][0]["status"] == "triggered"
    runtime.repair.assert_not_called()
    runtime.clock[0] += timedelta(minutes=5)
    runtime.snapshots.side_effect = runtime.snapshot
    retry = guardian.execute_guardian({}, runtime.context)
    assert len(retry["fills"]) == 1 and retry["risk_events"][0]["status"] == "executed"
    assert saved(runtime.context)[0]["positions"][0]["quantity"] == 500


def test_t1_risk_retries_next_day_and_records_full_exit(runtime) -> None:
    armed(runtime, quantity=1000, bought_today=True)
    result = guardian.execute_guardian({}, runtime.context)
    assert not result["fills"] and result["rejects"][0]["reject_code"] == "t_plus_one"
    assert saved(runtime.context)[0]["positions"][0]["risk_plans"][0]["status"] == "active"
    runtime.clock[0] += timedelta(days=1)
    result = guardian.execute_guardian({}, runtime.context)
    assert len(result["fills"]) == 1 and result["fills"][0]["quantity"] == 1000
    assert saved(runtime.context)[0]["positions"] == []
    assert result["risk_events"][0]["executed_quantity"] == 1000


def test_cancel_during_final_quote_does_not_consume_or_commit(runtime, monkeypatch) -> None:
    before = armed(runtime)
    cancelled = [False]
    def checkpoint():
        if cancelled[0]:
            raise JobCancelled("用户取消")
    def snapshot(codes, **kwargs):
        if runtime.snapshots.call_count == 2:
            cancelled[0] = True
        return runtime.snapshot(codes, **kwargs)
    monkeypatch.setattr(runtime.context, "check_cancelled", checkpoint)
    runtime.snapshots.side_effect = snapshot
    with pytest.raises(JobCancelled):
        guardian.execute_guardian({}, runtime.context)
    state, result = saved(runtime.context)
    assert state == before and result["status"] == "cancelled"
    assert all(event["status"] != "executed" for event in result["risk_events"])
    runtime.notify.assert_not_called()


def test_config_change_after_risk_quote_rolls_back_consumption(runtime) -> None:
    before = armed(runtime)
    def snapshot(codes, **kwargs):
        if runtime.snapshots.call_count == 2:
            save_config(runtime.context.ops_store, {"enabled": False})
        return runtime.snapshot(codes, **kwargs)
    runtime.snapshots.side_effect = snapshot
    with pytest.raises(JobError, match="配置"):
        guardian.execute_guardian({}, runtime.context)
    state, result = saved(runtime.context)
    assert state == before and all(event["status"] != "executed" for event in result["risk_events"])
    runtime.notify.assert_called_once()


def test_monotonic_deadline_blocks_risk_with_unchanged_wall_clock(runtime, monkeypatch) -> None:
    armed(runtime)
    elapsed = [0.0]
    monkeypatch.setattr(guardian, "time", SimpleNamespace(monotonic=lambda: elapsed[0]))
    def snapshot(codes, **kwargs):
        if runtime.snapshots.call_count == 2:
            elapsed[0] = 301.0
        return runtime.snapshot(codes, **kwargs)
    runtime.snapshots.side_effect = snapshot
    result = guardian.execute_guardian({}, runtime.context)
    assert runtime.clock[0] == NOW and not result["fills"] and result["status"] == "failed"
    assert saved(runtime.context)[0]["positions"][0]["risk_plans"][0]["status"] == "active"
    assert result["risk_events"][0]["status"] == "triggered"


@pytest.mark.parametrize("ending", ["expired", "invalidated"])
def test_initial_expiry_and_changed_basis_are_persisted_without_model(runtime, ending) -> None:
    state, fills = account()
    contract = plan(execution={"kind": "market", "valid_until": NOW.isoformat()}) if ending == "expired" else plan()
    install_risk_plans(state["positions"][0], [contract], NOW - timedelta(minutes=1))
    if ending == "invalidated":
        state["positions"][0]["entry_context"]["opened_at"] = (NOW - timedelta(days=2)).isoformat()
    seed(runtime.context, state, fills)
    runtime.model.side_effect = AssertionError("失效回执不应被模型异常吞掉")
    result = guardian.execute_guardian({}, runtime.context)
    state, stored = saved(runtime.context)
    assert not result["fills"] and result["status"] == "failed"
    assert state["positions"][0]["risk_plans"][0]["status"] == ending
    assert stored["risk_events"][0]["status"] == ending
    runtime.model.assert_not_called()
    runtime.notify.assert_called_once()


def test_expiry_between_quotes_is_saved_and_never_consumed(runtime) -> None:
    state, fills = account()
    install_risk_plans(state["positions"][0], [plan(execution={"kind": "market",
        "valid_until": (NOW + timedelta(seconds=1)).isoformat()})], NOW)
    seed(runtime.context, state, fills)
    def snapshot(codes, **kwargs):
        if runtime.snapshots.call_count == 2:
            runtime.clock[0] += timedelta(seconds=2)
        return runtime.snapshot(codes, **kwargs)
    runtime.snapshots.side_effect = snapshot
    result = guardian.execute_guardian({}, runtime.context)
    assert not result["fills"] and any(r["reject_code"] == "intent_expired" for r in result["rejects"])
    assert saved(runtime.context)[0]["positions"][0]["risk_plans"][0]["status"] == "expired"
    assert "executed" not in {e["status"] for e in result["risk_events"]}


@pytest.mark.parametrize("missing", ["initial", "final", "timeout"])
def test_missing_risk_quote_is_blocked_and_notified(runtime, missing) -> None:
    armed(runtime)
    if missing != "final":
        runtime.market.side_effect = lambda: nullcontext(SimpleNamespace(trading_days=lambda **kw: ["2026-09-15"]))
        runtime.model.side_effect = None
        runtime.observe.side_effect = None

    def snapshot(codes, **kwargs):
        call = runtime.snapshots.call_count
        if missing == "timeout" and call == 1:
            raise TimeoutError("持仓取价deadline")
        if (missing == "initial" and call == 1) or (missing == "final" and call == 2):
            return SimpleNamespace(quotes={})
        return runtime.snapshot(codes, **kwargs)
    runtime.snapshots.side_effect = snapshot
    result = guardian.execute_guardian({}, runtime.context)
    expected = "quote_unavailable" if missing == "final" else "risk_quote_unavailable"
    assert result["status"] == "failed" and not result["fills"]
    assert any(row["reject_code"] == expected for row in result["rejects"])
    assert saved(runtime.context)[0]["positions"][0]["risk_plans"][0]["status"] == "active"
    assert CODE in result["body"] and "暂未执行" in result["body"]
    runtime.notify.assert_called_once()
    if missing == "final":
        runtime.model.assert_not_called()
    else:
        runtime.model.assert_called_once()


@pytest.mark.parametrize("close_due", [False, True])
def test_missing_close_plan_does_not_undo_legal_risk_reduction(runtime, close_due) -> None:
    armed(runtime, count=6)
    if close_due:
        runtime.clock[0] = NOW.replace(hour=14, minute=50)
        with pytest.raises(JobError, match="尾盘持仓"):
            guardian.execute_guardian({}, runtime.context)
        state, result = saved(runtime.context)
    else:
        result = guardian.execute_guardian({}, runtime.context)
        state, _ = saved(runtime.context)
    assert len(result["fills"]) == 1 and result["fills"][0]["quantity"] == 500
    assert len(state["positions"]) == 6 and state["positions"][0]["quantity"] == 500
    assert state["positions"][0]["risk_plans"][0]["status"] == "executed"
    assert any(r["reject_code"] == "close_plan" for r in result["rejects"])
    assert result["outcome"] == "partial_execution" and "close_keep_codes" not in state
    runtime.notify.assert_called_once()


def test_tail_risk_has_priority_without_duplicate_close_order(runtime) -> None:
    state, fills = account(5)
    keep = [p["code"] for p in state["positions"][:4]]
    state.update(close_keep_codes=keep, close_plan_date=NOW.date().isoformat())
    target = state["positions"][-1]
    target_code = target["code"]
    install_risk_plans(target, [plan(quantity=1000)], NOW)
    seed(runtime.context, state, fills)
    runtime.clock[0] = NOW.replace(hour=14, minute=50)
    runtime.model.side_effect = AssertionError("尾盘风险优先")
    result = guardian.execute_guardian({}, runtime.context)
    state, _ = saved(runtime.context)
    assert [(f["code"], f["quantity"]) for f in result["fills"]] == [(target_code, 1000)]
    assert len(state["positions"]) == 4 and result["risk_only"] and not result["closing_rebalance"]
    assert state["close_keep_codes"] == keep
    assert result["risk_events"][0]["status"] == "executed"


@pytest.mark.parametrize("locked", [False, True])
def test_keep_list_only_prunes_stocks_that_really_closed(locked) -> None:
    state, _ = account(6)
    keep = [CODE, "600001", "600002", "600099"]
    state.update(close_keep_codes=keep, close_plan_date=NOW.date().isoformat())
    if locked:
        state["positions"][0].update(today_bought=1000, bought_on=NOW.date().isoformat())
    updated, fills, rejects = simulate(state, decision(order("stop_loss", 1000)), [],
                                       {CODE: quote()}, NOW, risk_only=True)
    assert len(fills) == (0 if locked else 1)
    assert updated["close_keep_codes"] == (keep if locked else keep[1:])
    assert any(r["reject_code"] == "close_plan" for r in rejects)
    assert "600099" in updated["close_keep_codes"]


def test_job_risk_execution_isolated_between_two_tenants(runtime, monkeypatch) -> None:
    for tenant, trigger in (("risk_execution_a", 9), ("risk_execution_b", 8)):
        with tenant_scope(tenant), OpsStore(None) as ops:
            ops.create_job(name=JOB_NAME, kind="guardian", enabled=True, config=runtime.config)
            context = JobContext(ops_store=ops, palace_db=None)
            monkeypatch.setattr(context, "market", runtime.market)
            state, fills = account()
            install_risk_plans(state["positions"][0], [plan(trigger_price=trigger)], NOW)
            seed(context, state, fills)
            result = guardian.execute_guardian({}, context)
            assert bool(result["fills"]) is (trigger == 9)
    for tenant, quantity, status in (("risk_execution_a", 500, "executed"), ("risk_execution_b", 1000, "active")):
        with tenant_scope(tenant), GuardianStore() as ledger:
            position = ledger.state()["positions"][0]
            assert position["quantity"] == quantity and position["risk_plans"][0]["status"] == status
    assert runtime.model.call_count == 1 and runtime.notify.call_count == 1


def test_agent_schema_risk_rules_and_transport_deadline(runtime, monkeypatch) -> None:
    from src.ops.application.guardian_evidence import OPPORTUNITY_RULES
    provider = SimpleNamespace(model="fixture", protocol="openai_compatible")
    tools = Mock(return_value=([], lambda name, arguments: {}, {"mode": "fixture"}))
    complete = Mock(return_value=(decision(), {}))
    monkeypatch.setattr("src.ai.resolve_config", lambda *a, **kw: provider)
    monkeypatch.setattr("src.ops.application.guardian_tools.agent_tools", tools)
    monkeypatch.setattr(guardian_agent, "complete_decision", complete)
    deadline = guardian_agent.time.monotonic() + 60
    guardian_agent.decide(runtime.context.ops_store, runtime.config,
                          {"as_of": NOW.isoformat(), "portfolio": new_guardian_account()}, deadline=deadline)
    assert tools.call_args.kwargs["deadline"] == deadline
    system = complete.call_args.kwargs["system"]
    assert "risk_plans" in system and '"maxItems": 16' in system
    assert "旧自然语言" in system and "trigger_price" in system and OPPORTUNITY_RULES in system
