"""无歧义的常见模型写法不再让整份决策作废；有歧义的仍拒绝。"""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.ops.application.guardian_contract import ExecutionTerms
from src.ops.application.guardian_decision import GuardianOrder, normalize_stock_code
from src.ops.application.guardian_quotes import quote_error
from src.ops.application.stock_agent_decision import StockAgentDecision

NOW = datetime.fromisoformat("2026-09-23T10:02:30+08:00")


def test_naive_expiry_is_beijing_time_and_aware_expiry_unchanged():
    naive = ExecutionTerms(kind="market", valid_until="2026-09-23T10:05:00")
    assert naive.valid_until == "2026-09-23T10:05:00+08:00"
    assert ExecutionTerms(kind="market", valid_until="2026-09-23T02:05:00+00:00").valid_until == "2026-09-23T02:05:00+00:00"
    assert ExecutionTerms(kind="market", valid_until="2026-09-23T02:05:00Z").valid_until == "2026-09-23T02:05:00+00:00"


@pytest.mark.parametrize(("raw", "code"), [
    ("SH600519", "600519"), ("sh.600000", "600000"), ("600519.SH", "600519"), ("600519.SS", "600519"),
    ("600519.XSHG", "600519"), ("sz000001", "000001"), ("000001.XSHE", "000001"), ("300750.SZ", "300750"),
    ("430047.BJ", "430047"), (" 600519 ", "600519"),
])
def test_exchange_qualified_codes_normalize(raw, code):
    assert GuardianOrder(code=raw, action="watch", reason="x").code == code


@pytest.mark.parametrize("raw", ["000001.SH", "SH000001", "600519.SZ", "HK00700", "60051"])
def test_ambiguous_or_foreign_codes_still_rejected(raw):
    with pytest.raises(ValidationError):
        GuardianOrder(code=raw, action="watch", reason="x")
    assert normalize_stock_code(raw) in {raw, raw.strip()}


def test_keep_list_and_replacement_codes_normalized():
    decision = StockAgentDecision.model_validate({"summary": "s", "orders": [
        {"code": "600000.SH", "action": "hold", "reason": "x", "replacement_for": "SZ000002"}],
        "close_keep_codes": ["600000.SH", "sz000002"]})
    assert decision.close_keep_codes == ["600000", "000002"]
    assert decision.orders[0].replacement_for == "000002"


def stamped(offset_seconds):
    moment = NOW + timedelta(seconds=offset_seconds)
    return {"code": "600000", "price": 10.0, "source": "wudao",
            "trade_date": moment.date().isoformat(), "trade_time": moment.strftime("%H:%M:%S")}


@pytest.mark.parametrize(("offset", "valid"), [(0, True), (-179, True), (-181, False), (30, True), (60, True), (61, False)])
def test_quote_clock_skew_tolerance(offset, valid):
    assert (quote_error("600000", stamped(offset), NOW) is None) is valid
