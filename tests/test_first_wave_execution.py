"""Synthetic execution evidence only; no network, database, or live prices."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from scripts.first_wave_execution import simulate_opportunity


def daily_bars(periods=20, start="2024-01-02"):
    days = pd.bdate_range(start, periods=periods).strftime("%Y-%m-%d")
    return pd.DataFrame(
        {
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "volume": 10000.0,
            "factor": 1.0,
        },
        index=days,
    )


def minute_bars(day, price=10.0):
    times = pd.date_range(f"{day} 09:30", f"{day} 11:30", freq="min").union(
        pd.date_range(f"{day} 13:00", f"{day} 15:00", freq="min")
    )
    return pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": 100.0},
        index=times,
    )


def minute_data(bars, through=None):
    return {day: minute_bars(day) for day in bars.index[4:through]}


def simulate(bars, **kwargs):
    return simulate_opportunity(bars, bars.index[4], code="600001", **kwargs)


def surge_minutes(bars):
    minutes = minute_data(bars)
    d3 = bars.index[5]
    frame = minute_bars(d3, 10.1)
    frame.loc[f"{d3} 09:35", ["high", "close"]] = [10.6, 10.5]
    minutes[d3] = frame
    return minutes


def test_daily_stages_and_horizon_count_from_first_fill():
    bars = daily_bars()
    result = simulate(bars, hold_days=3, exit_rule="horizon")
    assert result["status"] == "closed"
    assert [leg["entry_date"] for leg in result["legs"]] == list(bars.index[5:7])
    assert [leg["weight"] for leg in result["legs"]] == [0.5, 0.5]
    assert result["exit_date"] == bars.index[8]
    assert result["exit_reason"] == "horizon"
    assert result["gross_return_pct"] == 0
    assert result["net_return_pct"] < 0


def test_daily_requires_d2_close_above_ma5():
    bars = daily_bars()
    bars.loc[bars.index[4], "close"] = 9.9
    result = simulate(bars)
    assert result["status"] == "skipped"
    assert result["reason"] == "d2_below_ma5"
    assert result["legs"] == []


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
def test_ma5_requires_four_prior_observations(mode):
    bars = daily_bars(6)
    signal = bars.index[2]
    result = simulate_opportunity(
        bars, signal, code="600001", mode=mode, minutes={signal: minute_bars(signal)}
    )
    assert result["status"] == "unverifiable"
    assert result["reason"] == "insufficient_ma5_history"


def test_d3_gap_with_small_body_does_not_chase():
    bars = daily_bars()
    bars.loc[bars.index[5], ["open", "high", "low", "close"]] = [
        10.4,
        10.45,
        10.35,
        10.45,
    ]
    result = simulate(bars, exit_rule="horizon", hold_days=3)
    assert result["status"] == "closed"
    assert len(result["legs"]) == 1
    assert result["invested_notional"] == 50000
    assert result["uninvested_cash"] == 50000
    assert result["invested_gross_return_pct"] == pytest.approx(
        2 * result["gross_return_pct"]
    )
    assert result["invested_net_return_pct"] == pytest.approx(
        2 * result["net_return_pct"]
    )


def test_daily_surge_prefers_later_close_pullback_then_next_open():
    bars = daily_bars()
    d3, d4, d5 = bars.index[5:8]
    bars.loc[d3, ["open", "high", "low", "close"]] = [10.2, 10.6, 10.0, 10.2]
    bars.loc[d4, ["open", "high", "low", "close"]] = [10.3, 10.4, 9.8, 10.1]
    bars.loc[d5, ["open", "high", "low", "close"]] = [10.35, 10.4, 9.9, 10.2]
    result = simulate(bars, hold_days=4, exit_rule="horizon")
    assert result["status"] == "closed"
    assert result["legs"][1]["entry_date"] == d5
    assert result["legs"][1]["entry_price"] == 10.35
    assert result["legs"][1]["entry_reason"] == "ma5_pullback"


@pytest.mark.parametrize("blocked_price", [11.0, float("nan")])
def test_first_buy_upper_limit_or_suspension_is_skipped(blocked_price):
    bars = daily_bars()
    bars.loc[bars.index[5], ["open", "high", "low", "close"]] = blocked_price
    result = simulate(bars)
    assert result["status"] == "skipped"
    assert result["legs"] == []
    assert result["reason"] == (
        "first_buy_upper_limit" if pd.notna(blocked_price) else "first_buy_suspended"
    )


def test_suspension_and_lower_limit_queue_sales_and_count_calendar_days():
    bars = daily_bars()
    bars.loc[bars.index[7], ["open", "high", "low", "close"]] = float("nan")
    bars.loc[bars.index[8], ["open", "high", "low", "close"]] = 9.0
    bars.loc[bars.index[9], ["open", "high", "low", "close"]] = 9.2
    result = simulate(bars, hold_days=2, exit_rule="horizon")
    assert result["status"] == "closed"
    assert result["exit_date"] == bars.index[9]
    assert len(result["legs"]) == 2
    assert "sell_queued_suspended" in result["evidence_flags"]
    assert "sell_queued_lower_limit" in result["evidence_flags"]


def test_close_break_exits_next_open_and_cancels_add():
    bars = daily_bars()
    bars.loc[bars.index[5], ["open", "high", "low", "close"]] = [10.0, 10.1, 9.7, 9.8]
    bars.loc[bars.index[6], "open"] = 9.7
    result = simulate(bars)
    assert result["status"] == "closed"
    assert len(result["legs"]) == 1
    assert result["exit_date"] == bars.index[6]
    assert result["legs"][0]["exit_price"] == 9.7
    assert result["exit_reason"] == "ma5_break"


def test_adjustment_factor_pays_economic_return_without_false_limit_down():
    bars = daily_bars()
    bars.loc[bars.index[6] :, ["open", "high", "low", "close"]] /= 2
    bars.loc[bars.index[6] :, "factor"] = 2.0
    result = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    leg = result["legs"][0]
    assert result["status"] == "closed"
    assert leg["entry_price"] == 10
    assert leg["exit_price"] == 5
    assert leg["exit_factor"] == 2
    assert leg["exit_quantity"] == 2 * leg["quantity"]
    assert result["gross_return_pct"] == 0
    assert "sell_queued_lower_limit" not in result["evidence_flags"]


def test_ex_rights_reference_is_used_for_buy_and_d3_gap_filter():
    bars = daily_bars()
    bars.loc[bars.index[5] :, ["open", "high", "low", "close"]] /= 2
    bars.loc[bars.index[5] :, "factor"] = 2.0
    result = simulate(bars, hold_days=2, exit_rule="horizon")
    assert result["status"] == "closed"
    assert len(result["legs"]) == 2
    assert result["gross_return_pct"] == 0


@pytest.mark.parametrize("opening,status", [(11.05, "closed"), (11.06, "skipped")])
@pytest.mark.parametrize("factor", [1.0, 1.81])
def test_limit_prices_round_half_up_to_cents(opening, status, factor):
    bars = daily_bars()
    bars.loc[:, ["open", "high", "low", "close"]] = 10.05
    bars.loc[:, "factor"] = factor
    bars.loc[bars.index[5], ["open", "high", "low", "close"]] = opening
    result = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    assert result["status"] == status


@pytest.mark.parametrize(
    "code,entry_day,opening,status",
    [
        ("300001", "2020-08-21", 11.0, "skipped"),
        ("300001", "2020-08-24", 11.0, "closed"),
        ("300001.SZ", "2020-08-24", 12.0, "skipped"),
        ("688001.SH", "2024-01-09", 12.0, "skipped"),
        ("430001.BJ", "2024-01-09", 12.0, "closed"),
        ("920001", "2024-01-09", 13.0, "skipped"),
        ("600001", "2024-01-09", 11.0, "skipped"),
    ],
)
def test_board_and_date_price_limits(code, entry_day, opening, status):
    days = pd.bdate_range(end=entry_day, periods=6).append(
        pd.bdate_range(entry_day, periods=2)[1:]
    )
    bars = daily_bars(len(days))
    bars.index = days.strftime("%Y-%m-%d")
    bars.loc[entry_day, ["open", "high", "low", "close"]] = opening
    # Stay flat after a permitted large opening, avoiding an unrelated exit lock.
    bars.loc[bars.index[6], ["open", "high", "low", "close"]] = opening
    result = simulate_opportunity(
        bars, bars.index[4], code=code, staged=False, hold_days=1, exit_rule="horizon"
    )
    assert result["status"] == status


@pytest.mark.parametrize(
    "entry_day,buy_rate,sell_rate",
    [
        ("2023-08-28", 0, 0.0005),
        ("2023-08-25", 0, 0.0005),
        ("2008-09-19", 0, 0.001),
        ("2008-09-18", 0.001, 0.001),
        ("2008-04-24", 0.001, 0.001),
        ("2008-04-23", 0.003, 0.001),
        ("2007-05-30", 0.003, 0.003),
        ("2007-05-29", 0.001, 0.003),
        ("2005-01-24", 0.001, 0.001),
        ("2001-11-16", 0.002, 0.002),
        ("1998-06-12", 0.004, 0.004),
        ("1997-05-12", 0.005, 0.005),
        ("1992-06-12", 0.003, 0.003),
    ],
)
def test_stamp_tax_historical_boundaries(entry_day, buy_rate, sell_rate):
    days = pd.bdate_range(end=entry_day, periods=6).append(
        pd.bdate_range(entry_day, periods=2)[1:]
    )
    bars = daily_bars(len(days))
    bars.index = days.strftime("%Y-%m-%d")
    result = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    assert result["status"] == "closed"
    leg = result["legs"][0]
    assert leg["entry_costs"]["stamp_rate"] == buy_rate
    assert leg["exit_costs"]["stamp_rate"] == sell_rate
    assert leg["entry_costs"]["stamp_tax"] == pytest.approx(100050 * buy_rate)
    assert leg["exit_costs"]["stamp_tax"] == pytest.approx(99950 * sell_rate)


def test_commission_minimum_slippage_fractional_shares_and_plan_denominator():
    bars = daily_bars()
    result = simulate(
        bars, notional=123, staged=False, hold_days=1, exit_rule="horizon"
    )
    leg = result["legs"][0]
    assert leg["quantity"] == 12.3
    assert leg["entry_costs"]["commission"] == 5
    assert leg["exit_costs"]["commission"] == 5
    expected_net = -10 - 2 * 123 * 0.0005 - 123 * 0.9995 * 0.0005
    assert result["net_return_pct"] == pytest.approx(expected_net / 123 * 100)


def test_unverified_early_cost_and_limit_regime_are_disclosed():
    bars = daily_bars(start="1991-01-02")
    result = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    assert result["status"] == "closed"
    assert "stamp_tax_unverified_before_1992_06_12" in result["evidence_flags"]
    assert "price_limit_regime_unverified_before_1996_12_16" in result["evidence_flags"]
    assert "historical_st_status_unavailable" in result["evidence_flags"]
    assert any(
        "unverified and assumed zero" in line for line in result["cost_assumption"]
    )


def test_minute_mode_never_falls_back_to_daily():
    bars = daily_bars()
    result = simulate(bars, mode="intraday_1450")
    assert result["status"] == "unverifiable"
    assert result["reason"] == "minute_data_missing"
    assert result["net_return_pct"] is None


@pytest.mark.parametrize("daily_close,late_price", [(8.0, 8.0), (15.0, 15.0)])
def test_minute_d2_ignores_daily_close_and_minutes_after_decision(
    daily_close, late_price
):
    bars = daily_bars(8)
    minutes = minute_data(bars)
    d2 = bars.index[4]
    bars.loc[d2, "close"] = daily_close
    minutes[d2].loc[f"{d2} 14:52" :, ["open", "high", "low", "close"]] = late_price
    result = simulate(
        bars,
        mode="intraday_1450",
        minutes=minutes,
        staged=False,
        exit_rule="horizon",
        hold_days=10,
    )
    leg = result["legs"][0]
    assert leg["entry_date"] == d2
    assert leg["entry_time"] == f"{d2}T14:51:00"
    assert leg["entry_price"] == 10
    decision = next(
        event for event in result["evidence"] if event["action"] == "snapshot_1450"
    )
    assert decision["ma5"] == 10
    assert result["status"] == "data_end"


@pytest.mark.parametrize(
    "latest,expected", [("14:49", "data_end"), ("14:48", "unverifiable")]
)
def test_1450_snapshot_maximum_one_minute_lag(latest, expected):
    bars = daily_bars(5)
    d2 = bars.index[4]
    frame = minute_bars(d2)
    frame = frame.drop(frame.loc[f"{d2} {latest}" : f"{d2} 14:50"].index[1:])
    result = simulate(bars, mode="intraday_1450", minutes={d2: frame}, staged=False)
    assert result["status"] == expected
    assert bool(result["legs"]) == (expected == "data_end")


def test_minute_d3_uses_snapshot_not_later_close_for_add():
    bars = daily_bars(7)
    minutes = minute_data(bars)
    d3 = bars.index[5]
    bars.loc[d3, "close"] = 8.0
    minutes[d3].loc[f"{d3} 14:52" :, ["open", "high", "low", "close"]] = 8.0
    result = simulate(bars, mode="intraday_1450", minutes=minutes, exit_rule="horizon")
    assert len(result["legs"]) == 2
    assert result["legs"][1]["entry_time"] == f"{d3}T14:51:00"
    assert result["legs"][1]["entry_price"] == 10
    assert result["legs"][1]["entry_reason"] == "d3_small_k"


def test_minute_gap_small_body_also_blocks_direct_add():
    bars = daily_bars(7)
    minutes = minute_data(bars)
    minutes[bars.index[5]] = minute_bars(bars.index[5], 10.4)
    result = simulate(bars, mode="intraday_1450", minutes=minutes, exit_rule="horizon")
    assert result["status"] == "data_end"
    assert len(result["legs"]) == 1


def test_minute_surge_requires_two_complete_windows_then_next_open():
    bars = daily_bars(7)
    minutes = surge_minutes(bars)
    d3 = bars.index[5]
    minutes[d3].loc[f"{d3} 09:46", "open"] = 10.12
    result = simulate(bars, mode="intraday_1450", minutes=minutes, exit_rule="horizon")
    leg = result["legs"][1]
    assert leg["entry_time"] == f"{d3}T09:46:00"
    assert leg["entry_price"] == 10.12
    windows = [
        event for event in result["evidence"] if event["action"] == "pullback_window"
    ]
    assert [event["time"] for event in windows] == [f"{d3}T09:40:00", f"{d3}T09:45:00"]


def test_missing_minute_does_not_count_as_a_complete_five_minute_window():
    bars = daily_bars(7)
    minutes = surge_minutes(bars)
    d3 = bars.index[5]
    minutes[d3] = minutes[d3].drop(pd.Timestamp(f"{d3} 09:40"))
    result = simulate(bars, mode="intraday_1450", minutes=minutes, exit_rule="horizon")
    assert result["legs"][1]["entry_time"] == f"{d3}T09:51:00"


def test_minute_d3_missing_high_coverage_is_unverifiable():
    bars = daily_bars(7)
    minutes = minute_data(bars)
    d3 = bars.index[5]
    minutes[d3] = minutes[d3].drop(pd.Timestamp(f"{d3} 10:00"))
    result = simulate(bars, mode="intraday_1450", minutes=minutes, exit_rule="horizon")
    assert result["status"] == "unverifiable"
    assert result["reason"] == f"minute_d3_coverage_incomplete: {d3}"


def test_each_leg_obeys_t_plus_one_and_keeps_the_unsellable_leg_queued():
    bars = daily_bars(7)
    minutes = surge_minutes(bars)
    d3, d4 = bars.index[5:7]
    minutes[d3].loc[f"{d3} 14:50" :, ["open", "high", "low", "close"]] = 9.9
    result = simulate(bars, mode="intraday_1450", minutes=minutes)
    assert result["status"] == "closed"
    assert result["legs"][0]["exit_time"] == f"{d3}T14:51:00"
    assert result["legs"][1]["exit_time"] == f"{d4}T09:30:00"
    assert "sell_queued_t_plus_one" in result["evidence_flags"]
    assert result["exit_reason"] == "ma5_break"
    assert all(leg["entry_date"] < leg["exit_date"] for leg in result["legs"])


def test_partial_exit_at_data_end_does_not_report_realized_total_return():
    bars = daily_bars(6)
    minutes = surge_minutes(bars)
    d3 = bars.index[5]
    minutes[d3].loc[f"{d3} 14:50" :, ["open", "high", "low", "close"]] = 9.9
    result = simulate(bars, mode="intraday_1450", minutes=minutes)
    assert result["status"] == "data_end"
    assert result["legs"][0]["exit_date"] == d3
    assert result["legs"][1]["exit_date"] is None
    assert result["exit_date"] is None
    assert result["gross_return_pct"] is None
    assert result["net_return_pct"] is None
    assert result["invested_net_return_pct"] is None
    assert result["realized_net_pnl"] == result["legs"][0]["net_pnl"]


def test_minute_lower_limit_and_suspension_queue_to_next_executable_session():
    bars = daily_bars(8)
    minutes = minute_data(bars)
    d3, d4, d5 = bars.index[5:8]
    minutes[d3] = minute_bars(d3, 9.0)
    bars.loc[d3, ["open", "high", "low", "close"]] = 9.0
    bars.loc[d4, ["open", "high", "low", "close"]] = float("nan")
    del minutes[d4]
    minutes[d5] = minute_bars(d5, 9.1)
    result = simulate(
        bars,
        mode="intraday_1450",
        minutes=minutes,
        staged=False,
        hold_days=1,
        exit_rule="horizon",
    )
    assert result["status"] == "closed"
    assert result["exit_date"] == d5
    assert result["legs"][0]["exit_price"] == 9.1
    assert "sell_queued_lower_limit" in result["evidence_flags"]
    assert "sell_queued_suspended" in result["evidence_flags"]


def test_missing_next_buy_minute_is_unverifiable_not_a_later_fill():
    bars = daily_bars(6)
    minutes = minute_data(bars)
    d2 = bars.index[4]
    minutes[d2] = minutes[d2].drop(pd.Timestamp(f"{d2} 14:51"))
    result = simulate(bars, mode="intraday_1450", minutes=minutes)
    assert result["status"] == "unverifiable"
    assert result["legs"] == []


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
def test_immature_horizon_returns_data_end(mode):
    bars = daily_bars(7)
    result = simulate(bars, mode=mode, minutes=minute_data(bars), hold_days=10)
    assert result["status"] == "data_end"
    assert result["net_return_pct"] is None
    assert result["gross_return_pct"] is None
    assert result["exit_date"] is None


def test_missing_entry_session_is_data_end():
    result = simulate(daily_bars(5))
    assert result["status"] == "data_end"
    assert result["legs"] == []


def test_inputs_are_not_modified_and_signals_are_independent():
    bars = daily_bars(8)
    minutes = minute_data(bars)
    original = bars.copy(deep=True)
    originals = {day: frame.copy(deep=True) for day, frame in minutes.items()}
    first = simulate(
        bars, mode="intraday_1450", minutes=minutes, hold_days=2, exit_rule="horizon"
    )
    second = simulate(
        bars, mode="intraday_1450", minutes=minutes, hold_days=2, exit_rule="horizon"
    )
    overlap = simulate_opportunity(
        bars,
        bars.index[5],
        code="600001",
        mode="intraday_1450",
        minutes=minutes,
        hold_days=2,
        exit_rule="horizon",
    )
    assert first == second
    assert overlap["status"] == "closed"
    assert overlap["legs"][0]["entry_date"] == bars.index[5]
    assert_frame_equal(bars, original)
    for day in minutes:
        assert_frame_equal(minutes[day], originals[day])


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
@pytest.mark.parametrize("factor", [float("nan"), 0.0])
def test_closed_trade_is_invariant_to_bad_factors_in_unused_future(mode, factor):
    bars = daily_bars()
    minutes = minute_data(bars)
    expected = simulate(
        bars.iloc[:8], mode=mode, minutes=minutes, hold_days=2, exit_rule="horizon"
    )
    assert expected["status"] == "closed"
    bars.loc[bars.index[8] :, "factor"] = factor
    actual = simulate(
        bars, mode=mode, minutes=minutes, hold_days=2, exit_rule="horizon"
    )
    assert actual == expected


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
@pytest.mark.parametrize("value", [float("nan"), 0.0, "unused_bad_quote"])
def test_closed_trade_is_invariant_to_unrelated_future_ohlcv(mode, value):
    bars = daily_bars()
    minutes = minute_data(bars)
    expected = simulate(
        bars.iloc[:8], mode=mode, minutes=minutes, hold_days=2, exit_rule="horizon"
    )
    assert expected["status"] == "closed"
    if isinstance(value, str):
        bars = bars.astype(
            {name: object for name in ["open", "high", "low", "close", "volume"]}
        )
    bars.loc[bars.index[8] :, ["open", "high", "low", "close", "volume"]] = value
    actual = simulate(
        bars, mode=mode, minutes=minutes, hold_days=2, exit_rule="horizon"
    )
    assert actual == expected


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
@pytest.mark.parametrize("factor", [float("nan"), 0.0])
def test_unknown_factor_in_required_ma5_history_remains_unverifiable(mode, factor):
    bars = daily_bars()
    bars.loc[bars.index[3], "factor"] = factor
    result = simulate(bars, mode=mode, minutes=minute_data(bars))
    assert result["status"] == "unverifiable"
    assert result["legs"] == []


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
@pytest.mark.parametrize("factor", [float("nan"), 0.0])
def test_unknown_factor_at_execution_boundary_remains_unverifiable(mode, factor):
    bars = daily_bars()
    entry_index = 5 if mode == "next_open" else 4
    bars.loc[bars.index[entry_index], "factor"] = factor
    result = simulate(bars, mode=mode, minutes=minute_data(bars), staged=False)
    assert result["status"] == "unverifiable"
    assert result["legs"] == []


@pytest.mark.parametrize("mode", ["next_open", "intraday_1450"])
def test_factor_not_consumed_by_horizon_hold_does_not_reject_trade(mode):
    bars = daily_bars()
    expected = simulate(
        bars,
        mode=mode,
        minutes=minute_data(bars),
        staged=False,
        hold_days=10,
        exit_rule="horizon",
    )
    bars.loc[bars.index[6], "factor"] = float("nan")
    actual = simulate(
        bars,
        mode=mode,
        minutes=minute_data(bars),
        staged=False,
        hold_days=10,
        exit_rule="horizon",
    )
    assert actual["status"] == "closed"
    assert actual == expected


def test_missing_next_sell_minute_is_unverifiable_not_a_later_fill():
    bars = daily_bars(7)
    minutes = minute_data(bars)
    d3 = bars.index[5]
    minutes[d3].loc[f"{d3} 14:50" :, ["open", "high", "low", "close"]] = 9.9
    minutes[d3] = minutes[d3].drop(pd.Timestamp(f"{d3} 14:51"))
    result = simulate(bars, mode="intraday_1450", minutes=minutes, staged=False)
    assert result["status"] == "unverifiable"
    assert result["reason"] == f"next_exit_minute_missing: {d3}T14:51:00"
    assert result["legs"][0]["exit_date"] is None


def test_missing_minute_while_sell_is_queued_does_not_fill_later_open():
    bars = daily_bars(7)
    minutes = minute_data(bars)
    d3 = bars.index[5]
    minutes[d3].loc[f"{d3} 14:50" :, ["open", "high", "low", "close"]] = 9.0
    minutes[d3].loc[f"{d3} 14:53" :, ["open", "high", "low", "close"]] = 9.1
    minutes[d3] = minutes[d3].drop(pd.Timestamp(f"{d3} 14:52"))
    result = simulate(bars, mode="intraday_1450", minutes=minutes, staged=False)
    assert result["status"] == "unverifiable"
    assert result["reason"] == f"next_exit_minute_missing: {d3}T14:52:00"
    assert result["legs"][0]["exit_date"] is None


def test_horizon_requires_session_open_evidence_in_minute_mode():
    bars = daily_bars(7)
    minutes = minute_data(bars)
    d3 = bars.index[5]
    minutes[d3] = minutes[d3].loc[f"{d3} 14:50" :]
    result = simulate(
        bars,
        mode="intraday_1450",
        minutes=minutes,
        staged=False,
        hold_days=1,
        exit_rule="horizon",
    )
    assert result["status"] == "unverifiable"
    assert result["reason"] == f"minute_session_open_missing: {d3}"
    assert result["legs"][0]["exit_date"] is None


@pytest.mark.parametrize("field", ["high", "low", "close", "volume"])
def test_daily_open_entry_does_not_depend_on_uncompleted_day_fields(field):
    bars = daily_bars()
    expected = simulate(bars, staged=False, hold_days=3, exit_rule="horizon")
    bars.loc[bars.index[5], field] = float("nan")
    actual = simulate(bars, staged=False, hold_days=3, exit_rule="horizon")
    assert actual["status"] == "closed"
    assert actual["legs"] == expected["legs"]


@pytest.mark.parametrize("field", ["high", "low", "close", "volume"])
def test_daily_open_exit_does_not_depend_on_uncompleted_day_fields(field):
    bars = daily_bars()
    expected = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    bars.loc[bars.index[6], field] = float("nan")
    actual = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    assert actual == expected


def test_unknown_close_keeps_the_occurred_open_entry_and_rejects_confirmation():
    bars = daily_bars()
    bars.loc[bars.index[5], "close"] = float("nan")
    result = simulate(bars)
    assert result["status"] == "unverifiable"
    assert result["reason"] == f"close_confirmation_missing: {bars.index[5]}"
    assert result["legs"][0]["entry_date"] == bars.index[5]
    assert result["legs"][0]["entry_price"] == 10


def test_daily_second_open_entry_ignores_its_uncompleted_close_and_volume():
    bars = daily_bars()
    bars.loc[bars.index[6], ["high", "low", "close", "volume"]] = float("nan")
    result = simulate(bars, hold_days=4, exit_rule="horizon")
    assert result["status"] == "closed"
    assert len(result["legs"]) == 2
    assert result["legs"][1]["entry_date"] == bars.index[6]
    assert result["legs"][1]["entry_price"] == 10


def test_bad_old_factor_outside_last_four_observations_is_not_consumed():
    bars = daily_bars()
    expected = simulate_opportunity(
        bars,
        bars.index[5],
        code="600001",
        staged=False,
        hold_days=1,
        exit_rule="horizon",
    )
    bars.loc[bars.index[0], "factor"] = 0
    actual = simulate_opportunity(
        bars,
        bars.index[5],
        code="600001",
        staged=False,
        hold_days=1,
        exit_rule="horizon",
    )
    assert actual == expected


def test_unknown_factor_at_exit_does_not_retroactively_remove_entry():
    bars = daily_bars()
    bars.loc[bars.index[6], "factor"] = 0
    result = simulate(bars, staged=False, hold_days=1, exit_rule="horizon")
    assert result["status"] == "unverifiable"
    assert len(result["legs"]) == 1
    assert result["legs"][0]["entry_date"] == bars.index[5]
    assert result["legs"][0]["exit_date"] is None
