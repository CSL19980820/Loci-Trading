from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.ledger import GuardianStore, new_guardian_account
from src.ops.application.guardian_config import get_config, save_config, JOB_NAME
from src.ops.application.guardian_context import observe
from src.ops.application.guardian_decision import GuardianDecision, simulate, render_digest
from src.ops.infrastructure.store import OpsStore

NOW = datetime(2026, 9, 14, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def decision(action, quantity=0, **fields):
    return GuardianDecision.model_validate({"summary": "主动寻找盈利机会", "orders": [
        {"code": "603920", "action": action, "quantity": quantity, "reason": "交易判断", **fields}]})


def quote(price, now=NOW):
    return {"603920": {"price": price, "trade_date": now.date().isoformat(), "trade_time": "10:00:00"}}


def test_watch_outside_strategy_pool_persists_without_trade_and_can_be_removed(tmp_path):
    with GuardianStore(tmp_path / "palace.db") as store:
        initial = store.state()
        state, fills, rejects = simulate(initial, decision("watch", name="世运电路", entry_condition="放量突破", exit_condition="资金撤离"), [], {}, NOW)
        assert not fills and not rejects
        assert state["cash_cents"] == initial["cash_cents"] and not state["positions"]
        store.claim("watch")
        store.finish("watch", {"status": "success", "fills": fills}, state)
    with GuardianStore(tmp_path / "palace.db") as store:
        state = store.state()
        assert store.trades()["total"] == 0
        rows = observe(SimpleNamespace(candidates_payload=lambda _: []), [], state, [])
        assert rows[0]["code"] == "603920" and rows[0]["watch"]["entry_condition"] == "放量突破"
        assert "自主观察" not in render_digest("主动观察", [], [], state)
        state, _, _ = simulate(state, decision("watch", entry_condition="回踩确认"), [], {}, NOW)
        assert len(state["watchlist"]) == 1 and state["watchlist"][0]["entry_condition"] == "回踩确认"
        state, fills, rejects = simulate(state, decision("unwatch"), [], {}, NOW)
        assert not state["watchlist"] and not fills and not rejects


@pytest.mark.parametrize("action", ["take_profit", "stop_loss"])
def test_profit_and_loss_exits_are_real_sell_actions_and_obey_t1(action):
    state, _, _ = simulate(new_guardian_account(), decision("buy", 1000), [], quote(10), NOW)
    _, fills, rejects = simulate(state, decision(action, 500), [], quote(11), NOW)
    assert not fills and "T+1" in rejects[0]["reason"]
    tomorrow = NOW.replace(day=15)
    state, fills, rejects = simulate(state, decision(action, 500), [], quote(11, tomorrow), tomorrow)
    assert not rejects and fills[0]["side"] == "sell" and fills[0]["action"] == action
    assert state["positions"][0]["quantity"] == 500
    assert fills[0]["realized_pnl_cents"] == 49451  # 5500.00 - 4.19 - 5001.30
    assert ("止盈" if action == "take_profit" else "止损") in render_digest("退出", fills, [], state)


def test_hold_preserves_profit_and_loss_plans_without_changing_shares():
    state, _, _ = simulate(new_guardian_account(), decision("buy", 1000), [], quote(10), NOW)
    next_state, fills, rejects = simulate(state, decision("hold", take_profit_plan="主线退潮时兑现", stop_loss_plan="结构破坏时退出"), [], quote(10), NOW)
    assert not fills and not rejects
    assert next_state["positions"][0]["quantity"] == 1000
    assert next_state["positions"][0]["take_profit_plan"] == "主线退潮时兑现"
    assert next_state["positions"][0]["stop_loss_plan"] == "结构破坏时退出"
    _, _, rejects = simulate(new_guardian_account(), decision("hold"), [], {}, NOW)
    assert "未持仓" in rejects[0]["reason"]


def test_rename_reuses_existing_job_and_does_not_reset_config(tmp_path):
    with OpsStore(tmp_path / "ops.db") as store:
        job_id = store.create_job(name="智能守护", kind="guardian", config={"provider": "test", "model": "qwen3.8-flash", "prompt": "我的偏好"}, enabled=True)
        cfg = get_config(store)
        assert cfg["enabled"] and cfg["prompt"] == "我的偏好"
        save_config(store, cfg)
        assert store.get_job_by_name(JOB_NAME)["id"] == job_id
        assert store.get_job_by_name("智能守护") is None
        assert get_config(store) == cfg


@pytest.mark.parametrize("action", ["hold", "watch", "unwatch"])
def test_non_trade_actions_cannot_hide_an_order_quantity(action):
    with pytest.raises(ValueError, match="quantity"):
        decision(action, 100)
