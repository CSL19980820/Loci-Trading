"""完整运行器回归：真实私有账本，模型与行情用确定性替身，禁止访问实盘。"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.ledger import StockAgentConflict, StockAgentStore
from src.ops import OpsStore
from src.ops.application.guardian_decision import GuardianDecision
from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs import stock_agent as runner
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "agent_time", lambda: NOW)
    monkeypatch.setattr(runner, "require_phase", lambda *_: None)
    monkeypatch.setattr(runner, "workshop_options", lambda *_: [])
    monkeypatch.setattr("src.ledger.infrastructure.stock_agent_store.agent_now", lambda value=None: value or NOW)
    monkeypatch.setattr("src.ledger.infrastructure.stock_agent_history.agent_now", lambda value=None: value or NOW)
    config = StockAgentConfig(name="运行器验证", kind="leader", provider="mock", model="mock", enabled=True).model_dump()
    path = str(tmp_path / "palace.db")
    with StockAgentStore(path) as ledger, OpsStore(None) as ops:
        profile = ledger.create(config, now=NOW)
        claimed = ledger.claim_run(profile["id"], "2026-09-16:intraday:10:00", "intraday", now=NOW)
        context = JobContext(ops_store=ops, palace_db=path, market_db=str(tmp_path / "market.db"))
        yield ledger, claimed, context, path


def test_complete_run_records_summary_without_fake_trades(runtime, monkeypatch):
    ledger, profile, context, path = runtime
    monkeypatch.setattr("src.ops.application.stock_agent_decide.decide_stock_agent",
                        lambda *_args, **_kwargs: (GuardianDecision(summary="证据不足，维持现金", orders=[]), {"model": "mock"}))
    result = runner.run_claimed(profile, "intraday", context, path)
    assert result["ledger_committed"]
    updated = ledger.get(profile["id"])
    assert updated["latest_summary"] == "证据不足，维持现金"
    assert updated["latest_status"] == "success"
    assert updated["total_trades"] == 0
    assert ledger.history(profile["id"])["total"] == 1


def test_actual_simulated_fill_matches_account_and_statement(runtime, monkeypatch):
    ledger, profile, context, path = runtime
    quote = {"code": "600001", "name": "验证股票", "price": 10,
             "trade_date": "2026-09-16", "trade_time": "10:00:00"}
    monkeypatch.setattr(runner, "snapshot", lambda *_args, **_kwargs: SimpleNamespace(quotes={"600001": quote}))
    decision = GuardianDecision.model_validate({"summary": "小仓位模拟验证", "orders": [{
        "code": "600001", "name": "验证股票", "action": "buy", "quantity": 100,
        "reason": "测试已核实的行情", "execution": {"kind": "market", "valid_until": (NOW+timedelta(minutes=3)).isoformat()}}]})
    monkeypatch.setattr("src.ops.application.stock_agent_decide.decide_stock_agent", lambda *_args, **_kwargs: (decision, {}))
    result = runner.run_claimed(profile, "intraday", context, path)
    assert result["fills"] == 1
    updated = ledger.get(profile["id"])
    assert updated["state"]["positions"][0]["quantity"] == 100
    assert updated["latest_actions"][0]["status"] == "filled"
    trade = ledger.history(profile["id"], kind="trades")["items"][0]
    assert trade["gross_cents"] == 100_000
    assert updated["state"]["cash_cents"] == 20_000_000-trade["gross_cents"]-trade["fees_cents"]


def test_funding_during_model_call_invalidates_old_result(runtime, monkeypatch):
    ledger, profile, context, path = runtime
    def decide(*_args, **_kwargs):
        with StockAgentStore(path) as other:
            other.deposit(profile["id"], 100_000, "inflight-funding", now=NOW)
        return GuardianDecision(summary="已过期的研究结果", orders=[]), {}
    monkeypatch.setattr("src.ops.application.stock_agent_decide.decide_stock_agent", decide)
    with pytest.raises(StockAgentConflict):
        runner.run_claimed(profile, "intraday", context, path)
    updated = ledger.get(profile["id"])
    assert updated["state"]["cash_cents"] == 20_100_000
    assert updated["latest_status"] == "cancelled"
    assert updated["total_trades"] == 0


def test_model_failure_is_visible_and_does_not_mutate_financial_account(runtime, monkeypatch):
    ledger, profile, context, path = runtime
    def fail(*_args, **_kwargs):
        raise RuntimeError("测试模型暂时不可用")
    monkeypatch.setattr("src.ops.application.stock_agent_decide.decide_stock_agent", fail)
    with pytest.raises(RuntimeError, match="模型暂时不可用"):
        runner.run_claimed(profile, "intraday", context, path)
    result = ledger.get(profile["id"])
    assert result["state"] == profile["state"]
    assert result["latest_status"] == "failed"
    assert "模型暂时不可用" in result["latest_summary"]
