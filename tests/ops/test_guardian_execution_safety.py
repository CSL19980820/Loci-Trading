from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from typing import Any
import pytest
from src.ledger import GuardianStore
from src.ops.application.guardian_contract import ExecutionTerms, completion_error
from src.ops.application.guardian_decision import GuardianDecision, simulate
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobCancelled, JobError
from tests.ops import test_guardian
from tests.ops.test_guardian import EMPTY, NOW, decision, quotes
runtime = test_guardian.runtime


@pytest.fixture(autouse=True)
def no_network(monkeypatch) -> Iterator[None]:
    leaked = []

    def forbidden(*args, **kwargs) -> None:
        leaked.append("network")
        raise AssertionError("External calls must be mocked")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    yield
    assert not leaked, "A swallowed network error must still fail this test"


def intent(action="buy", quantity=100, code="600001", **bounds) -> GuardianDecision:
    proposed = decision(action, quantity, code)
    proposed.orders[0].execution = ExecutionTerms(
        kind="limit" if bounds else "market",
        valid_until=(NOW + timedelta(minutes=5)).isoformat(), **bounds,
    )
    return proposed


def assert_failed_without_fills(context) -> dict[str, Any]:
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 0
        assert ledger.state()["cash_cents"] == EMPTY["cash_cents"]
        assert ledger.state()["positions"] == []
        row = ledger.recent()[0]
        assert row["status"] == row["result"]["status"] == "failed"
        return row["result"]


def test_cancel_during_quote_does_not_commit_or_notify(runtime, monkeypatch) -> None:
    context, _, notify = runtime
    context._cancel_event = Event()
    def cancelled_quote(*args, **kwargs) -> SimpleNamespace:
        context._cancel_event.set()
        return SimpleNamespace(quotes=quotes(10))
    monkeypatch.setattr(guardian, "build_monitor_snapshot", cancelled_quote)
    with pytest.raises(JobCancelled):
        guardian.execute_guardian({}, context)
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 0
        assert ledger.state() == EMPTY
        assert ledger.recent()[0]["status"] == "cancelled"
    notify.assert_not_called()


def test_wrong_stock_quote_never_changes_valuation() -> None:
    state, _, _ = simulate(EMPTY, decision(), [], quotes(10), NOW)
    tomorrow = NOW.replace(day=14)
    polluted = quotes(20, tomorrow)
    polluted["600001"]["code"] = "600002"
    updated, fills, rejects = simulate(state, decision("sell"), [], polluted, tomorrow)
    assert not fills and rejects[0]["reject_code"] == "quote_unavailable"
    assert updated["positions"][0]["mark_price_cents"] == 1000
    assert updated["positions"][0]["market_value_cents"] == 100000
    assert updated["stale_codes"] == ["600001"]


@pytest.mark.parametrize("reason", ["", None, "length", "max_tokens", "tool_calls", "content_filter", "unexpected"])
def test_completion_rejects_every_non_terminal_finish_reason(reason) -> None:
    assert completion_error(SimpleNamespace(stopped_reason="completed", finish_reason=reason))


def test_completion_requires_an_explicit_finish_reason() -> None:
    assert completion_error(SimpleNamespace(stopped_reason="completed"))


@pytest.mark.parametrize("reason", ["stop", "end_turn"])
def test_completion_accepts_only_successfully_completed_turns(reason) -> None:
    assert completion_error(SimpleNamespace(stopped_reason="completed", finish_reason=reason)) == ""
    assert completion_error(SimpleNamespace(stopped_reason="max_rounds", finish_reason=reason))


def install_model_response(monkeypatch, reason) -> Mock:
    from src.ai import ProviderConfig
    from src.ai.application.agent import AgentResult
    from src.ops.application.guardian_agent import decide as real_decide

    provider = ProviderConfig("test", "openai_compatible", "https://example.invalid", "test", "test")
    monkeypatch.setattr("src.ai.resolve_config", lambda *args, **kwargs: provider)
    monkeypatch.setattr("src.ai.record_llm_usage", Mock())
    monkeypatch.setattr("src.ops.application.guardian_tools.agent_tools",
                        lambda *args, **kwargs: ([], Mock(), {}))
    response = AgentResult(text=intent().model_dump_json(), rounds=1, model="test",
                           finish_reason=reason, input_tokens=11, output_tokens=7)
    run = Mock(return_value=response)
    monkeypatch.setattr("src.ai.application.agent.run_agent", run)
    monkeypatch.setattr(guardian, "decide", real_decide)
    return run


@pytest.mark.parametrize("reason", ["length", "max_tokens", "", "tool_calls"])
def test_valid_order_json_with_incomplete_model_response_never_commits(runtime, monkeypatch, reason) -> None:
    context, _, notify = runtime
    run = install_model_response(monkeypatch, reason)
    with pytest.raises(JobError):
        guardian.execute_guardian({}, context)
    saved = assert_failed_without_fills(context)
    assert 1 <= run.call_count <= 2
    assert saved["usage"]["attempts"][0]["finish_reason"] == reason
    notify.assert_called_once()


