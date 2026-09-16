from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore, new_guardian_account, check_guardian_account
from src.ops.application.guardian_decision import GuardianDecision, simulate

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def trade(state, action, quantity, price, *, day=14, code="603920"):
    now = NOW.replace(day=day)
    decision = GuardianDecision.model_validate({"summary": "自主发现", "orders": [
        {"code": code, "action": action, "quantity": quantity, "reason": "研究判断"}]})
    quote = {code: {"code": code, "name": "测试股票", "price": price,
                    "trade_date": now.date().isoformat(), "trade_time": "10:00:00", "source": "fixture"}}
    return simulate(state, decision, [], quote, now)


def test_complete_cash_cost_and_realized_reconciliation():
    state, buys, rejects = trade(new_guardian_account(), "buy", 1000, 10)
    assert not rejects and buys[0]["fees_cents"] == 260
    assert state["cash_cents"] == 18_999_740
    state, _, rejects = trade(state, "add", 500, 12)
    assert not rejects and state["positions"][0]["cost_cents"] == 1_600_416
    state, sales, rejects = trade(state, "reduce", 600, 13, day=15)
    assert not rejects
    assert sales[0]["fees_cents"] == 593
    assert sales[0]["allocated_cost_cents"] == 640_166
    assert sales[0]["realized_pnl_cents"] == 139_241
    assert state["cash_cents"] == 19_178_991
    assert state["positions"][0]["quantity"] == 900
    assert state["positions"][0]["cost_cents"] == 960_250
    state, sales, rejects = trade(state, "sell", 900, 9, day=15)
    assert not rejects and state["positions"] == []
    assert state["fees_cents"] == 1625
    assert state["cash_cents"] == 19_988_375
    assert state["realized_pnl_cents"] == state["total_pnl_cents"] == -11625
    check_guardian_account(state)
    # 清仓不禁止再次买入，同一只股票仍可管理。
    state, fills, rejects = trade(state, "buy", 100, 9, day=15)
    assert fills and not rejects and state["positions"][0]["quantity"] == 100


def test_t1_sells_only_previous_shares_after_adding_today():
    state, _, _ = trade(new_guardian_account(), "buy", 1000, 10)
    state, _, _ = trade(state, "add", 500, 10, day=15)
    snapshot = copy.deepcopy(state)
    _, fills, rejects = trade(state, "sell", 1500, 10, day=15)
    assert not fills and "T+1" in rejects[0]["reason"] and state == snapshot
    state, fills, rejects = trade(state, "sell", 1000, 10, day=15)
    assert fills and not rejects
    assert state["positions"][0]["quantity"] == 500
    assert state["positions"][0]["available_quantity"] == 0


def test_authorized_legacy_conversion_4500_shares_with_waived_minimum():
    state, fills, rejects = trade(new_guardian_account(), "buy", 4500, 8.70, code="002349")
    assert not rejects and fills[0]["gross_cents"] == 3_915_000
    assert fills[0]["commission_cents"] == 979 and fills[0]["transfer_cents"] == 39
    assert state["positions"][0]["quantity"] == 4500
    assert state["positions"][0]["available_quantity"] == 0
    assert state["positions"][0]["cost_cents"] == 3_916_018
    assert state["cash_cents"] == 16_083_982


@pytest.mark.parametrize("code,quantity,accepted", [
    ("603920", 101, False), ("603920", 100, True),
    ("688001", 199, False), ("688001", 201, True),
    ("920001", 101, True), ("920001", 99, False), ("510300", 100, False),
])
def test_board_share_rules(code, quantity, accepted):
    _, fills, rejects = trade(new_guardian_account(), "buy", quantity, 10, code=code)
    assert bool(fills) is accepted and bool(rejects) is not accepted


def test_invalid_money_or_oversell_cannot_change_cash():
    initial = new_guardian_account()
    for action, quantity in (("buy", 20000), ("sell", 100)):
        state, fills, rejects = trade(initial, action, quantity, 10)
        assert not fills and rejects and state["cash_cents"] == 20_000_000
    invalid = {**initial, "cash_cents": initial["cash_cents"] - 1}
    with pytest.raises(ValueError, match="对账不平"):
        check_guardian_account(invalid)


