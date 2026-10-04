"""工作台事实、曲线范围及完整动作摘要，使用隔离账本。"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import time

import pytest

from src.ledger import StockAgentStore
from src.ledger.domain.guardian_account import mark_guardian_account, new_guardian_account, settle_guardian_order
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.stock_agent_workbench import (
    apply_workbench_research, capture_observation_prices, enrich_workbench_state, entry_prices,
    quote_values, research_quotes, valuation_snapshot,
)
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime.fromisoformat("2026-09-30T14:40:00+08:00")


def quote(price=12, at=NOW):
    return {"price": price, "trade_date": at.date().isoformat(), "trade_time": at.time().isoformat(), "source": "test"}


@pytest.mark.parametrize("row", [quote(True), quote(float("nan")), quote(-1), quote(at=NOW+timedelta(seconds=1)),
                                   {"price": 12}, {**quote(), "error": "不可用"}])
def test_invalid_quote_never_becomes_current_price(row):
    assert quote_values(row, NOW) == (None, None)


def test_observation_and_review_dates_are_separate_and_old_price_is_unknown():
    state = {"positions": [], "watchlist": [
        {"code": "600000", "added_at": (NOW-timedelta(days=2)).isoformat(), "reason": "公式自动入池"},
        {"code": "000001", "added_at": (NOW-timedelta(seconds=20)).isoformat(), "reason": "首次入池"},
    ]}
    original = deepcopy(state)
    decision = StockAgentDecision(summary="等待", orders=[], assessments=[
        {"code": "600000", "stance": "wait", "summary": "缩量回踩后再核验承接", "expected_entry_price": 11.95},
        {"code": "000001", "stance": "unreviewed", "summary": "本轮未复核"},
    ])
    result = apply_workbench_research(state, decision, quotes={"600000": quote(), "000001": quote(10)}, now=NOW,
                                     coverage={"total": 2, "reviewed": 1, "complete": False})
    old, new = result["watchlist"]
    assert old["observed_at"] == original["watchlist"][0]["added_at"]
    assert old["observed_price_cents"] is None and old["current_price_cents"] == 1200
    assert old["reviewed_at"] == NOW.isoformat() and old["expected_entry_price_cents"] == 1195
    assert new["observed_price_cents"] == 1000 and new.get("reviewed_at") is None
    assert new["review_status"] == "unreviewed" and result["assessment_coverage"]["complete"] is False
    assert state == original


def test_current_quote_preserves_latest_fact_across_offsets_and_failed_refresh():
    state = {"positions": [], "watchlist": [{"code": "600000", "current_price_cents": 1230,
              "current_price_at": "2026-09-30T06:39:00+00:00"}]}
    row = enrich_workbench_state(state, now=NOW, quotes={"600000": quote(12, NOW-timedelta(minutes=2))})["watchlist"][0]
    assert row["current_price_cents"] == 1230
    row = enrich_workbench_state(state, now=NOW, quotes={"600000": quote(12.405)})["watchlist"][0]
    assert row["current_price_cents"] == 1241


def test_position_buy_price_replays_actual_gross_trades_with_partial_sales_and_new_cycle():
    trades = [
        {"code": "600000", "side": "buy", "quantity": 100, "price_cents": 1000},
        {"code": "600000", "side": "buy", "quantity": 100, "price_cents": 1200},
        {"code": "600000", "side": "sell", "quantity": 100, "price_cents": 1500},
    ]
    assert entry_prices(trades, {"600000": 100}) == {"600000": 1100}
    assert entry_prices(trades, {"600000": 200}) == {}
    trades += [{"code": "600000", "side": "sell", "quantity": 100, "price_cents": 1300},
               {"code": "600000", "side": "buy", "quantity": 100, "price_cents": 900}]
    assert entry_prices(trades) == {"600000": 900}


def test_position_projection_keeps_fees_in_pnl_and_original_account_unchanged():
    state = new_guardian_account()
    buy_at = NOW-timedelta(days=2)
    fill = settle_guardian_order(state, {"code": "600000", "action": "buy", "quantity": 100, "reason": "回踩后承接确认"},
                                 quote(10, buy_at), buy_at, {})
    state = mark_guardian_account(state, {"600000": quote(11)}, NOW)
    original = deepcopy(state)
    result = enrich_workbench_state(state, now=NOW, trades=[fill])
    row = result["positions"][0]
    assert row["entry_price_cents"] == 1000 and row["holding_days"] == 2
    assert row["entry_at"] == buy_at.isoformat() and row["entry_reason"] == "回踩后承接确认"
    assert row["pnl_pct"] < 10 and row["unrealized_pnl_cents"] < 10000
    assert state == original
    assert enrich_workbench_state(state, now=NOW)["positions"][0]["entry_price_cents"] is None


def test_live_profile_refresh_never_downgrades_position_quote(tmp_path, monkeypatch):
    from src.ops.application import stock_agent_service, stock_agent_workbench
    monkeypatch.setattr(stock_agent_service, "agent_time", lambda: NOW)
    monkeypatch.setattr(stock_agent_workbench, "research_quotes", lambda *_args, **_kwargs:
        {"600000": quote(12, NOW-timedelta(minutes=1))})
    with StockAgentStore(tmp_path/"palace.db") as ledger:
        profile = create(ledger)
        state = profile["state"]
        settle_guardian_order(state, {"code": "600000", "action": "buy", "quantity": 100, "reason": "确认承接"},
                              quote(12.30), NOW, {})
        state = mark_guardian_account(state, {}, NOW)
        ledger.conn.execute("UPDATE stock_agent_profiles SET state_json=? WHERE id=?", (json.dumps(state), profile["id"]))
        refreshed = stock_agent_service.public_profile(ledger.get(profile["id"]), ledger=ledger, refresh_quotes=True)
        assert refreshed["state"]["positions"][0]["mark_price_cents"] == 1230
        assert refreshed["state"]["equity_cents"] == state["equity_cents"]
        assert ledger.get(profile["id"])["state"] == state


def test_research_can_use_actual_close_quote_but_execution_still_rejects_stale_quote(monkeypatch):
    from src.market.application import live_cache
    from src.ops.application.guardian_quotes import quote_error
    after_close = NOW.replace(hour=20, minute=0)
    closing = {"code": "600000", **quote(12, NOW.replace(hour=15, minute=0))}
    requested = []
    def fetch(codes, **kwargs):
        requested.append((codes, kwargs))
        return SimpleNamespace(quotes={"600000": closing, "600001": {**closing, "code": "600002"}})
    monkeypatch.setattr(live_cache, "build_monitor_snapshot", fetch)
    result = research_quotes(["600000", "600001"], now=after_close, deadline=time.monotonic()+1)
    assert result["600000"]["price"] == 12 and result["600000"]["research_reference"]
    assert result["600000"]["quote_age_seconds"] == 18000
    assert quote_error("600000", result["600000"], after_close)
    assert result["600001"]["error"]
    assert requested == [(["600000", "600001"], {"include_minute": False, "force_refresh": False})]


def test_first_observation_price_survives_long_model_round_without_becoming_finish_price():
    state = {"positions": [], "watchlist": [{"code": "600000", "added_at": NOW.isoformat()}]}
    initial = capture_observation_prices(state, quotes={"600000": quote(12)}, now=NOW)
    finished = apply_workbench_research(initial, StockAgentDecision(summary="等待", orders=[]),
                                        quotes={"600000": quote(12.30, NOW+timedelta(minutes=4))}, now=NOW+timedelta(minutes=4))
    assert finished["watchlist"][0]["observed_price_cents"] == 1200
    assert finished["watchlist"][0]["current_price_cents"] == 1230


def test_failed_first_observation_is_not_backfilled_from_later_quote():
    state = {"positions": [], "watchlist": [{"code": "600000", "added_at": NOW.isoformat()}]}
    initial = capture_observation_prices(state, quotes={}, now=NOW)
    later = capture_observation_prices(initial, quotes={"600000": quote(12)}, now=NOW+timedelta(seconds=20))
    assert later["watchlist"][0].get("observed_price_cents") is None


def create(ledger, name="测试"):
    return ledger.create(StockAgentConfig(name=name, enabled=True, provider="test", model="test-model").model_dump(), now=NOW)


def test_curve_ranges_are_chronological_agent_scoped_and_funding_neutral(tmp_path):
    with StockAgentStore(tmp_path/"palace.db") as ledger:
        profile, other = create(ledger), create(ledger, "其他")
        ledger.conn.execute("DELETE FROM stock_agent_equity WHERE agent_id=?", (profile["id"],))
        for day in ["2025-09-30", "2025-10-01", "2026-03-31", "2026-04-01", "2026-08-30", "2026-08-31", "2026-09-23", "2026-09-24", "2026-09-30", "2026-10-01"]:
            ledger._snapshot(profile["id"], profile["state"], day+"T14:40:00+08:00")
        for span, first, count in [("week", "2026-09-24", 2), ("month", "2026-08-31", 4),
                                    ("half_year", "2026-03-31", 7), ("year", "2025-10-01", 8)]:
            data = ledger.equity(profile["id"], range=span, now=NOW)
            assert len(data["items"]) == count and data["items"][0]["day"] == first
            assert data["items"][-1]["day"] == "2026-09-30"
            assert all(row["agent_id"] == profile["id"] and row["pnl_cents"] == 0 for row in data["items"])
        limited = ledger.equity(profile["id"], range="year", limit=2, now=NOW)
        assert limited["truncated"] and limited["total"] == 8
        assert ledger.equity(other["id"], now=NOW)["total"] == 1
        with pytest.raises(ValueError, match="范围"):
            ledger.equity(profile["id"], range="bad", now=NOW)


def test_day_curve_only_uses_saved_actual_points_and_complete_actions(tmp_path):
    with StockAgentStore(tmp_path/"palace.db") as ledger:
        profile = create(ledger)
        actions = [{"code": f"6000{i:02}", "action": "watch", "status": "recorded"} for i in range(16)]
        actions.append({"code": "600000", "action": "buy", "status": "rejected"})
        for index in range(2):
            at = NOW+timedelta(minutes=index)
            claim = ledger.claim_run(profile["id"], f"2026-09-30:research:{index}", "research", now=at)
            ledger.finish_run(profile["id"], claim["run_id"], claim["state"],
                              {"summary": "空仓", "fills": [], "actions": actions,
                               "valuation_snapshot": valuation_snapshot(claim["state"], at)}, now=at)
        result = ledger.equity(profile["id"], range="day", now=NOW+timedelta(minutes=1))
        assert result["granularity"] == "intraday" and result["total"] == 2
        assert [row["at"] for row in result["items"]] == [NOW.isoformat(), (NOW+timedelta(minutes=1)).isoformat()]
        assert ledger.history(profile["id"])["items"][0]["actions"][-1]["action"] == "buy"
        assert len(ledger.get(profile["id"])["latest_actions"]) == 17


def test_trade_history_latest_first_with_stable_tie_and_agent_scope(tmp_path):
    with StockAgentStore(tmp_path/"palace.db") as ledger:
        profile, other = create(ledger), create(ledger, "其他")
        for agent, key, at in [(profile, "old", NOW-timedelta(days=1)), (profile, "same1", NOW),
                                (profile, "same2", NOW), (other, "other", NOW+timedelta(seconds=1))]:
            ledger.conn.execute("INSERT INTO stock_agent_trades(agent_id,run_id,seq,at,detail_json) VALUES(?,?,?,?,?)",
                                (agent["id"], key, 0, at.isoformat(), '{"code":"600000","side":"buy"}'))
        assert [row["run_id"] for row in ledger.history(profile["id"], kind="trades")["items"]] == ["same2", "same1", "old"]