@pytest.mark.parametrize("reason", ["stop", "end_turn"])
def test_complete_model_response_can_commit_once(runtime, monkeypatch, reason) -> None:
    context, _, notify = runtime
    run = install_model_response(monkeypatch, reason)
    result = guardian.execute_guardian({}, context)
    assert result["status"] == "success" and result["outcome"] == "traded"
    assert len(result["fills"]) == 1
    run.assert_called_once()
    notify.assert_called_once()
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1


def test_stale_primary_quote_uses_fresh_fallback(monkeypatch) -> None:
    from src.ops.application import guardian_tools

    primary = Mock(return_value={"structured": {"data": {
        "stock": {"code": "600001"},
        "points": [{"time": (NOW - timedelta(minutes=10)).isoformat(), "price": 10}],
    }}})
    backup_quotes = {"600001": {**quotes(10.8)["600001"], "source": "backup"}}
    fallback = Mock(return_value=SimpleNamespace(quotes=backup_quotes))
    monkeypatch.setattr(guardian_tools, "data_source", lambda: {"server": "wudao", "wudao": True})
    monkeypatch.setattr("src.intel.call_mcp_tool", primary)
    monkeypatch.setattr("src.market.application.live_cache.build_monitor_snapshot", fallback)
    snapshot = guardian_tools.snapshot(["600001"], now=NOW)
    primary.assert_called_once()
    fallback.assert_called_once()
    assert fallback.call_args.args[0] == ["600001"]
    assert snapshot.quotes["600001"]["price"] == 10.8
    assert snapshot.quotes["600001"]["source"] == "backup"
    assert snapshot.quotes["600001"]["primary_error"]
    _, fills, rejects = simulate(EMPTY, intent(), [], snapshot.quotes, NOW, require_execution_terms=True)
    assert len(fills) == 1 and not rejects


def test_rejected_half_lot_is_failed_and_notified(runtime) -> None:
    context, decide, notify = runtime
    decide.return_value = (intent(quantity=2250), {})
    result = guardian.execute_guardian({}, context)
    assert result["status"] == "failed" and result["outcome"] == "rejected"
    assert result["fills"] == []
    assert result["rejects"][0]["quantity"] == 2250
    assert result["rejects"][0]["reject_code"] == "quantity"
    assert_failed_without_fills(context)
    notify.assert_called_once()


def test_partial_execution_keeps_fill_and_notifies_rejected_intent(runtime, monkeypatch) -> None:
    context, decide, notify = runtime
    proposed = intent()
    proposed.orders.append(intent(quantity=2250, code="600002").orders[0])
    decide.return_value = (proposed, {})
    market = {**quotes(10), "600002": {**quotes(10)["600001"], "code": "600002"}}
    monkeypatch.setattr(guardian, "build_monitor_snapshot", lambda *args, **kwargs: SimpleNamespace(quotes=market))
    result = guardian.execute_guardian({}, context)
    assert result["status"] == "failed" and result["outcome"] == "partial_execution"
    assert [fill["code"] for fill in result["fills"]] == ["600001"]
    assert result["rejects"][0]["code"] == "600002"
    notify.assert_called_once()
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1
        assert ledger.state()["positions"][0]["quantity"] == 100
        assert len(ledger.state()["positions"]) == 1
        assert ledger.recent()[0]["status"] == "failed"


def test_natural_language_price_limit_does_not_authorize_a_market_fill() -> None:
    proposed = intent()
    proposed.orders[0].reason = "仅在不高于10.10元买入"
    proposed.orders[0].execution = None
    updated, fills, rejects = simulate(EMPTY, proposed, [], quotes(10.8), NOW, require_execution_terms=True)
    assert fills == [] and rejects[0]["reject_code"] == "missing_execution"
    assert updated["cash_cents"] == EMPTY["cash_cents"] and updated["positions"] == []


@pytest.mark.parametrize("price, fills_expected", [(10.10, True), (10.80, False)])
def test_structured_buy_limit_survives_final_price_refresh(runtime, monkeypatch, price, fills_expected) -> None:
    context, decide, notify = runtime
    proposed = intent(max_price=10.10)
    proposed.orders[0].reason = "仅在不高于10.10元买入"
    decide.return_value = (proposed, {})
    monkeypatch.setattr(guardian, "build_monitor_snapshot",
                        lambda *args, **kwargs: SimpleNamespace(quotes=quotes(price)))
    result = guardian.execute_guardian({}, context)
    assert bool(result["fills"]) is fills_expected
    notify.assert_called_once()
    if fills_expected:
        assert result["status"] == "success" and result["fills"][0]["price_cents"] == 1010
    else:
        assert result["status"] == "failed" and result["rejects"][0]["reject_code"] == "price_condition"
        assert_failed_without_fills(context)


