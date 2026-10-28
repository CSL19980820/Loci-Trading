"""行情价模拟保留涨停买入门禁，静态昨收参考不要求实时盘口。"""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from src.ledger.domain.guardian_account import new_guardian_account, settle_guardian_order
from src.ops.application.guardian_contract import GUARDIAN_EXECUTION_RULES
from src.ops.application.guardian_decision import GuardianDecision, simulate
from src.ops.application.guardian_quotes import executable_quote

NOW = datetime.fromisoformat("2026-10-13T13:05:00+08:00")
CODE = "000823"


def quote(code=CODE, **changes):
    return {"code": code, "name": "超声电子", "price": 22.32, "prev_close": 20.29,
            "source": "wudao", "trade_date": "2026-10-13", "trade_time": "13:05:00", **changes}


@pytest.mark.parametrize("action", ["buy", "add"])
@pytest.mark.parametrize("price", [22.32, 22.33, 22.319])
def test_ultrasonic_limit_up_never_becomes_a_paper_fill(action, price):
    with pytest.raises(ValueError, match="已达涨停价22.32"):
        executable_quote(CODE, action, 1200, quote(price=price), NOW, paper=True)


@pytest.mark.parametrize(("code", "name", "previous", "upper"), [
    ("000823", "超声电子", 20.29, 22.32),
    ("600000", "ST浦发", 10, 11),
    ("300001", "特锐德", 10, 12),
    ("300001", "ST特锐德", 10, 12),
    ("688001", "ST华兴", 10, 12),
    ("920001", "ST北证", 10, 13),
    ("600000", "普通主板", 10.15, 11.17),  # 11.165须逢五进一，不能银行家舍入。
])
def test_board_and_current_st_limits_use_half_up_cents(code, name, previous, upper):
    row = quote(code, name=name, prev_close=previous, price=upper)
    with pytest.raises(ValueError, match="已达涨停价"):
        executable_quote(code, "buy", 200, row, NOW, paper=True)
    below = executable_quote(code, "buy", 200, {**row, "price": upper - .01}, NOW, paper=True)
    check = below["execution_evidence"]["limit_up_check"]
    assert check["limit_up"] == upper and check["prev_close"] == previous
    assert check["reference"] == "prev_close_board_rule"
    assert below["execution_evidence"]["method"] == "paper_quote_proxy_v2"


def test_historical_main_st_limit_changes_on_2026_july_six():
    previous_rule = NOW.replace(month=7, day=3)
    row = quote("600000", name="ST浦发", prev_close=10, price=10.5, trade_date="2026-07-03")
    with pytest.raises(ValueError, match="涨停价10.50"):
        executable_quote("600000", "buy", 100, row, previous_rule, paper=True)
    current_rule = previous_rule.replace(day=6)
    filled = executable_quote("600000", "buy", 100, {**row, "trade_date": "2026-07-06"}, current_rule, paper=True)
    assert filled["execution_evidence"]["limit_up_check"]["limit_up"] == 11


@pytest.mark.parametrize("previous", [None, 0, -1, True, float("nan"), float("inf")])
def test_missing_or_invalid_reference_rejects_buy(previous):
    with pytest.raises(ValueError, match="缺少可靠当日涨停价或昨收参考"):
        executable_quote(CODE, "buy", 1200, quote(prev_close=previous), NOW, paper=True)


def test_known_current_limit_reference_can_replace_missing_previous_close():
    row = quote(prev_close=None, limit_up=22.32)
    with pytest.raises(ValueError, match="已达涨停价"):
        executable_quote(CODE, "buy", 1200, row, NOW, paper=True)
    filled = executable_quote(CODE, "buy", 1200, {**row, "price": 22.31}, NOW, paper=True)
    assert filled["execution_evidence"]["limit_up_check"]["reference"] == "quote_limit_up"


