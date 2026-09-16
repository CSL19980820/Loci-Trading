"""Causal signal and cash-account invariants for the standalone research."""
import numpy as np
import pandas as pd
import pytest

from scripts.high_payoff_research import account, features


@pytest.mark.parametrize("breakout,style", [(60, "strength"), (20, "quiet"), (0, "pullback")])
def test_signal_prefix_cannot_change_when_future_prices_change(breakout, style):
    dates = pd.bdate_range("2024-01-01", periods=260)
    close = np.linspace(10, 30, len(dates))
    frame = pd.DataFrame({"close": close, "high": close * 1.001,
                          "volume": 10_000_000.0, "factor": 1.0}, index=dates)
    frame.loc[dates[180], "volume"] = 30_000_000
    if style == "pullback":
        frame.loc[dates[180], "close"] *= .94
    before = features(frame, breakout, style)
    assert bool(before.loc[dates[180], "eligible"])
    frame.loc[dates[181]:, "close"] *= 100
    after = features(frame, breakout, style)
    pd.testing.assert_frame_equal(before.loc[:dates[180]], after.loc[:dates[180]])
    pd.testing.assert_frame_equal(before.loc[:dates[180]], features(frame.loc[:dates[180]], breakout, style))


def case(exit_reason="hold_expired", final_mark=10):
    days = ["2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05"]
    picks = {days[0]: [{"code": "600000", "name": "test", "score": 1.0}]}
    trade = {"code": "600000", "signal_date": days[0], "entry_date": days[1],
             "exit_date": days[3], "exit_reason": exit_reason, "gross_return_pct": 0.0}
    marks = {"600000": pd.Series([10., 10., 5., final_mark], index=days)}
    entry = {(days[1], "600000"): 10.0}
    factors = {(days[1], "600000"): 1.0}
    return picks, {(days[0], "600000"): trade}, marks, entry, factors, days


def test_daily_drawdown_detects_loss_that_recovers_before_exit():
    result = account(*case())
    assert result["metrics"]["max_drawdown_pct"] < -4.7
    assert result["metrics"]["return_pct"] < 0
    assert result["metrics"]["trades"] == 1
    assert result["trades"][0]["quantity"] % 100 == 0
    assert result["daily"][0]["open_positions"] == 0
    assert result["daily"][1]["open_positions"] == 1


def test_data_end_keeps_loss_on_equity_and_does_not_invent_a_sale():
    result = account(*case(exit_reason="data_end", final_mark=4))
    assert result["metrics"]["trades"] == 0
    assert result["metrics"]["open_positions"] == 1
    assert result["metrics"]["return_pct"] < -5.7
    assert result["metrics"]["unrealized_net_buy_cost_pnl"] < -11000


def test_higher_cost_reduces_same_trades_equity():
    normal = account(*case())
    stress = account(*case(), cost_multiplier=2)
    assert stress["trades"][0]["quantity"] == normal["trades"][0]["quantity"]
    assert stress["metrics"]["ending_equity"] < normal["metrics"]["ending_equity"]


def test_adjustment_factor_preserves_actual_entry_lots_and_value():
    picks, events, marks, raw, factors, dates = case()
    for key in factors:
        factors[key] = 2.0
    marks["600000"] *= 2
    adjusted = account(picks, events, marks, raw, factors, dates)
    unadjusted = account(*case())
    assert adjusted["metrics"]["ending_equity"] == pytest.approx(unadjusted["metrics"]["ending_equity"])
    assert adjusted["daily"][2]["equity"] == pytest.approx(unadjusted["daily"][2]["equity"])
