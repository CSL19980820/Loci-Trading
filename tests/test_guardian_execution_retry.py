"""受阻意图回到模型重新授权，整轮预检重算但最终只落账一次。"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore, new_guardian_account, settle_guardian_order
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_risk import install_risk_plans
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobCancelled, JobError


NOW = datetime(2026, 10, 13, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
A, B = "600000", "300364"


def trade(code, quantity, reference, *, action="sell", reason="重新核验后退出"):
    return {"code": code, "action": action, "quantity": quantity, "reason": reason,
            "execution": {"kind": "market", "reference_price": reference,
                          "valid_until": (NOW + timedelta(seconds=300)).isoformat()}}


def decision(reference):
    return GuardianDecision.model_validate({"summary": "拟分批退出持仓",
                                           "orders": [trade(A, 100, 10), trade(B, 300, reference)]})


def fixture_job(tmp_path, monkeypatch, prices, *, positions=None, initial_decision=None):
    state = new_guardian_account()
    positions = positions or [(A, 400, 10), (B, 300, 24.25)]
    for code, quantity, price in positions:
        settle_guardian_order(state, {"code": code, "action": "buy", "quantity": quantity,
                                     "reason": "昨日隔离账户建仓"},
                              {"price": price, "name": code}, NOW - timedelta(days=1), {})
    path = tmp_path / "palace.db"
    with GuardianStore(path) as ledger:
        ledger.conn.execute("UPDATE guardian_portfolio SET state_json=? WHERE id=1", (json.dumps(state),))
        ledger.conn.commit()

    clock = SimpleNamespace(instant=NOW)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.instant if tz is None else clock.instant.astimezone(tz)

    cfg = {"enabled": True, "notify": False, "model": "fixture"}
    ops = SimpleNamespace(get_run=lambda _: None, guardian_commit_guard=lambda _: nullcontext())
    context = SimpleNamespace(ops_store=ops, palace_db=path, run_id="",
                              market=lambda: nullcontext(SimpleNamespace(trading_days=lambda **_: ["2026-10-12"])),
                              check_cancelled=lambda: None)
    snapshot_calls = []

    def snapshot(codes, **kwargs):
        index = len(snapshot_calls)
        assert index < len(prices), "重试不得无限刷新行情或重复下单"
        snapshot_calls.append({"codes": list(codes), **kwargs})
        batch = {code: {"code": code, "price": price, "source": "sina",
                        "trade_date": clock.instant.date().isoformat(),
                        "trade_time": clock.instant.strftime("%H:%M:%S")}
                 for code, price in prices[index].items() if code in codes}
        return SimpleNamespace(quotes=batch)

    initial_decision = initial_decision or decision(24.25)
    decide = MagicMock(return_value=(initial_decision, {"source": "fixture"}))
    monkeypatch.setattr(guardian, "datetime", Clock)
    monkeypatch.setattr(guardian, "get_config", lambda _: cfg)
    monkeypatch.setattr(guardian, "calendar_trading_day", lambda _: True)
    monkeypatch.setattr(guardian, "build_monitor_snapshot", snapshot)
    monkeypatch.setattr(guardian, "decide", decide)
    monkeypatch.setattr(guardian, "data_source", lambda: {"label": "isolated fixture"})
    monkeypatch.setattr(guardian, "deliver_pending", lambda *_: {})
    return SimpleNamespace(path=path, context=context, state=state, clock=clock, cfg=cfg,
                           snapshots=snapshot_calls, decide=decide)


def assert_uncommitted_retry(job, retry_state, kwargs, *, expected_fills):
    assert {p["code"]: p["quantity"] for p in retry_state["positions"]} == {
        p["code"]: p["quantity"] for p in job.state["positions"]}
    assert retry_state["cash_cents"] == job.state["cash_cents"]
    assert [(fill["code"], fill["quantity"]) for fill in kwargs["preflight_fills"]] == expected_fills
    deadline = kwargs["execution_deadline"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline)
    assert deadline == NOW + timedelta(seconds=300)
    payload = kwargs["retry_payload"]
    assert payload["portfolio"]["cash_cents"] == retry_state["cash_cents"]
    assert payload["risk_events"] is not None
    assert datetime.fromisoformat(payload["as_of"]).utcoffset() == timedelta(hours=8)
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 0
        assert ledger.state() == job.state


def test_blocked_sell_reauthorized_without_repeating_successful_sell(tmp_path, monkeypatch):
    quotes = {A: 10, B: 24.74}
    job = fixture_job(tmp_path, monkeypatch, [quotes, quotes, quotes])
    attempts = []

    def repair(_store, _cfg, original, _meta, state, refreshed, rejects, **kwargs):
        attempts.append(deepcopy(kwargs))
        assert_uncommitted_retry(job, state, kwargs, expected_fills=[(A, 100)])
        assert [(row["code"], row["reject_code"]) for row in rejects] == [(B, "price_condition")]
        assert refreshed[B]["price"] == 24.74
        assert original.orders[1].execution.reference_price == 24.25
        return decision(24.74)

    monkeypatch.setattr(guardian, "repair_preflight", repair)
    result = guardian.execute_guardian({}, job.context)
    assert result["status"] == "success"
    assert result["ledger_committed"] and not result["rejects"] and not result["withdrawn"]
    assert len(attempts) == 1
    assert [(fill["code"], fill["quantity"]) for fill in result["fills"]] == [(A, 100), (B, 300)]
    assert result["initial_rejects"][0]["code"] == B
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 2
        assert [p["quantity"] for p in ledger.state()["positions"]] == [300]
        assert ledger.recent()[0]["result"]["fills"] == result["fills"]
    assert all(call["require_order_book"] is False for call in job.snapshots[1:])


def test_invalid_model_correction_gets_one_more_attempt_without_duplicate_settlement(tmp_path, monkeypatch):
    quotes = {A: 10, B: 24.74}
    job = fixture_job(tmp_path, monkeypatch, [quotes, quotes, quotes])
    attempts = []

    def repair(_store, _cfg, original, meta, state, refreshed, rejects, **kwargs):
        assert_uncommitted_retry(job, state, kwargs, expected_fills=[(A, 100)])
        attempts.append(original)
        if len(attempts) == 1:
            meta["preflight_repair"] = {"status": "failed", "error": "修正不得新增股票"}
            return original
        assert meta["preflight_repair"]["error"] == "修正不得新增股票"
        meta["preflight_repair"] = {"status": "corrected"}
        return decision(refreshed[B]["price"])

    monkeypatch.setattr(guardian, "repair_preflight", repair)
    result = guardian.execute_guardian({}, job.context)
    assert len(attempts) == 2 and result["status"] == "success"
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 2


@pytest.mark.parametrize("second_retry_succeeds", [True, False])
def test_second_reauthorization_is_bounded_and_preserves_other_fill(tmp_path, monkeypatch, second_retry_succeeds):
    initial = {A: 10, B: 24.74}
    after_first = {A: 10, B: 25.30}
    final = {A: 10, B: 25.30 if second_retry_succeeds else 25.90}
    job = fixture_job(tmp_path, monkeypatch, [initial, initial, after_first, final])
    attempts = []

    def repair(_store, _cfg, original, _meta, state, quotes, rejects, **kwargs):
        assert_uncommitted_retry(job, state, kwargs, expected_fills=[(A, 100)])
        attempts.append({"decision": original, "quotes": deepcopy(quotes), "rejects": deepcopy(rejects)})
        assert len(attempts) <= 2
        assert [row["code"] for row in rejects] == [B]
        return decision(quotes[B]["price"])

    monkeypatch.setattr(guardian, "repair_preflight", repair)
    result = guardian.execute_guardian({}, job.context)
    assert len(attempts) == 2 and len(job.snapshots) == 4
    assert attempts[1]["decision"].orders[1].execution.reference_price == 24.74
    assert attempts[1]["quotes"][B]["price"] == 25.30
    assert result["ledger_committed"] and not result["withdrawn"]
    expected = [(A, 100), (B, 300)] if second_retry_succeeds else [(A, 100)]
    assert [(fill["code"], fill["quantity"]) for fill in result["fills"]] == expected
    assert result["status"] == ("success" if second_retry_succeeds else "failed")
    assert bool(result["rejects"]) != second_retry_succeeds
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == len(expected)
        assert {p["code"]: p["quantity"] for p in ledger.state()["positions"]} == (
            {A: 300} if second_retry_succeeds else {A: 300, B: 300})


def test_triggered_saved_stop_is_reauthorized_by_model_and_consumed_only_after_fill(tmp_path, monkeypatch):
    code = "300133"
    job = fixture_job(tmp_path, monkeypatch, [{code: 8.70}, {code: 8.87}, {code: 8.87}],
                      positions=[(code, 4000, 9)])
    install_risk_plans(job.state["positions"][0], [{"action": "stop_loss", "quantity": 4000,
        "trigger_price": 8.70, "reason": "持仓触发止损", "execution": {"kind": "market",
        "reference_price": 8.68, "valid_until": "2026-10-13T14:55:00+08:00"}}], NOW - timedelta(days=1))
    with GuardianStore(job.path) as ledger:
        ledger.conn.execute("UPDATE guardian_portfolio SET state_json=? WHERE id=1", (json.dumps(job.state),))
        ledger.conn.commit()
    ordinary_decide = MagicMock(side_effect=AssertionError("已触发风险合同应先执行，不能重新启动全市场研判"))
    monkeypatch.setattr(guardian, "decide", ordinary_decide)
    attempts = []

    def repair(_store, _cfg, original, meta, state, quotes, rejects, **kwargs):
        attempts.append(kwargs)
        assert_uncommitted_retry(job, state, kwargs, expected_fills=[])
        assert meta["source"] == "saved_risk_plan"
        assert original.orders[0].action == "stop_loss"
        assert rejects[0]["reject_code"] == "price_condition"
        assert kwargs["retry_payload"]["risk_events"][0]["status"] == "triggered"
        return GuardianDecision.model_validate({"summary": "核对8.87元新报价后继续止损",
            "orders": [trade(code, 4000, quotes[code]["price"], action="stop_loss", reason="重新授权止损") ]})

    monkeypatch.setattr(guardian, "repair_preflight", repair)
    result = guardian.execute_guardian({}, job.context)
    assert len(attempts) == 1 and result["risk_only"] and result["status"] == "success"
    assert result["fills"][0]["price_cents"] == 887
    assert result["risk_events"][0]["status"] == "executed"
    assert result["risk_events"][0]["executed_quantity"] == 4000
    ordinary_decide.assert_not_called()
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 1 and not ledger.state()["positions"]


@pytest.mark.parametrize("invalidation", ["config", "cancel"])
def test_invalidated_cycle_does_not_start_retry_or_commit_preflight_fills(tmp_path, monkeypatch, invalidation):
    quotes = {A: 10, B: 24.74}
    job = fixture_job(tmp_path, monkeypatch, [quotes, quotes])
    original_simulate = guardian.simulate
    invalidated = False

    def invalidate_after_simulation(*args, **kwargs):
        nonlocal invalidated
        result = original_simulate(*args, **kwargs)
        invalidated = True
        return result

    def config(_store):
        return {**job.cfg, "model": "changed"} if invalidated and invalidation == "config" else job.cfg

    def check_cancelled():
        if invalidated and invalidation == "cancel":
            raise JobCancelled("隔离回归取消")

    repair = MagicMock(side_effect=AssertionError("已取消或配置改变的轮次不能启动修正模型"))
    monkeypatch.setattr(guardian, "simulate", invalidate_after_simulation)
    monkeypatch.setattr(guardian, "get_config", config)
    monkeypatch.setattr(guardian, "repair_preflight", repair)
    job.context.check_cancelled = check_cancelled
    error = JobError if invalidation == "config" else JobCancelled
    with pytest.raises(error):
        guardian.execute_guardian({}, job.context)
    repair.assert_not_called()
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 0 and ledger.state() == job.state
        saved = ledger.recent()[0]["result"]
        assert not saved["ledger_committed"] and saved["fills"] == []
        assert [(fill["code"], fill["quantity"]) for fill in saved["preflight_fills"]] == [(A, 100)]


def test_expired_cycle_does_not_retry_or_commit_prior_preflight_fill(tmp_path, monkeypatch):
    quotes = {A: 10, B: 24.74}
    job = fixture_job(tmp_path, monkeypatch, [quotes, quotes])
    original_simulate = guardian.simulate

    def expire_after_simulation(*args, **kwargs):
        result = original_simulate(*args, **kwargs)
        job.clock.instant = NOW + timedelta(seconds=300)
        return result

    repair = MagicMock(side_effect=AssertionError("本轮有效期结束不能再启动修正模型"))
    monkeypatch.setattr(guardian, "simulate", expire_after_simulation)
    monkeypatch.setattr(guardian, "repair_preflight", repair)
    try:
        result = guardian.execute_guardian({}, job.context)
    except JobError:
        # 过期可在预检或提交前收口，两条路径都不得提交旧成交意图。
        pass
    else:
        assert result["fills"] == []
    repair.assert_not_called()
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 0 and ledger.state()["cash_cents"] == job.state["cash_cents"]
        assert {p["code"]: p["quantity"] for p in ledger.state()["positions"]} == {A: 400, B: 300}
        assert ledger.recent()[0]["result"]["fills"] == []


def test_limit_up_buy_rejected_in_real_cycle_while_existing_sell_commits(tmp_path, monkeypatch):
    code = "000823"
    prices = {A: 10, B: 24.25, code: 22.32}
    initial = GuardianDecision(summary="拟减仓并参与超声电子", orders=[
        trade(A, 100, 10), trade(code, 1200, 22.32, action="buy")])
    job = fixture_job(tmp_path, monkeypatch, [prices, prices], initial_decision=initial)
    snapshot = guardian.build_monitor_snapshot

    def with_limit_reference(codes, **kwargs):
        result = snapshot(codes, **kwargs)
        if code in result.quotes:
            result.quotes[code]["prev_close"] = 20.29
        return result

    monkeypatch.setattr(guardian, "build_monitor_snapshot", with_limit_reference)
    monkeypatch.setattr(guardian, "repair_preflight", lambda _s, _c, original, *_a, **_k: original)
    result = guardian.execute_guardian({}, job.context)
    assert result["ledger_committed"] and result["status"] == "failed"
    assert [(fill["code"], fill["quantity"]) for fill in result["fills"]] == [(A, 100)]
    assert result["rejects"][0]["code"] == code and "涨停" in result["rejects"][0]["reason"]
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 1
        assert {p["code"]: p["quantity"] for p in ledger.state()["positions"]} == {A: 300, B: 300}
        assert ledger.recent()[0]["result"]["fills"] == result["fills"]


def test_commit_check_rejects_quote_that_reaches_limit_after_preflight(tmp_path, monkeypatch):
    code = "000823"
    prices = {A: 10, B: 24.25, code: 22.31}
    initial = GuardianDecision(summary="拟买入未涨停股票", orders=[trade(code, 1200, 22.31, action="buy")])
    job = fixture_job(tmp_path, monkeypatch, [prices, prices], initial_decision=initial)
    snapshot = guardian.build_monitor_snapshot
    simulate = guardian.simulate

    def with_limit_reference(codes, **kwargs):
        result = snapshot(codes, **kwargs)
        if code in result.quotes:
            result.quotes[code]["prev_close"] = 20.29
        return result

    def limit_after_preflight(state, value, candidates, quotes, now, **kwargs):
        result = simulate(state, value, candidates, quotes, now, **kwargs)
        assert result[1] and result[1][0]["price_cents"] == 2231
        quotes[code]["price"] = 22.32
        return result

    monkeypatch.setattr(guardian, "build_monitor_snapshot", with_limit_reference)
    monkeypatch.setattr(guardian, "simulate", limit_after_preflight)
    with pytest.raises(JobError, match="涨停"):
        guardian.execute_guardian({}, job.context)
    with GuardianStore(job.path) as ledger:
        assert ledger.trades()["total"] == 0 and ledger.state() == job.state
        saved = ledger.recent()[0]["result"]
        assert not saved["ledger_committed"] and saved["fills"] == []
        assert saved["failure_stage"] == "commit" and saved["preflight_fills"][0]["price_cents"] == 2231
