"""模型单笔越权或修正轮照抄旧输出时，不能把整轮（含止损卖单）一起作废。"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.ledger.domain.guardian_account import (
    new_guardian_account,
    settle_guardian_order,
)
from src.ops.application import (
    guardian_agent,
    guardian_completion,
    guardian_config,
    guardian_order_repair,
)
from src.ops.application.guardian_decision import GuardianDecision, simulate
from src.ops.application.guardian_opening_plans import validate_opening_reviews
from src.ops.application.guardian_order_repair import (
    inherit_bound_terms,
    repair_preflight,
    validate_correction,
)
from src.ops.application.guardian_research_context import ResearchContext

NOW = datetime.fromisoformat("2026-09-23T10:00:00+08:00")
EXECUTION = {"kind": "market", "valid_until": "2026-09-23T10:04:00+08:00"}
SELL = {"code": "600000", "action": "sell", "quantity": 100, "reason": "止损", "execution": EXECUTION}
STAR_BUY = {"code": "688825", "action": "buy", "quantity": 200, "reason": "看好", "execution": EXECUTION}
QUOTE = {"code": "600000", "name": "浦发银行", "price": 10.0, "prev_close": 10.0, "trade_date": "2026-09-23",
         "trade_time": "09:59:40", "source": "tencent"}


def agent_result(text):
    return SimpleNamespace(text=text, finish_reason="stop", stopped_reason="completed", input_tokens=10,
                           output_tokens=5, messages=[{"role": "user", "content": "研判"}])


def live_parser(monkeypatch, pending_plans=()):
    """取出 guardian_agent.decide 内真实使用的决策解析器。"""
    import src.ai
    monkeypatch.setattr(src.ai, "resolve_config", lambda *a, **k: SimpleNamespace(model="fixture", protocol="openai"))
    monkeypatch.setattr(guardian_agent, "compose_research_tools", lambda *a, **k: ([], lambda *_: {}, {}))
    captured = {}

    def complete(provider, store, **kwargs):
        captured["parser"] = kwargs["decision_parser"]
        return GuardianDecision(summary="等待", orders=[]), {"tools": []}

    monkeypatch.setattr(guardian_agent, "complete_decision", complete)
    cfg = {**guardian_config.DEFAULTS, "model": "fixture"}
    guardian_agent.decide(None, cfg, {"as_of": NOW.isoformat(), "portfolio": {"positions": []},
                                      "pending_opening_plans": list(pending_plans)})
    return captured["parser"]


def run_completion(monkeypatch, parser, texts):
    calls = []

    def fake_agent(provider, store, usage, **arguments):
        calls.append(arguments)
        return agent_result(texts[len(calls) - 1])

    monkeypatch.setattr(guardian_completion, "run_accounted_agent", fake_agent)
    provider = SimpleNamespace(model="fixture", context_window=None, max_output_tokens=None)
    decision, usage = guardian_completion.complete_decision(
        provider, None, system="s", payload={}, schemas=[], execute=lambda *_: {}, archive=ResearchContext(),
        checkpoint=lambda *_: None, deadline=10**9, config={}, decision_parser=parser)
    return decision, usage, calls


def held_state():
    state = new_guardian_account()
    settle_guardian_order(state, {"code": "600000", "action": "buy", "quantity": 100, "reason": "昨日建仓"},
                          {"price": 10}, NOW.replace(day=22), {})
    return state


def test_forbidden_buy_after_repair_keeps_stop_loss_executable(monkeypatch):
    parser = live_parser(monkeypatch)
    text = json.dumps({"summary": "止损并买入", "orders": [SELL, STAR_BUY]})
    decision, usage, calls = run_completion(monkeypatch, parser, [text, text])
    assert [o.code for o in decision.orders] == ["600000", "688825"]
    assert usage["attempts"][1]["accepted_with_policy_rejects"] is True
    repair_prompt = calls[1]["messages"][-1].content
    assert "账户权限校验未通过" in repair_prompt and "保留原判断" not in repair_prompt

    _, fills, rejects = simulate(held_state(), decision, [], {"600000": QUOTE}, NOW, require_execution_terms=True)
    assert [(f["code"], f["action"]) for f in fills] == [("600000", "sell")]
    assert [(r["code"], r["reject_code"]) for r in rejects] == [("688825", "board_not_allowed")]


def test_broken_repair_falls_back_to_policy_checked_original(monkeypatch):
    parser = live_parser(monkeypatch)
    text = json.dumps({"summary": "止损并买入", "orders": [SELL, STAR_BUY]})
    decision, usage, _ = run_completion(monkeypatch, parser, [text, '{"summary": "修复半截'])
    assert [o.code for o in decision.orders] == ["600000", "688825"]
    assert usage["attempts"][1]["fallback"] == "policy_rejected_original"
    assert usage["raw"] == text


def test_repair_that_withdraws_forbidden_buy_is_used(monkeypatch):
    parser = live_parser(monkeypatch)
    first = json.dumps({"summary": "止损并买入", "orders": [SELL, STAR_BUY]})
    fixed = json.dumps({"summary": "止损，科创板改观察", "orders": [
        SELL, {"code": "688825", "action": "watch", "quantity": 0, "reason": "账户不可买"}]})
    decision, _, _ = run_completion(monkeypatch, parser, [first, fixed])
    assert [(o.code, o.action) for o in decision.orders] == [("600000", "sell"), ("688825", "watch")]


def test_non_policy_contract_errors_still_fail_after_one_repair(monkeypatch):
    parser = live_parser(monkeypatch)
    with pytest.raises(ValueError):
        run_completion(monkeypatch, parser, ['{"summary": ', '{"summary": '])


def test_structural_opening_review_errors_are_not_downgraded_to_policy(monkeypatch):
    plans = [{"id": "p1", "order": {"code": "600000", "action": "buy"}}]
    parser = live_parser(monkeypatch, plans)
    text = json.dumps({"summary": "漏复核竞价计划且买科创板", "orders": [STAR_BUY]})
    with pytest.raises(ValueError, match="逐笔复核") as caught:
        parser(text, require_execution_terms=True)
    assert type(caught.value) is ValueError


def bound_original():
    buy = {"code": "600000", "action": "buy", "quantity": 400, "reason": "竞价计划执行", "opening_plan_id": "p1",
           "execution": {**EXECUTION, "reference_price": 10.0}}
    return GuardianDecision.model_validate({
        "summary": "执行竞价计划",
        "opening_plan_reviews": [{"plan_id": "p1", "decision": "execute", "reason": "竞价强"}],
        "orders": [buy]})


def test_correction_inherits_program_bound_reference_and_plan():
    corrected = GuardianDecision.model_validate({"summary": "缩量", "orders": [
        {"code": "600000", "action": "buy", "quantity": 200, "reason": "资金不足缩量", "execution": EXECUTION}]})
    with pytest.raises(ValueError, match="参考价"):
        validate_correction(bound_original(), corrected)
    inherited = inherit_bound_terms(bound_original(), corrected)
    validate_correction(bound_original(), inherited)
    assert inherited.orders[0].execution.reference_price == 10.0
    assert inherited.orders[0].opening_plan_id == "p1"


def repair(monkeypatch, corrected_orders):
    import src.ai
    monkeypatch.setattr(src.ai, "resolve_config",
                        lambda *a, **k: SimpleNamespace(model="fixture", max_output_tokens=None))
    text = json.dumps({"summary": "修正", "orders": corrected_orders})
    monkeypatch.setattr(guardian_order_repair, "run_accounted_agent", lambda *a, **k: agent_result(text))
    original = bound_original()
    meta = {"_repair": {"messages": [], "system": "s", "text": original.model_dump_json()}, "tools": []}
    rejects = [{**original.orders[0].model_dump(mode="json"), "reject_code": "cash", "reason": "现金不足"}]
    corrected = repair_preflight(None, {"provider": "p", "model": "fixture"}, original, meta,
                                 new_guardian_account(), {}, rejects, check_cancelled=lambda: None, deadline=10**9)
    return original, corrected, meta


def test_preflight_repair_reduces_quantity_without_losing_binding(monkeypatch):
    original, corrected, meta = repair(monkeypatch, [
        {"code": "600000", "action": "buy", "quantity": 200, "reason": "缩量", "execution": EXECUTION}])
    assert meta["preflight_repair"]["status"] == "corrected"
    assert corrected.orders[0].quantity == 200
    assert corrected.orders[0].execution.reference_price == 10.0
    assert corrected.opening_plan_reviews == original.opening_plan_reviews
    validate_opening_reviews(corrected, [{"id": "p1", "order": {"code": "600000", "action": "buy"}}])


def test_withdrawn_opening_plan_order_is_blocked_not_cycle_failure(monkeypatch):
    plans = [{"id": "p1", "order": {"code": "600000", "action": "buy"}}]
    _, corrected, meta = repair(monkeypatch, [
        {"code": "600000", "action": "buy", "quantity": 0, "reason": "资金不足撤回", "execution": EXECUTION}])
    assert meta["preflight_repair"]["status"] == "corrected"
    assert corrected.orders == []
    with pytest.raises(ValueError, match="执行计划须绑定新订单"):
        validate_opening_reviews(corrected, plans)
    validate_opening_reviews(corrected, plans, withdrawn_plan_ids={"p1"})


def preflight_retry(monkeypatch, original, orders, rejects, *, meta=None, **kwargs):
    import src.ai
    monkeypatch.setattr(src.ai, "resolve_config",
                        lambda *a, **k: SimpleNamespace(model="fixture", max_output_tokens=None))
    text = json.dumps({"summary": "按拒单重新研判", "orders": orders})
    calls = []

    def complete(*args, **arguments):
        calls.append(arguments)
        return agent_result(text)

    monkeypatch.setattr(guardian_order_repair, "run_accounted_agent", complete)
    if meta is None:
        meta = {"_repair": {"messages": [], "system": "s", "text": original.model_dump_json()}, "tools": []}
    corrected = repair_preflight(None, {"provider": "p", "model": "fixture"}, original, meta,
        new_guardian_account(), {"600000": {**QUOTE, "price": 10.4}}, rejects,
        check_cancelled=lambda: None, deadline=10**9, execution_deadline=NOW + timedelta(minutes=5), **kwargs)
    return corrected, meta, calls


def blocked_reject(original, code="price_condition"):
    return {**original.orders[0].model_dump(mode="json"), "reject_code": code, "reason": "预检受阻"}


def test_price_failure_model_explicitly_renews_reference_and_can_fill(monkeypatch):
    original = bound_original()
    quotes = {"600000": {**QUOTE, "price": 10.4}}
    _, fills, rejects = simulate(new_guardian_account(), original, [], quotes, NOW, require_execution_terms=True)
    assert not fills and rejects[0]["reject_code"] == "price_condition"
    order = original.orders[0].model_dump(mode="json")
    order["execution"] = {**EXECUTION, "reference_price": 10.4,
                          "valid_until": (NOW + timedelta(minutes=5)).isoformat()}
    corrected, meta, calls = preflight_retry(monkeypatch, original, [order], rejects)
    _, fills, rejects = simulate(new_guardian_account(), corrected, [], quotes, NOW, require_execution_terms=True)
    assert len(fills) == 1 and not rejects
    assert fills[0]["price_cents"] == 1040
    assert corrected.orders[0].execution.reference_price == 10.4
    assert meta["preflight_repair_attempts"] == [meta["preflight_repair"]]
    request = json.loads(calls[0]["messages"][-1].content)
    assert request["renewal_keys"] == [{"code": "600000", "action": "buy"}]
    assert "不是已成交" in request["instruction"]
    assert meta["_repair"]["text"] == json.dumps({"summary": "按拒单重新研判", "orders": [order]})


@pytest.mark.parametrize("unauthorized", ["new_stock", "extra_quantity", "successful_order", "non_trade"])
def test_retry_rejects_new_intents_over_quantity_or_edits_to_success(monkeypatch, unauthorized):
    original = bound_original()
    successful = {**SELL, "code": "600001"}
    watch = {"code": "600002", "action": "watch", "reason": "继续观察"}
    original = original.model_copy(update={"orders": original.orders + GuardianDecision.model_validate({
        "summary": "其他意图", "orders": [successful, watch]}).orders})
    order = original.orders[0].model_dump(mode="json")
    orders = [order]
    if unauthorized == "new_stock":
        order["code"] = "600003"
    elif unauthorized == "extra_quantity":
        order["quantity"] = 500
    elif unauthorized == "successful_order":
        orders.append({**successful, "quantity": 0})
    else:
        orders.append({**watch, "reason": "修改了成功的观察条件"})
    corrected, meta, calls = preflight_retry(monkeypatch, original, orders, [blocked_reject(original, "cash")],
        preflight_fills=[{"code": "600001", "action": "sell", "quantity": 100}],
        retry_payload={"preflight_portfolio": {"cash_cents": 12345}})
    assert corrected is original
    assert meta["preflight_repair"]["status"] == "failed"
    request = json.loads(calls[0]["messages"][-1].content)
    assert [o["code"] for o in request["original_decision"]["orders"]] == ["600000"]
    assert request["preflight_fills"][0]["code"] == "600001"
    assert request["preflight_portfolio"] == {"cash_cents": 12345}
    assert request["ledger_committed"] is False


def test_retry_preserves_successful_trades_and_non_trade_orders_once(monkeypatch):
    original = bound_original()
    retained = GuardianDecision.model_validate({"summary": "其他意图", "orders": [
        {**SELL, "code": "600001"}, {"code": "600002", "action": "watch", "reason": "等候条件"}]}).orders
    original = original.model_copy(update={"orders": [retained[0], original.orders[0], retained[1]]})
    order = original.orders[1].model_dump(mode="json")
    order["quantity"] = 200
    reject = {**order, "reject_code": "cash", "reason": "资金不足"}
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [reject])
    assert meta["preflight_repair"]["status"] == "corrected"
    assert corrected.orders == [retained[0], original.orders[1].model_copy(update={"quantity": 200}), retained[1]]
    assert original.orders[1].quantity == 400


@pytest.mark.parametrize("code", ["cash", "quantity", "quote_unavailable", "liquidity_unconfirmed", "risk_plan",
                                 "board_not_allowed"])
def test_non_price_rejection_cannot_renew_reference_or_deadline(monkeypatch, code):
    original = bound_original()
    order = original.orders[0].model_dump(mode="json")
    order["execution"]["reference_price"] = 10.4
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [blocked_reject(original, code)])
    assert corrected is original and "参考价" in meta["preflight_repair"]["error"]
    order["execution"]["reference_price"] = 10.0
    order["execution"]["valid_until"] = (NOW + timedelta(minutes=5)).isoformat()
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [blocked_reject(original, code)])
    assert corrected is original and "延长" in meta["preflight_repair"]["error"]


def test_price_renewal_requires_explicit_market_reference_and_bounded_deadline(monkeypatch):
    original = bound_original()
    order = original.orders[0].model_dump(mode="json")
    order["execution"].pop("reference_price")
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [blocked_reject(original)])
    assert corrected is original and "明确新的执行参考价" in meta["preflight_repair"]["error"]
    order["execution"]["reference_price"] = 10.4
    order["execution"]["valid_until"] = (NOW + timedelta(minutes=6)).isoformat()
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [blocked_reject(original)])
    assert corrected is original and "截止时间" in meta["preflight_repair"]["error"]


def test_old_validate_correction_remains_strict_without_renewal_authorization():
    original = bound_original()
    corrected = original.model_copy(deep=True)
    corrected.orders[0].execution.reference_price = 10.4
    with pytest.raises(ValueError, match="参考价"):
        validate_correction(original, corrected)
    validate_correction(original, corrected, renewal_keys={("600000", "buy")},
                        execution_deadline=NOW + timedelta(minutes=5))


def test_expired_intent_model_renews_price_and_expiry(monkeypatch):
    original = bound_original()
    original.orders[0].execution.valid_until = (NOW - timedelta(seconds=1)).isoformat()
    order = original.orders[0].model_dump(mode="json")
    order["execution"].update(reference_price=10.4, valid_until=(NOW + timedelta(minutes=5)).isoformat())
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [blocked_reject(original, "intent_expired")])
    assert meta["preflight_repair"]["status"] == "corrected"
    assert corrected.orders[0].execution.valid_until == (NOW + timedelta(minutes=5)).isoformat()


def test_risk_retry_without_continuation_uses_decide_and_merges_usage(monkeypatch):
    original = GuardianDecision.model_validate({"summary": "触发止损", "orders": [
        {**SELL, "action": "stop_loss", "execution": {**EXECUTION, "reference_price": 10.0}}]})
    corrected = original.model_copy(deep=True)
    corrected.orders[0].execution.reference_price = 10.4
    calls = []
    continuation = {"messages": [], "system": "s", "text": corrected.model_dump_json()}

    def decide(store, config, payload, **arguments):
        calls.append((payload, arguments))
        return corrected, {"input_tokens": 7, "output_tokens": 3, "rounds": 1, "tool_calls": 1,
                           "tools": [{"name": "fresh_quote"}], "_repair": continuation}

    monkeypatch.setattr(guardian_agent, "decide", decide)
    meta = {"input_tokens": 10, "output_tokens": 5, "rounds": 2, "tool_calls": 1,
            "tools": [{"name": "prior_quote"}]}
    retry_payload = {"as_of": NOW.isoformat(), "portfolio": held_state(), "risk_events": [{"code": "600000"}],
                     "risk_only": True, "palace_db_path": "isolated-palace.db"}
    result, meta, agent_calls = preflight_retry(monkeypatch, original, [], [blocked_reject(original)],
        meta=meta, retry_payload=retry_payload)
    assert not agent_calls and result.orders[0].execution.reference_price == 10.4
    assert calls[0][0]["retry_only"] is True
    assert calls[0][0]["risk_events"] == retry_payload["risk_events"]
    assert calls[0][1]["palace_db_path"] == "isolated-palace.db"
    assert (meta["input_tokens"], meta["output_tokens"], meta["rounds"], meta["tool_calls"]) == (17, 8, 3, 2)
    assert meta["_repair"] is continuation
    assert len(meta["tools"]) == 2


def test_retry_budget_exhausted_preserves_reject_and_records_attempt(monkeypatch):
    original = bound_original()
    monkeypatch.setattr(guardian_order_repair.time, "monotonic", lambda: 100)
    meta = {}
    called = []
    monkeypatch.setattr(guardian_agent, "decide", lambda *a, **k: called.append(k))
    result = repair_preflight(None, {"provider": "p", "model": "fixture"}, original, meta,
        new_guardian_account(), {}, [blocked_reject(original)], check_cancelled=lambda: None, deadline=115,
        retry_payload={"as_of": NOW.isoformat()})
    assert result is original and not called
    assert meta["preflight_repair"]["status"] == "skipped"
    assert meta["preflight_repair_attempts"] == [meta["preflight_repair"]]


def test_risk_only_retry_cannot_change_persisted_risk_contract(monkeypatch):
    original = GuardianDecision.model_validate({"summary": "触发止损", "orders": [
        {**SELL, "action": "stop_loss", "execution": {**EXECUTION, "reference_price": 10.0}}]})
    order = original.orders[0].model_dump(mode="json")
    order["risk_plans"] = []
    corrected, meta, _ = preflight_retry(monkeypatch, original, [order], [blocked_reject(original, "cash")],
                                       retry_payload={"risk_only": True})
    assert corrected is original and "风险合同" in meta["preflight_repair"]["error"]


def test_fallback_then_continuation_preserves_prior_evidence_and_attempt_history(monkeypatch):
    import src.ai
    original = bound_original()
    first = original.model_copy(deep=True)
    first.orders[0].execution.reference_price = 10.4
    archive = ResearchContext()
    archive.record("first_refresh", {}, {"text": "10.4"}, 1)
    continuation = {"messages": [], "system": "s", "text": first.model_dump_json(), "archive": archive}
    monkeypatch.setattr(guardian_agent, "decide", lambda *a, **k: (first, {
        "tools": list(archive.receipts), "context_documents": {}, "_repair": continuation}))
    meta = {"tools": [{"name": "pre_model_evidence"}], "context_documents": {"prior": {"text": "原证据"}}}
    first = repair_preflight(None, {"provider": "p", "model": "fixture"}, original, meta,
        new_guardian_account(), {}, [blocked_reject(original)], check_cancelled=lambda: None, deadline=10**9,
        execution_deadline=NOW + timedelta(minutes=5), retry_payload={"as_of": NOW.isoformat()})
    second = first.model_copy(deep=True)
    second.orders[0].execution.reference_price = 10.7
    text = second.model_dump_json()
    calls = []

    def complete(*a, **k):
        calls.append(k)
        archive.record("second_refresh", {}, {"text": "10.7"}, 1)
        return agent_result(text)

    monkeypatch.setattr(src.ai, "resolve_config", lambda *a, **k: SimpleNamespace(model="fixture", max_output_tokens=None))
    monkeypatch.setattr(guardian_order_repair, "run_accounted_agent", complete)
    result = repair_preflight(None, {"provider": "p", "model": "fixture"}, first, meta,
        new_guardian_account(), {}, [blocked_reject(first)], check_cancelled=lambda: None, deadline=10**9,
        execution_deadline=NOW + timedelta(minutes=5))
    assert result.orders[0].execution.reference_price == 10.7
    assert calls[0]["messages"][-2].content == first.model_dump_json()
    assert meta["_repair"]["text"] == text
    assert len(meta["preflight_repair_attempts"]) == 2
    assert [item["name"] for item in meta["tools"]] == ["pre_model_evidence", "first_refresh", "second_refresh"]
    assert meta["context_documents"]["prior"] == {"text": "原证据"}


@pytest.mark.parametrize("exception", [TimeoutError("时间耗尽"),
    pytest.param(None, id="cancelled")])
def test_retry_cancellation_and_timeout_propagate_with_usage(monkeypatch, exception):
    from src.ops.application.jobs.context import JobCancelled
    exception = exception or JobCancelled("用户取消")
    original = bound_original()
    meta = {"_repair": {"messages": [], "system": "s", "text": original.model_dump_json()}, "tools": []}

    def cancel():
        raise exception

    with pytest.raises(type(exception)) as caught:
        repair_preflight(None, {"provider": "p", "model": "fixture"}, original, meta,
            new_guardian_account(), {}, [blocked_reject(original)], check_cancelled=cancel, deadline=10**9)
    assert caught.value.usage is meta