def test_expired_execution_intent_is_rejected(runtime) -> None:
    context, decide, notify = runtime
    proposed = intent()
    proposed.orders[0].execution = ExecutionTerms(kind="market", valid_until=NOW.isoformat())
    decide.return_value = (proposed, {})
    result = guardian.execute_guardian({}, context)
    assert result["rejects"][0]["reject_code"] == "intent_expired"
    assert_failed_without_fills(context)
    notify.assert_called_once()


def test_preflight_withdrawal_preserves_failure_reason_and_notification(runtime, monkeypatch) -> None:
    context, decide, notify = runtime
    decide.return_value = (intent(quantity=2250), {})
    corrected = GuardianDecision(summary="撤回不能执行的意图", orders=[])
    repair = Mock(return_value=corrected)
    monkeypatch.setattr(guardian, "repair_preflight", repair)
    result = guardian.execute_guardian({}, context)
    repair.assert_called_once()
    assert result["status"] == "failed" and result["outcome"] == "rejected"
    assert result["decisions"] == result["fills"] == result["rejects"] == []
    assert result["initial_rejects"][0]["reject_code"] == "quantity"
    assert result["withdrawn"][0]["reject_code"] == "withdrawn"
    assert result["initial_rejects"][0]["reason"] in result["withdrawn"][0]["reason"]
    assert result["blocked"] == result["withdrawn"]
    saved = assert_failed_without_fills(context)
    assert saved["original_decision"]["orders"][0]["quantity"] == 2250
    assert saved["withdrawn"] == result["withdrawn"]
    notify.assert_called_once()


@pytest.mark.parametrize("slow_stage", ["research", "quote"])
def test_monotonic_expiry_prevents_fills_when_wall_clock_stands_still(runtime, monkeypatch, slow_stage) -> None:
    context, decide, notify = runtime
    monotonic = [1000.0]
    monkeypatch.setattr(guardian, "time", SimpleNamespace(monotonic=lambda: monotonic[0]))

    def delayed_decision(*args, **kwargs) -> tuple[GuardianDecision, dict]:
        monotonic[0] += 301
        return intent(), {}

    def delayed_quote(*args, **kwargs) -> SimpleNamespace:
        monotonic[0] += 301
        return SimpleNamespace(quotes=quotes(10))

    if slow_stage == "research":
        decide.side_effect = delayed_decision
    else:
        decide.return_value = (intent(), {})
        monkeypatch.setattr(guardian, "build_monitor_snapshot", delayed_quote)
    result = guardian.execute_guardian({}, context)
    assert guardian.datetime.now(NOW.tzinfo) == NOW
    assert result["fills"] == [] and result["analysis_only"]
    assert result["outcome"] == "rejected"
    assert result["blocked"][0]["reject_code"] == "execution_window"
    assert_failed_without_fills(context)
    notify.assert_called_once()


@pytest.mark.parametrize("wrong_owner", ["other-run", "", None])
def test_failed_finish_rejects_wrong_owner_without_creating_a_notice(tmp_path, wrong_owner) -> None:
    with GuardianStore(tmp_path / "owner.db") as ledger:
        assert ledger.claim("slot", run_id="expected-owner")
        notice = {"title": "失败", "body": "运行失败"}
        with pytest.raises(RuntimeError, match="所有权"):
            ledger.finish("slot", {"status": "failed"}, run_id=wrong_owner, notice=notice)
        assert ledger.recent()[0]["status"] == "running"
        assert ledger.recent()[0]["result"]["owner_run_id"] == "expected-owner"
        assert ledger.trades()["total"] == 0 and ledger.state() == EMPTY
        assert ledger.claim_notices() == []
        ledger.finish("slot", {"status": "failed"}, run_id="expected-owner", notice=notice)
        assert ledger.recent()[0]["status"] == "failed"
        assert len(ledger.claim_notices()) == 1


def test_rejected_2250_share_reduction_preserves_the_existing_position(runtime) -> None:
    context, decide, notify = runtime
    yesterday = NOW - timedelta(days=1)
    state, seed_fills, rejects = simulate(EMPTY, intent(quantity=3000), [], quotes(10, yesterday), yesterday)
    assert seed_fills and not rejects
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.claim("seed")
        ledger.finish("seed", {"fills": seed_fills}, state)
    decide.return_value = (intent("reduce", 2250), {})
    result = guardian.execute_guardian({}, context)
    assert result["status"] == "failed" and result["outcome"] == "rejected"
    assert result["fills"] == []
    assert result["rejects"][0]["action"] == "reduce"
    assert result["rejects"][0]["quantity"] == 2250
    assert result["rejects"][0]["reject_code"] == "quantity"
    notify.assert_called_once()
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1
        assert ledger.state()["positions"][0]["quantity"] == 3000
        assert ledger.state()["cash_cents"] == state["cash_cents"]
        assert ledger.recent()[0]["status"] == "failed"
