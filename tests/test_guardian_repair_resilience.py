"""模型单笔越权或修正轮照抄旧输出时，不能把整轮（含止损卖单）一起作废。"""
import json
from datetime import datetime
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
QUOTE = {"code": "600000", "name": "浦发银行", "price": 10.0, "trade_date": "2026-09-23",
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
