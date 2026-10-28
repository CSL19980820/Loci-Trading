"""猎隼按行情价模拟：盘口不参与，账户及价格约束继续生效。"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.ledger import StockAgentStore
from src.ledger.domain.guardian_account import new_guardian_account, settle_guardian_order
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.stock_agent_policy import simulate_stock_agent
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime.fromisoformat("2026-10-08T10:00:00+08:00")
CODE = "600152"


def quote(**changes):
    return {"code": CODE, "name": "维科技术", "source": "wudao", "price": 8.66, "prev_close": 8.50,
            "trade_date": "2026-10-08", "trade_time": "10:00:00", **changes}


def decision(action="buy", **changes):
    return StockAgentDecision(summary="拟交易", orders=[{
        "code": CODE, "action": action, "quantity": 100, "reason": "当前行情满足条件",
        "execution": {"kind": "limit", "max_price": 8.70, "valid_until": "2026-10-08T10:05:00+08:00"},
        **changes}])


def simulate(state=None, order=None, q=None, kind="falcon"):
    return simulate_stock_agent(state or new_guardian_account(), order or decision(),
        {CODE: q if q is not None else quote()}, NOW,
        StockAgentConfig(name="test", kind=kind).model_dump(), candidate_codes=[CODE])


@pytest.mark.parametrize("book", [None, {}, {"ask_price": 0, "ask_quantity": 0},
    {"code": CODE, "ask_price": 100, "ask_quantity": 1, "trade_date": "2020-01-01"}])
@pytest.mark.parametrize("action", ["buy", "sell", "stop_loss"])
def test_falcon_ignores_missing_empty_stale_or_insufficient_book(book, action):
    state = new_guardian_account()
    if action != "buy":
        settle_guardian_order(state, {"code": CODE, "action": "buy", "quantity": 100, "reason": "旧持仓"},
                             {"price": 8.5}, NOW.replace(day=7), {}, guardian_policy=False)
    _, fills, rejects = simulate(state, decision(action), quote(order_book=book))
    assert not rejects and len(fills) == 1
    assert fills[0]["price_cents"] == 866
    evidence = fills[0]["execution_evidence"]
    assert evidence["method"] == "paper_quote_proxy_v2"
    assert "order_book" not in evidence["quote"]


@pytest.mark.parametrize("changes", [{"trade_time": "09:00:00"}, {"price": 0},
                                    {"code": "600000"}, {"source": ""}])
def test_invalid_quote_still_rejected(changes):
    _, fills, rejects = simulate(q=quote(**changes))
    assert not fills and rejects


def test_price_expiry_cash_and_t_plus_one_still_enforced():
    for order, state in [
        (decision(execution={"kind": "limit", "max_price": 8, "valid_until": "2026-10-08T10:05:00+08:00"}), None),
        (decision(execution={"kind": "market", "valid_until": NOW.isoformat()}), None),
        (decision(quantity=100_000_000), None),
    ]:
        _, fills, rejects = simulate(state, order)
        assert not fills and rejects
    state, fills, rejects = simulate()
    assert fills and not rejects
    _, fills, rejects = simulate(state, decision("sell"))
    assert not fills and "T+1" in rejects[0]["reason"]


def test_other_agent_keeps_existing_book_requirement():
    _, fills, rejects = simulate(kind="custom")
    assert not fills and rejects[0]["reject_code"] == "liquidity_unconfirmed"


def test_falcon_runtime_commits_without_book(tmp_path, monkeypatch):
    import src.ledger.infrastructure.stock_agent_store as agent_store
    import src.ledger.infrastructure.stock_agent_history as agent_history
    import src.ops.application.jobs.stock_agent as runtime
    import src.ops.application.stock_agent_decide as model
    import src.ops.application.stock_agent_notify as notify
    import src.ops.application.falcon_candidates as candidates
    from src.ops.application.jobs.context import JobContext
    from src.ops.infrastructure.store import OpsStore

    monkeypatch.setattr(runtime, "agent_time", lambda: NOW)
    monkeypatch.setattr(agent_store, "agent_now", lambda value=None: value or NOW)
    monkeypatch.setattr(agent_history, "agent_now", lambda value=None: value or NOW)
    monkeypatch.setattr(runtime, "calendar_trading_day", lambda _: True)
    monkeypatch.setattr(notify, "notify_stock_agent", lambda *_: {"skipped": "test_no_send"})
    scope = {"as_of": NOW.isoformat(), "complete": True, "candidate_codes": [CODE], "research_codes": [CODE],
             "candidates": [{"code": CODE, "evidence_id": "candidate:test", "entry_eligible": True}], "warnings": []}
    monkeypatch.setattr(candidates, "load_falcon_candidates", lambda *_a, **_k: scope)
    monkeypatch.setattr(model, "decide_stock_agent", lambda *_a, **_k: (decision(), {}))
    snapshots = []

    def snapshot(codes, **kwargs):
        snapshots.append(kwargs)
        return SimpleNamespace(quotes={code: quote(code=code) for code in codes})

    monkeypatch.setattr(runtime, "snapshot", snapshot)
    palace = str(tmp_path / "palace.db")
    cfg = StockAgentConfig(name="猎隼", kind="falcon", provider="test", model="test", enabled=True).model_dump()
    with StockAgentStore(palace) as ledger:
        profile = ledger.create(cfg, now=NOW)
        claimed = ledger.claim_run(profile["id"], "2026-10-08:intraday:test", "intraday", now=NOW)
    with OpsStore(tmp_path / "ops.db") as ops:
        result = runtime.run_claimed(claimed, "intraday", JobContext(ops_store=ops, palace_db=palace), palace)
    assert result["ledger_committed"] and result["fills"] == 1
    assert snapshots and all(not call.get("require_order_book", False) for call in snapshots)
    with StockAgentStore(palace) as ledger:
        saved = ledger.run_detail(profile["id"], claimed["run_id"])
        assert saved["status"] == "success"
        assert saved["detail"]["fills"][0]["execution_evidence"]["method"] == "paper_quote_proxy_v2"
        assert ledger.get(profile["id"])["state"]["positions"][0]["quantity"] == 100
