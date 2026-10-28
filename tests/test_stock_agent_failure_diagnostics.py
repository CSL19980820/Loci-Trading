from datetime import datetime

import pytest

from src.ledger import StockAgentStore
from src.ledger.infrastructure.stock_agent_history import StockAgentConflict
from src.ops.application.jobs import stock_agent as runtime
from src.ops.application.jobs.context import JobContext
from src.ops.domain.stock_agent import StockAgentConfig
from src.ops.infrastructure.store import OpsStore


@pytest.mark.parametrize("error_type,status", [(ValueError, "failed"), (StockAgentConflict, "cancelled")])
def test_failed_model_diagnostics_survive_without_raw_evidence(tmp_path, monkeypatch, error_type, status):
    import src.ledger.infrastructure.stock_agent_store as agent_store
    import src.ledger.infrastructure.stock_agent_history as agent_history
    import src.ops.application.stock_agent_decide as model

    now = datetime.fromisoformat("2026-10-08T08:50:00+08:00")
    monkeypatch.setattr(runtime, "agent_time", lambda: now)
    monkeypatch.setattr(agent_store, "agent_now", lambda value=None: value or now)
    monkeypatch.setattr(agent_history, "agent_now", lambda value=None: value or now)
    monkeypatch.setattr(runtime, "calendar_trading_day", lambda _: True)
    error = error_type("模型首响应超时")
    error.usage = {"model": "test-model", "input_tokens": 12, "output_tokens": 0,
        "elapsed_ms": 270000, "rounds": 1, "tool_calls": 0,
        "timeline": [{"event": "model_retry", "attempt": i, "reason": "interrupted_generation"}
                     for i in range(210)],
        "attempts": [{"finish_reason": "", "stopped_reason": "llm_error", "error": "timeout",
                      "raw": "private output"}],
        "tools": [{"text": "large tool evidence" * 100000}],
        "context_documents": {"ref": {"text": "large source"}}, "_repair": {"messages": [object()]}}

    def failed(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(model, "decide_stock_agent", failed)
    palace = str(tmp_path / "palace.db")
    with StockAgentStore(palace) as ledger:
        profile = ledger.create(StockAgentConfig(name="test", provider="test", model="test-model",
                                               enabled=True).model_dump(), now=now)
        claimed = ledger.claim_run(profile["id"], "2026-10-08:premarket", "premarket", now=now)
    with OpsStore(tmp_path / "ops.db") as ops:
        with pytest.raises(error_type, match="首响应超时"):
            runtime.run_claimed(claimed, "premarket", JobContext(ops_store=ops, palace_db=palace), palace)
    with StockAgentStore(palace) as ledger:
        saved = ledger.run_detail(profile["id"], claimed["run_id"])
        assert saved["status"] == status
        assert saved["detail"]["error_type"] == error_type.__name__
        usage = saved["detail"]["usage"]
        assert usage["input_tokens"] == 12 and usage["elapsed_ms"] == 270000
        assert len(usage["timeline"]) == 200 and usage["timeline"][0]["attempt"] == 10
        assert usage["attempts"][0] == {"finish_reason": "", "stopped_reason": "llm_error", "error": "timeout"}
        assert not {"tools", "context_documents", "_repair"} & usage.keys()
        current = ledger.get(profile["id"])
        assert current["state"] == profile["state"] and current["active_run"] is None
        assert ledger.history(profile["id"], kind="trades")["total"] == 0
        ledger.fail_run(profile["id"], claimed["run_id"], "late duplicate failure")
        assert ledger.run_detail(profile["id"], claimed["run_id"])["detail"] == saved["detail"]