def test_stale_mark_keeps_last_value_and_labels_it():
    state, _, _ = trade(new_guardian_account(), "buy", 100, 10)
    held, fills, rejects = simulate(state, GuardianDecision(summary="hold", orders=[]), [], {}, NOW.replace(hour=11))
    assert held["equity_cents"] == state["equity_cents"]
    assert held["stale_codes"] == ["603920"]
    assert held["positions"][0]["valuation_stale"]
    assert not fills and not rejects


def test_trades_commit_once_with_account_and_survive_reopen(tmp_path):
    path = tmp_path / "palace.db"
    with GuardianStore(path) as ledger:
        assert ledger.claim("slot")
        state, fills, _ = trade(ledger.state(), "buy", 100, 10)
        ledger.finish("slot", {"status": "success", "fills": fills}, state)
        with pytest.raises(RuntimeError):
            ledger.finish("slot", {"status": "success", "fills": fills}, state)
    with GuardianStore(path) as ledger:
        assert ledger.state()["positions"][0]["quantity"] == 100
        assert ledger.trades()["total"] == 1
        assert ledger.trades()["items"][0]["cash_after_cents"] == 19_899_974
        assert ledger.trades(offset=1)["items"] == []


def test_trade_insert_failure_rolls_back_account_and_cycle(tmp_path):
    with GuardianStore(tmp_path / "palace.db") as ledger:
        ledger.claim("slot")
        state, fills, _ = trade(ledger.state(), "buy", 100, 10)
        ledger.conn.execute("CREATE TRIGGER fail_trade BEFORE INSERT ON guardian_trades BEGIN SELECT RAISE(ABORT,'test'); END")
        with pytest.raises(sqlite3.IntegrityError):
            ledger.finish("slot", {"status": "success", "fills": fills}, state)
        assert ledger.state() == new_guardian_account()
        assert ledger.recent()[0]["status"] == "running"
        assert ledger.trades()["total"] == 0


def test_legacy_layer_account_is_archived_not_fabricated_as_shares(tmp_path):
    path = tmp_path / "palace.db"
    old = {"positions": [{"code": "600001", "layers": 1.25}], "retired": ["600002"]}
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE guardian_portfolio(id INTEGER PRIMARY KEY,state_json TEXT)")
        conn.execute("INSERT INTO guardian_portfolio VALUES(1,?)", (json.dumps(old),))
    with GuardianStore(path) as ledger:
        assert ledger.state() == new_guardian_account()
        assert json.loads(ledger.conn.execute("SELECT state_json FROM guardian_legacy_accounts").fetchone()[0]) == old
    with GuardianStore(path) as ledger:
        assert ledger.state()["cash_cents"] == 20_000_000


def test_cash_and_shares_cannot_change_without_matching_trades(tmp_path):
    with GuardianStore(tmp_path / "palace.db") as ledger:
        ledger.claim("slot")
        state, _, _ = trade(ledger.state(), "buy", 100, 10)
        with pytest.raises(ValueError, match="流水"):
            ledger.finish("slot", {"status": "success", "fills": []}, state)
        assert ledger.state() == new_guardian_account()
        assert ledger.recent()[0]["status"] == "running"


def test_tenants_do_not_share_cash_trades_or_performance():
    from src.shared.tenancy import tenant_scope
    for tenant, code in (("account_one", "603920"), ("account_two", "002046")):
        with tenant_scope(tenant), GuardianStore() as ledger:
            ledger.claim("slot")
            state, fills, _ = trade(ledger.state(), "buy", 100, 10, code=code)
            ledger.finish("slot", {"status": "success", "fills": fills}, state)
    for tenant, code in (("account_one", "603920"), ("account_two", "002046")):
        with tenant_scope(tenant), GuardianStore() as ledger:
            assert ledger.trades()["total"] == 1
            assert ledger.trades()["items"][0]["code"] == code
            assert ledger.performance()[0]["bought_quantity"] == 100
            assert ledger.performance()[0]["code"] == code
            assert ledger.state()["cash_cents"] == 19_899_974