@pytest.mark.parametrize("upper", [22.33, 20, 22.321])
def test_conflicting_or_invalid_known_limit_fails_closed(upper):
    with pytest.raises(ValueError, match="涨停参考价"):
        executable_quote(CODE, "buy", 1200, quote(price=22, limit_up=upper), NOW, paper=True)


def test_supplemental_same_day_previous_close_does_not_replace_primary_price_evidence():
    reference = {"code": CODE, "name": "超声电子", "prev_close": 20.29,
                 "source": "sina", "trade_date": "2026-10-13", "trade_time": "09:30:00"}
    row = quote(prev_close=None, limit_reference=reference)
    before = deepcopy(row)
    with pytest.raises(ValueError, match="已达涨停价"):
        executable_quote(CODE, "buy", 1200, row, NOW, paper=True)
    filled = executable_quote(CODE, "buy", 1200, {**row, "price": 22.31}, NOW, paper=True)
    assert row == before
    assert filled["source"] == "wudao" and filled["trade_time"] == "13:05:00"
    check = filled["execution_evidence"]["limit_up_check"]
    assert check["source"] == "sina" and check["trade_time"] == "09:30:00"


@pytest.mark.parametrize("changes", [{"code": "000001"}, {"source": ""}, {"trade_date": "2026-10-12"}])
def test_wrong_stock_source_or_day_of_supplement_does_not_authorize_buy(changes):
    reference = {"code": CODE, "name": "超声电子", "prev_close": 20.29,
                 "source": "sina", "trade_date": "2026-10-13", **changes}
    with pytest.raises(ValueError, match="缺少可靠"):
        executable_quote(CODE, "buy", 1200, quote(prev_close=None, limit_reference=reference), NOW, paper=True)


def test_stale_or_wrong_stock_book_is_not_a_limit_reference():
    for changes in ({"trade_date": "2026-10-12"}, {"code": "000001"}, {"source": "other"}):
        book = {**quote(limit_up=22.32), **changes}
        with pytest.raises(ValueError, match="缺少可靠"):
            executable_quote(CODE, "buy", 1200, quote(prev_close=None, order_book=book), NOW, paper=True)


def test_limit_gate_does_not_block_exit_or_other_valid_orders():
    state = new_guardian_account()
    settle_guardian_order(state, {"code": "600000", "action": "buy", "quantity": 100,
                                 "reason": "昨日隔离持仓"}, {"price": 10}, NOW - timedelta(days=1), {})
    original = deepcopy(state)
    execution = {"kind": "market", "valid_until": (NOW + timedelta(minutes=5)).isoformat()}
    decision = GuardianDecision(summary="拟退出旧持仓，涨停只观察", orders=[
        {"code": CODE, "action": "buy", "quantity": 1200, "reason": "原错误意图", "execution": execution},
        {"code": "600000", "action": "sell", "quantity": 100, "reason": "退出", "execution": execution},
        {"code": "300001", "action": "buy", "quantity": 100, "reason": "未涨停", "execution": execution},
    ])
    quotes = {CODE: quote(), "600000": quote("600000", price=11, prev_close=None),
              "300001": quote("300001", price=11, prev_close=10)}
    updated, fills, rejects = simulate(state, decision, [], quotes, NOW, require_execution_terms=True)
    assert state == original
    assert [(row["code"], row["side"]) for row in fills] == [("600000", "sell"), ("300001", "buy")]
    assert [row["code"] for row in rejects] == [CODE]
    assert rejects[0]["reject_code"] == "liquidity_unconfirmed" and "涨停" in rejects[0]["reason"]
    assert [position["code"] for position in updated["positions"]] == ["300001"]


def test_live_guardian_rules_no_longer_allow_sealed_limit_price_proxy_fills():
    assert "达到涨停价时禁止模拟成交" in GUARDIAN_EXECUTION_RULES
    assert "不因缺盘口、空盘口或挂单量不足阻止模拟成交" in GUARDIAN_EXECUTION_RULES
    assert "不因缺盘口、空盘口、挂单量不足或盘口涨跌停信息阻止模拟成交" not in GUARDIAN_EXECUTION_RULES
