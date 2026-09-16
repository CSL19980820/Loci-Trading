"""失败必须保留意图且不冒充成交；预检与最终价格授权保持一致。"""
from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest

from src.ledger import GuardianStore
from src.ops.application.guardian_decision import simulate
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobCancelled, JobError
from tests.ops import test_guardian, test_guardian_execution_safety as safety

runtime = test_guardian.runtime
no_network = safety.no_network


def saved_result(context) -> dict:
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 0
        assert ledger.state() == test_guardian.EMPTY
        return ledger.recent()[0]["result"]


def test_quote_failure_keeps_order_and_authorization(runtime, monkeypatch) -> None:
    context, decide, notify = runtime
    proposed = safety.intent(max_price=10.1)
    decide.return_value = (proposed, {"model": "test"})

    def unavailable(*args, **kwargs):
        raise ValueError("execution quote unavailable")

    monkeypatch.setattr(guardian, "build_monitor_snapshot", unavailable)
    with pytest.raises(JobError, match="execution quote unavailable"):
        guardian.execute_guardian({}, context)
    saved = saved_result(context)
    assert saved["decisions"] == proposed.model_dump(mode="json")["orders"]
    assert saved["original_decision"] == proposed.model_dump(mode="json")
    assert saved["failure_stage"] == "final_quotes"
    assert saved["ledger_committed"] is False and saved["fills"] == []
    assert saved["outcome"] == "rejected"
    assert saved["blocked"][0]["reject_code"] == "execution_failed"
    assert saved["blocked"][0]["execution"]["max_price"] == 10.1
    assert saved["decision_context"]
    notify.assert_called_once()


def test_rollback_keeps_preflight_evidence_but_not_fake_fills(runtime, monkeypatch) -> None:
    context, decide, notify = runtime
    proposed = safety.intent()
    decide.return_value = (proposed, {})
    real_finish = GuardianStore.finish

    def reject_commit(self, slot, result, state=None, **kwargs):
        if state is not None:
            def blocked():
                raise ValueError("final commit rejected")
            kwargs["before_commit"] = blocked
        return real_finish(self, slot, result, state, **kwargs)

    monkeypatch.setattr(GuardianStore, "finish", reject_commit)
    with pytest.raises(JobError, match="final commit rejected"):
        guardian.execute_guardian({}, context)
    saved = saved_result(context)
    assert saved["failure_stage"] == "commit"
    assert saved["ledger_committed"] is False
    assert saved["fills"] == [] and saved["risk_events"] == []
    assert len(saved["preflight_fills"]) == 1
    assert saved["notification_facts"]["buy_count"] == 0
    assert saved["notification_facts"]["fees_cents"] == 0
    assert "本轮无已落账成交" in saved["body"]
    assert saved["preflight_fills"][0]["code"] == "600001"
    assert saved["blocked"][0]["reject_code"] == "execution_failed"
    assert saved["original_decision"] == proposed.model_dump(mode="json")
    assert saved["decisions"][0]["execution"]["reference_price"] == 10.0
    assert saved["decisions"][0]["code"] == proposed.orders[0].code
    notify.assert_called_once()


def test_cancelled_quote_retains_intent_without_new_notice(runtime, monkeypatch) -> None:
    context, decide, notify = runtime
    proposed = safety.intent()
    decide.return_value = (proposed, {})
    context._cancel_event = Event()

    def cancelled(*args, **kwargs):
        context._cancel_event.set()
        return SimpleNamespace(quotes=test_guardian.quotes(10))

    monkeypatch.setattr(guardian, "build_monitor_snapshot", cancelled)
    with pytest.raises(JobCancelled):
        guardian.execute_guardian({}, context)
    saved = saved_result(context)
    assert saved["status"] == saved["outcome"] == "cancelled"
    assert saved["ledger_committed"] is False and saved["fills"] == []
    assert saved["decisions"] == proposed.model_dump(mode="json")["orders"]
    assert saved["blocked"][0]["reject_code"] == "cancelled"
    notify.assert_not_called()


def test_research_failure_does_not_invent_an_order(runtime) -> None:
    context, decide, _ = runtime
    decide.side_effect = ValueError("research incomplete")
    with pytest.raises(JobError, match="research incomplete"):
        guardian.execute_guardian({}, context)
    saved = saved_result(context)
    assert saved["failure_stage"] == "research"
    assert saved["outcome"] == "failed"
    assert saved["decisions"] == saved["fills"] == saved["blocked"] == []
    assert saved["original_decision"] is None and saved["ledger_committed"] is False


@pytest.mark.parametrize("price,bounds", [(10.206, {"max_price": 10.006}), (9.804, {"min_price": 10.004})])
def test_preflight_rejects_rounded_price_outside_authorization(price, bounds) -> None:
    proposed = safety.intent(**bounds)
    state, fills, rejects = simulate(test_guardian.EMPTY, proposed, [], test_guardian.quotes(price),
                                      test_guardian.NOW, require_execution_terms=True)
    assert fills == [] and rejects[0]["reject_code"] == "price_condition"
    assert state["cash_cents"] == test_guardian.EMPTY["cash_cents"]
    assert state["positions"] == []


def test_bad_rounded_price_does_not_rollback_independent_legal_order(runtime, monkeypatch) -> None:
    context, decide, notify = runtime
    proposed = safety.intent(max_price=10.006)
    proposed.orders.append(safety.intent(code="600002").orders[0])
    decide.return_value = (proposed, {})
    market = {**test_guardian.quotes(10.206),
              "600002": {**test_guardian.quotes(10)["600001"], "code": "600002"}}
    monkeypatch.setattr(guardian, "build_monitor_snapshot", lambda *a, **kw: SimpleNamespace(quotes=market))
    result = guardian.execute_guardian({}, context)
    assert result["status"] == "failed" and result["outcome"] == "partial_execution"
    assert [f["code"] for f in result["fills"]] == ["600002"]
    assert result["rejects"][0]["code"] == "600001"
    assert result["rejects"][0]["reject_code"] == "price_condition"
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1
        assert [p["code"] for p in ledger.state()["positions"]] == ["600002"]
    notify.assert_called_once()
