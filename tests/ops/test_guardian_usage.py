"""Each guardian agent invocation is billed once, including interrupted repairs."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from src.ai import ChatResponse, LLMError, ProviderConfig, ToolCall
from src.ai.application import agent
from src.ops import JobCancelled, JobTimedOut
from src.ops.application.guardian_completion import complete_decision
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.guardian_order_repair import repair_preflight
from src.shared.paths import ops_db
from src.shared.tenancy import current_tenant, submit_with_tenant, tenant_scope

PROVIDER = ProviderConfig(
    name="test", protocol="openai_compatible", base_url="https://example.invalid",
    api_key="test", model="test",
)
VALID = '{"summary":"hold","orders":[]}'


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SimpleNamespace:
    billing = Mock()
    monkeypatch.setattr("src.ai.record_llm_usage", billing)
    monkeypatch.setattr("src.ai.resolve_config", lambda *_a, **_kw: PROVIDER)
    monkeypatch.setattr(agent, "chat", Mock(side_effect=AssertionError("unexpected fallback")))
    return SimpleNamespace(
        store=SimpleNamespace(db_path=tmp_path / "usage.db"), billing=billing,
        archive=SimpleNamespace(receipts=[], documents=[]), checkpoint=lambda *_: None,
    )


def _response(text: str = VALID, tokens_in: int = 123, tokens_out: int = 45, *, tools: bool = False) -> ChatResponse:
    return ChatResponse(text=text, input_tokens=tokens_in, output_tokens=tokens_out, model="test", raw={"finish_reason": "stop"},
                        tool_calls=[ToolCall(id="read", name="read", arguments={})] if tools else [])


def _complete(context: SimpleNamespace, execute=None) -> tuple:
    return complete_decision(
        PROVIDER, context.store, system="test", payload={}, schemas=[],
        execute=execute, archive=context.archive, checkpoint=context.checkpoint,
        deadline=time.monotonic() + 270, config={},
    )


def _bill(context: SimpleNamespace, tokens_in: int, tokens_out: int) -> call:
    return call(provider="test", model="test", input_tokens=tokens_in, output_tokens=tokens_out,
                ops_db=str(context.store.db_path))


def _meta() -> dict:
    return {"model": "test", "input_tokens": 10, "output_tokens": 3, "rounds": 1,
            "_repair": {"messages": [], "system": "test", "text": VALID}}


def _preflight(context: SimpleNamespace, meta: dict) -> GuardianDecision:
    return repair_preflight(
        context.store, {"provider": "test", "model": "test"},
        GuardianDecision(summary="original", orders=[]), meta, {}, {}, [{"reject_code": "quantity"}],
        check_cancelled=context.checkpoint, deadline=time.monotonic() + 270,
    )


def test_successful_format_repair_bills_each_call_once(context, monkeypatch) -> None:
    stream = Mock(side_effect=[_response('{"summary":', 10, 3), _response()])
    monkeypatch.setattr(agent, "chat_stream", stream)
    decision, usage = _complete(context)
    assert decision.summary == "hold"
    assert (usage["input_tokens"], usage["output_tokens"], usage["rounds"]) == (133, 48, 2)
    assert context.billing.call_args_list == [_bill(context, 10, 3), _bill(context, 123, 45)]


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, asyncio.CancelledError])
def test_cancelled_tool_bills_completed_round(context, monkeypatch, error_type) -> None:
    stop = error_type("tool cancelled")
    monkeypatch.setattr(agent, "chat_stream", Mock(return_value=_response(tools=True)))
    with pytest.raises(error_type) as caught:
        _complete(context, Mock(side_effect=stop))
    assert caught.value is stop
    assert (stop.usage["input_tokens"], stop.usage["output_tokens"]) == (123, 45)
    assert context.billing.call_args_list == [_bill(context, 123, 45)]
    assert stop.usage["context_documents"] == []


@pytest.mark.parametrize("error_type", [JobCancelled, TimeoutError])
def test_second_format_attempt_stop_adds_only_its_own_usage(context, monkeypatch, error_type) -> None:
    stop = error_type("second response cancelled")
    completed = 0

    def stream(*_args: object, **_kwargs: object) -> ChatResponse:
        nonlocal completed
        completed += 1
        return _response('{"summary":', 10, 3) if completed == 1 else _response()

    def checkpoint(*_args: object) -> None:
        if completed == 2:
            raise stop

    context.checkpoint = checkpoint
    monkeypatch.setattr(agent, "chat_stream", stream)
    with pytest.raises(error_type) as caught:
        _complete(context)
    assert caught.value is stop and completed == 2
    assert (stop.usage["input_tokens"], stop.usage["output_tokens"], stop.usage["rounds"]) == (133, 48, 2)
    assert context.billing.call_args_list == [_bill(context, 10, 3), _bill(context, 123, 45)]


def test_wrapped_llm_cancellation_is_not_repaired_or_rebilled(context, monkeypatch) -> None:
    stop = JobCancelled("wrapped cancellation")
    completed = 0

    def stream(*_args: object, **_kwargs: object) -> ChatResponse:
        nonlocal completed
        completed += 1
        if completed == 1:
            return _response(tools=True)
        raise LLMError("stream callback failed") from stop

    monkeypatch.setattr(agent, "chat_stream", stream)
    with pytest.raises(JobCancelled) as caught:
        _complete(context, lambda *_: {"text": "evidence"})
    assert caught.value is stop and completed == 2
    assert context.billing.call_args_list == [_bill(context, 123, 45)]
    assert (stop.usage["input_tokens"], stop.usage["output_tokens"]) == (123, 45)


def test_completed_but_invalid_attempts_are_not_billed_again(context, monkeypatch) -> None:
    monkeypatch.setattr(agent, "chat_stream", Mock(side_effect=[_response("invalid", 10, 3), _response("still invalid")]))
    with pytest.raises(ValueError) as caught:
        _complete(context)
    assert (caught.value.usage["input_tokens"], caught.value.usage["output_tokens"]) == (133, 48)
    assert context.billing.call_args_list == [_bill(context, 10, 3), _bill(context, 123, 45)]


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, asyncio.CancelledError])
def test_preflight_stop_bills_delta_and_reports_full_usage(context, monkeypatch, error_type) -> None:
    stop = error_type("preflight cancelled")
    returned = False

    def stream(*_args: object, **_kwargs: object) -> ChatResponse:
        nonlocal returned
        returned = True
        return _response()

    def checkpoint(*_args: object) -> None:
        if returned:
            raise stop

    context.checkpoint = checkpoint
    monkeypatch.setattr(agent, "chat_stream", stream)
    meta = _meta()
    with pytest.raises(error_type) as caught:
        _preflight(context, meta)
    assert caught.value is stop
    assert stop.usage is meta
    assert (meta["input_tokens"], meta["output_tokens"], meta["rounds"]) == (133, 48, 2)
    assert context.billing.call_args_list == [_bill(context, 123, 45)]


@pytest.mark.parametrize("text, summary, status", [(VALID, "hold", "corrected"), ("invalid", "original", "failed")])
def test_preflight_success_or_validation_failure_bills_only_repair(context, monkeypatch, text, summary, status) -> None:
    monkeypatch.setattr(agent, "chat_stream", Mock(return_value=_response(text)))
    meta = _meta()
    result = _preflight(context, meta)
    assert result.summary == summary and meta["preflight_repair"]["status"] == status
    assert (meta["input_tokens"], meta["output_tokens"]) == (133, 48)
    assert context.billing.call_args_list == [_bill(context, 123, 45)]


def test_cancel_between_format_attempts_does_not_bill_a_second_call(context, monkeypatch) -> None:
    stop = JobCancelled("cancel before repair starts")
    monkeypatch.setattr(agent, "chat_stream", Mock(return_value=_response("invalid", 10, 3)))

    def checkpoint(*_args: object) -> None:
        if context.billing.call_count:
            raise stop

    context.checkpoint = checkpoint
    with pytest.raises(JobCancelled) as caught:
        _complete(context)
    assert caught.value is stop
    assert (stop.usage["input_tokens"], stop.usage["output_tokens"]) == (10, 3)
    assert context.billing.call_args_list == [_bill(context, 10, 3)]


def test_terminal_event_cancellation_still_bills_the_response(context, monkeypatch) -> None:
    stop = JobCancelled("cancelled at terminal event")
    monkeypatch.setattr(agent, "chat_stream", Mock(return_value=_response()))

    def checkpoint(event=None) -> None:
        if event and event["type"] == "done":
            raise stop

    context.checkpoint = checkpoint
    with pytest.raises(JobCancelled) as caught:
        _complete(context)
    assert caught.value is stop
    assert (stop.usage["input_tokens"], stop.usage["output_tokens"]) == (123, 45)
    assert context.billing.call_args_list == [_bill(context, 123, 45)]


@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, asyncio.CancelledError])
def test_cancel_after_preflight_completion_does_not_rebill(context, monkeypatch, error_type) -> None:
    stop = error_type("cancel after accounting")
    monkeypatch.setattr(agent, "chat_stream", Mock(return_value=_response()))

    def checkpoint(*_args: object) -> None:
        if context.billing.call_count:
            raise stop

    context.checkpoint = checkpoint
    meta = _meta()
    with pytest.raises(error_type) as caught:
        _preflight(context, meta)
    assert caught.value is stop and stop.usage is meta
    assert (meta["input_tokens"], meta["output_tokens"]) == (133, 48)
    assert context.billing.call_args_list == [_bill(context, 123, 45)]


def test_concurrent_tenants_record_only_their_own_usage(monkeypatch) -> None:
    from src.ai.application import quota

    monkeypatch.setattr(quota, "_bump_identity_usage", lambda *_: None)
    barrier = Barrier(2)
    amounts = {"usage_alice": (123, 45), "usage_bob": (7, 3)}

    def stream(*_args: object, **_kwargs: object) -> ChatResponse:
        barrier.wait(timeout=5)
        return _response(VALID, *amounts[current_tenant()])

    def complete_for_tenant() -> tuple:
        context = SimpleNamespace(store=SimpleNamespace(db_path=ops_db()),
                                  archive=SimpleNamespace(receipts=[], documents=[]), checkpoint=lambda *_: None)
        _, usage = _complete(context)
        return context.store.db_path, usage

    monkeypatch.setattr(agent, "chat_stream", stream)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for tenant in amounts:
            with tenant_scope(tenant):
                futures.append(submit_with_tenant(pool, complete_for_tenant))
        results = [future.result(timeout=10) for future in futures]
    assert results[0][0] != results[1][0]
    for (path, usage), (tokens_in, tokens_out) in zip(results, amounts.values()):
        assert (usage["input_tokens"], usage["output_tokens"]) == (tokens_in, tokens_out)
        with sqlite3.connect(path) as db:
            row = db.execute("SELECT SUM(input_tokens), SUM(output_tokens), SUM(calls) FROM ai_usage_daily").fetchone()
        assert row == (tokens_in, tokens_out, 1)
