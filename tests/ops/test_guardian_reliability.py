"""Operational failures do not silently change the model, account or research capability."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.ledger import GuardianStore
from src.ops import OpsStore
from src.ops.application.guardian_config import get_job, save_config
from src.ops.application.jobs import guardian, guardian_delivery
from src.ops.application.jobs.context import JobContext, JobSkipped
from tests.ops import test_guardian as base

runtime = base.runtime


def test_partial_save_preserves_thinking_parallelism_and_disabled_status(tmp_path):
    with OpsStore(tmp_path / "ops.db") as store:
        save_config(store, {"enabled": True, "provider": "fixture", "model": "fixture",
                            "thinking": "high", "parallel_tools": 8})
        job = get_job(store)
        store.update_job(job["id"], enabled=False)
        result = save_config(store, {"notify": False})
        assert not result["enabled"] and not result["notify"]
        assert result["thinking"] == "high" and result["parallel_tools"] == 8
        assert result["provider"] == result["model"] == "fixture"


def test_independent_delivery_never_invokes_research_or_creates_trades(tmp_path, monkeypatch):
    sender = Mock(return_value={"success": True})
    monkeypatch.setattr(guardian_delivery, "dispatch_text", sender)
    monkeypatch.setattr(guardian_delivery, "notification_silence_reason", lambda: "")
    model = Mock(side_effect=AssertionError("Delivery must not rerun research"))
    monkeypatch.setattr(guardian, "decide", model)
    with OpsStore(tmp_path / "ops.db") as store, GuardianStore(tmp_path / "ledger.db") as ledger:
        save_config(store, {"enabled": True, "notify": True})
        job = store.get_job_by_name(guardian_delivery.MANAGED_GUARDIAN_DELIVERY)
        assert job["kind"] == "guardian_delivery" and job["enabled"]
        assert guardian_delivery.ensure_guardian_delivery_job(store) == {"created": []}
        before = ledger.state()
        assert ledger.claim("notice-fixture")
        ledger.finish("notice-fixture", {"status": "success"}, notice={"title": "fixture", "body": "saved notice"})
        context = JobContext(ops_store=store, palace_db=str(ledger.db_path))
        result = guardian_delivery.execute_guardian_delivery({}, context)
        assert result["delivered"] == 1 and result["backlog_after"]["total"] == 0
        assert result["research_calls"] == result["trade_count"] == 0
        assert ledger.state() == before and ledger.trades()["total"] == 0
        model.assert_not_called()
        sender.assert_called_once()
        with pytest.raises(JobSkipped):
            guardian_delivery.execute_guardian_delivery({}, context)


def test_data_source_display_failure_cannot_rollback_valid_fills(runtime, monkeypatch):
    context, _, _ = runtime
    monkeypatch.setattr(guardian, "data_source", Mock(side_effect=ValueError("catalog offline")))
    result = guardian.execute_guardian({}, context)
    assert result["ledger_committed"] and len(result["fills"]) == 1
    assert result["data_source"]["error"] == "catalog offline"
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1


def test_delivery_storage_failure_after_commit_preserves_execution_result(runtime, monkeypatch):
    context, _, _ = runtime
    monkeypatch.setattr(guardian, "deliver_pending", Mock(side_effect=OSError("outbox temporarily busy")))
    result = guardian.execute_guardian({}, context)
    assert result["ledger_committed"] and len(result["fills"]) == 1
    assert result["delivery_error"] == "outbox temporarily busy"
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.trades()["total"] == 1 and ledger.notice_backlog()["total"] == 1
