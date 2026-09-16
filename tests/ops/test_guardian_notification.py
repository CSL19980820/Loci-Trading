"""Compact pushes preserve financial facts, transaction truth and full internal research."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from src.ledger import GuardianStore
from src.ops.application.guardian_decision import render_digest, simulate
from src.ops.application.guardian_delivery_parts import notice_parts
from src.ops.application.guardian_notification import (
    load_notification_day, with_notification_facts, render_account_overview,
    render_failure_notice, notice_reason,
)
from src.ops.application.jobs import guardian
from src.ops.application.jobs.context import JobError
from src.ops.application.notify import _clip
from tests.ops import test_guardian as base
from tests.ops import test_guardian_execution_safety as safety

runtime = base.runtime
no_network = safety.no_network
NOW = base.NOW
SLOT = NOW.strftime("%Y-%m-%d %H:%M")


def fake_ledger(state=None, trades=None, report=None):
    return SimpleNamespace(state=lambda: state or deepcopy(base.EMPTY),
                           all_trades=lambda day: trades or [], report=lambda period, day: report)


def premarket(baseline=19_500_000):
    return {"status": "success", "result": {"facts": {
        "period": "premarket", "trade_date": "2026-09-11", "baseline_date": "2026-09-10",
        "baseline_equity_cents": baseline, "account": deepcopy(base.EMPTY),
    }}}


def fill(index, side="buy"):
    return {"name": f"操作股{index}", "code": f"{600001 + index:06d}", "action": side,
            "side": side, "quantity": 100, "price_cents": 1234, "gross_cents": 123400,
            "fees_cents": 32, "realized_pnl_cents": -678, "after_quantity": 100 if side == "buy" else 0,
            "occurred_at": NOW.isoformat()}


def decorated(state, fills=None):
    return with_notification_facts(state, load_notification_day(fake_ledger(report=premarket()), NOW),
                                   fills or [], slot=SLOT)


def test_six_trades_fit_one_notice_without_holdings_watchlist_or_research():
    state = {**deepcopy(base.EMPTY), "equity_cents": 19_695_438, "cash_cents": 13_792_538,
             "positions": [{"name": f"未操作持仓{i}", "code": f"60110{i}"} for i in range(4)],
             "watchlist": [{"name": "冗长观察", "code": "002999", "reason": "观察条件" * 2000}]}
    fills = [fill(i, "sell" if i < 4 else "buy") for i in range(6)]
    body = render_digest("完整研究结论" * 5000, fills, [], decorated(state, fills))
    assert "总资产 196,954.38 元" in body and "现金 137,925.38 元" in body and "持仓 4 只" in body
    assert "未操作持仓" not in body and "持仓成本" not in body and "601100" not in body
    assert "冗长观察" not in body and "002999" not in body and "完整研究结论" not in body
    assert "累计盈亏" not in body and "今日盈亏 +1,954.38 元" in body
    assert "本轮变动 · 成交 6 笔" in body and "剩余 0 股" in body
    assert "本笔盈亏 -6.78 元" in body
    parts = notice_parts("自主交易员 · 模拟账户", body)
    assert len(parts) == 1 and len(f"【{parts[0][0]}】\n{body}".encode()) <= 2000
    for item in fills:
        assert item["code"] in body


def test_large_change_set_splits_without_losing_last_trade():
    fills = [fill(i) for i in range(80)]
    body = render_digest("研究仍完整保存", fills, [], decorated(base.EMPTY, fills))
    parts = notice_parts("自主交易员 · 模拟账户", body)
    assert len(parts) > 1
    joined = "\n".join(chunk for _, chunk in parts)
    assert "截断" not in joined and fills[-1]["code"] in joined
    for title, chunk in parts:
        wire = f"【{title}】\n{chunk}"
        assert len(wire.encode()) <= 2000 and _clip(wire) == wire
    for item in fills:
        assert item["code"] in joined


@pytest.mark.parametrize("title,body", [("A", "x" * 2010), ("A" * 500, "x" * 4000)])
def test_ascii_notices_also_survive_legacy_character_clipping(title, body):
    parts = notice_parts(title, body)
    assert "".join(chunk for _, chunk in parts) == body
    assert all(_clip(f"【{t}】\n{b}") == f"【{t}】\n{b}" for t, b in parts)


def test_daily_pnl_is_not_cumulative_pnl():
    state = {**base.EMPTY, "equity_cents": 19_600_000, "total_pnl_cents": -400_000}
    marked = decorated(state)
    assert marked["notification_day"]["pnl_cents"] == 100_000
    assert "今日盈亏 +1,000.00 元" in render_account_overview(marked)
    assert "-4,000.00" not in render_account_overview(marked)


def test_new_account_daily_pnl_includes_actual_fee_and_counts_pending_fill_once():
    state, fills, _ = simulate(base.EMPTY, base.decision(), base.CANDIDATES, base.quotes(10), NOW)
    facts = load_notification_day(fake_ledger(), NOW)
    marked = with_notification_facts(state, facts, fills, slot=SLOT)
    assert marked["notification_day"]["pnl_cents"] == -26
    assert marked["notification_day"]["buy_count"] == 1
    assert marked["notification_day"]["fees_cents"] == 26
    assert facts["buy_count"] == 0 and "notification_day" not in state


def test_daily_counts_exclude_prior_day_and_include_all_current_trades():
    yesterday = {**fill(0), "occurred_at": "2026-09-10T10:00:00+08:00"}
    trades = [yesterday, fill(1), fill(2, "sell")]
    facts = load_notification_day(fake_ledger(trades=trades, report=premarket()), NOW)
    marked = with_notification_facts(base.EMPTY, facts, [fill(3)], slot=SLOT)
    assert marked["notification_day"]["buy_count"] == 2
    assert marked["notification_day"]["sell_count"] == 1
    assert marked["notification_day"]["fees_cents"] == 96


def test_missing_baseline_is_explicit_not_zero_or_cumulative_profit():
    old = {**fill(0), "occurred_at": "2026-09-10T10:00:00+08:00"}
    facts = load_notification_day(fake_ledger(trades=[old]), NOW)
    assert facts["baseline_equity_cents"] is None
    marked = with_notification_facts(base.EMPTY, facts, [], slot=SLOT)
    assert "pnl_cents" not in marked["notification_day"]
    assert "今日盈亏 · 暂不可用" in render_account_overview(marked)


def test_premarket_failure_cannot_supply_a_successful_baseline():
    report = premarket()
    report["status"] = "failed"
    old = {**fill(0), "occurred_at": "2026-09-10T10:00:00+08:00"}
    assert load_notification_day(fake_ledger(trades=[old], report=report), NOW)["baseline_equity_cents"] is None


def test_missing_report_can_reconstruct_verified_previous_close():
    yesterday = NOW.replace(day=10)
    state, fills, _ = simulate(base.EMPTY, base.decision(), base.CANDIDATES, base.quotes(10, yesterday), yesterday)
    market = SimpleNamespace(trading_days=lambda **kw: ["2026-09-10"], history=lambda *a, **kw: pd.DataFrame([{
        "trade_date": "2026-09-10", "close": 11.0, "source": "tdx",
        "fetched_at": "2026-09-10T15:10:00+08:00",
    }]))
    facts = load_notification_day(fake_ledger(state, fills), NOW, market_factory=lambda: nullcontext(market))
    assert facts["baseline_equity_cents"] == 20_009_974
    assert facts["baseline_source"] == "official_close" and facts["baseline_date"] == "2026-09-10"


def test_day_data_failure_does_not_prevent_notice():
    ledger = fake_ledger()
    ledger.all_trades = Mock(side_effect=ValueError("read failed"))
    facts = load_notification_day(ledger, NOW)
    assert not facts["trade_counts_available"] and facts["data_error"] == "read failed"
    assert "今日盈亏 · 暂不可用" in render_account_overview(with_notification_facts(base.EMPTY, facts, [], slot=SLOT))


def test_stale_valuation_reports_count_without_full_stock_codes():
    state = {**base.EMPTY, "stale_codes": ["600999", "002999"]}
    body = render_account_overview(decorated(state))
    assert "2 只股票使用最近有效报价" in body
    assert "600999" not in body and "002999" not in body


def test_failure_notice_contains_stage_reason_and_no_holdings():
    state = {**base.EMPTY, "positions": [{"code": "002999", "name": "未操作持仓"}]}
    body = render_failure_notice(decorated(state), TimeoutError("本轮研究超过270秒"), "research")
    assert "交易研判" in body and "研判超时" in body and "本轮无已落账成交" in body
    assert "总资产" in body and "持仓 1 只" in body
    assert "未操作持仓" not in body and "002999" not in body and "成本" not in body


def test_diagnostics_are_short_and_redact_transport_secrets():
    text = notice_reason("HTTP 401 https://example.invalid?key=secret-value api_key=credential Bearer bearer-value " + "错误" * 500)
    assert "secret-value" not in text and "credential" not in text and "bearer-value" not in text
    assert "HTTP 401" in text and len(text) < 130


def test_full_research_preserved_without_full_research_push(runtime):
    context, decide, notify = runtime
    proposed = base.decision().model_copy(update={"summary": "完整研究理由" * 3000})
    decide.return_value = (proposed, {"raw": "完整模型JSON" * 2000})
    result = guardian.execute_guardian({}, context)
    assert result["analysis"] == proposed.summary and result["usage"]["raw"].endswith("完整模型JSON")
    assert "完整研究理由" not in result["body"] and notify.call_count == 1
    assert result["notification_facts"]["buy_count"] == 1
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.recent()[0]["result"]["analysis"] == proposed.summary
        assert "notification_day" not in ledger.state()
        assert ledger.trades()["total"] == 1


def test_error_delivery_failure_cannot_mask_original_research_failure(runtime, monkeypatch):
    context, decide, _ = runtime
    decide.side_effect = TimeoutError("本轮研究超过270秒")
    monkeypatch.setattr(guardian, "deliver_pending", Mock(side_effect=RuntimeError("notice transport failed")))
    with pytest.raises(JobError, match="本轮研究超过270秒"):
        guardian.execute_guardian({}, context)
    with GuardianStore(context.palace_db) as ledger:
        saved = ledger.recent()[0]["result"]
        assert saved["error"] == "本轮研究超过270秒" and saved["delivery_error"] == "notice transport failed"
        assert saved["notification_facts"]["buy_count"] == 0 and saved["fills"] == []
        assert ledger.notice_backlog()["total"] == 1


def test_failed_valuation_does_not_break_error_notification(runtime, monkeypatch):
    context, _, notify = runtime
    monkeypatch.setattr(guardian, "mark_guardian_account", Mock(side_effect=ValueError("持仓缺少估值价格")))
    with pytest.raises(JobError, match="持仓缺少估值价格"):
        guardian.execute_guardian({}, context)
    body = notify.call_args.kwargs["body"]
    assert "总资产 暂不可用" in body and "持仓行情读取" in body
    assert "200,000.00 元" in body  # Cash is still independently known.
    with GuardianStore(context.palace_db) as ledger:
        assert ledger.recent()[0]["status"] == "failed"
        assert ledger.state() == base.EMPTY


def test_failure_and_risk_paths_reuse_verified_same_day_basis_without_market_reads():
    old = {**fill(0), "occurred_at": "2026-09-10T10:00:00+08:00"}
    ledger = fake_ledger(trades=[old])
    cached = load_notification_day(fake_ledger(report=premarket()), NOW)
    ledger.recent = Mock(return_value=[{"slot": "earlier", "result": {"notification_facts": cached}}])
    market = Mock(side_effect=AssertionError("No additional market read needed"))
    facts = load_notification_day(ledger, NOW, market_factory=market)
    assert facts["baseline_equity_cents"] == 19_500_000 and facts["baseline_from_slot"] == "earlier"
    assert facts["buy_count"] == 0
    market.assert_not_called()
    cached["trade_date"] = "2026-09-10"
    assert load_notification_day(ledger, NOW)["baseline_equity_cents"] is None
