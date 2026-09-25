from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from src.ledger.domain.guardian_account import new_guardian_account, settle_guardian_order
from src.ops.application import guardian_agent, guardian_config
from src.ops.application.guardian_decision import GuardianDecision, simulate
from src.ops.application.guardian_review_prompts import review_system

NOW = datetime.fromisoformat("2026-09-23T10:00:00+08:00")


def order(code, action="buy", quantity=200):
    return {"code": code, "action": action, "quantity": quantity, "reason": "fixture"}


@pytest.mark.parametrize("code", ["688825", "689009", "920001", "830001", "430001", "510300", "09988", "302001"])
@pytest.mark.parametrize("action", ["buy", "add"])
def test_forbidden_buy_does_not_mutate_account(code, action):
    state = new_guardian_account()
    before = deepcopy(state)
    with pytest.raises(ValueError, match="仅允许买入沪深主板和创业板"):
        settle_guardian_order(state, order(code, action), {"price": 10}, NOW, {})
    assert state == before


@pytest.mark.parametrize("code", ["600000", "601001", "603001", "605001", "000001", "001001", "002001", "003001", "300001", "301001"])
def test_main_and_chinext_still_buyable(code):
    state = new_guardian_account()
    assert settle_guardian_order(state, order(code), {"price": 10}, NOW, {})["quantity"] == 200


def test_legacy_star_position_can_exit_but_cannot_add_and_t1_still_applies():
    state = new_guardian_account()
    # The independent agent path retains its own contract; also represents a legacy holding.
    settle_guardian_order(state, order("688825"), {"price": 10}, NOW, {}, guardian_policy=False)
    before = deepcopy(state)
    with pytest.raises(ValueError, match="T\\+1"):
        settle_guardian_order(state, order("688825", "sell"), {"price": 10}, NOW, {})
    assert state == before
    next_day = NOW.replace(day=24)
    assert settle_guardian_order(state, order("688825", "sell"), {"price": 10}, next_day, {})["side"] == "sell"
    assert state["positions"] == []


def test_preflight_explains_permission_without_requiring_a_quote():
    state = new_guardian_account()
    decision = GuardianDecision(summary="fixture", orders=[order("688825")])
    updated, fills, rejects = simulate(state, decision, [], {}, NOW)
    assert not fills and rejects[0]["reject_code"] == "board_not_allowed"
    assert updated["cash_cents"] == state["cash_cents"] and updated["positions"] == []


def test_opening_parser_rejects_forbidden_plan_and_all_phases_explain_scope(monkeypatch):
    import src.ai
    monkeypatch.setattr(src.ai, "resolve_config", lambda *a, **k: SimpleNamespace(model="fixture", protocol="openai"))
    monkeypatch.setattr(guardian_agent, "compose_research_tools", lambda *a, **k: ([], lambda *_: {}, {}))

    def complete(provider, store, **kwargs):
        bad = {"summary": "fixture", "orders": [order("688825")]}
        with pytest.raises(ValueError, match="不可买入意图"):
            kwargs["decision_parser"](json.dumps(bad))
        assert kwargs["payload"]["position_policy"]["buyable_boards"] == ["沪深主板", "创业板"]
        assert "仅主板和创业板可买入" in kwargs["system"]
        return GuardianDecision(summary="等待", orders=[]), {"tools": []}

    monkeypatch.setattr(guardian_agent, "complete_decision", complete)
    cfg = {**guardian_config.DEFAULTS, "model": "fixture", "common_prompt": "偏好中小盘"}
    guardian_agent.decide(None, cfg, {"as_of": "2026-09-23T09:25:00+08:00", "portfolio": {"positions": []}})
    for phase in ("premarket", "daily", "weekly"):
        prompt = review_system(cfg, phase, {})
        assert "禁止买入或加仓科创板" in prompt
        assert "不凭股价判断市值" in prompt
        assert "不设市值硬门槛" in prompt
