"""Synthetic sampled quotes only: no providers, network or real databases."""

from concurrent.futures import ThreadPoolExecutor
import json

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from scripts.first_wave_quote_execution import simulate_quote_opportunity


def daily_bars(periods=12, start="2024-01-02"):
    return pd.DataFrame(
        {
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "volume": 10000.0,
            "factor": 1.0,
        },
        index=pd.bdate_range(start, periods=periods).strftime("%Y-%m-%d"),
    )


def quote_frame(day, price=10.0, *, opening=False):
    times = pd.date_range(f"{day} 09:31", f"{day} 11:30", freq="min").union(
        pd.date_range(f"{day} 13:01", f"{day} 15:00", freq="min")
    )
    if opening:
        times = times.insert(0, pd.Timestamp(f"{day} 09:30"))
    return pd.DataFrame({"close": price, "volume": 100.0}, index=times)


def quote_data(bars, **kwargs):
    return {day: quote_frame(day, **kwargs) for day in bars.index[4:]}


def no_trades():
    frame = pd.DataFrame(columns=["close", "volume"], index=pd.DatetimeIndex([]))
    frame.attrs["confirmed_no_trades"] = True
    return frame


def simulate(bars, quotes, **kwargs):
    return simulate_quote_opportunity(
        bars, bars.index[4], code="600001", quotes=quotes, **kwargs
    )


def surge_data(bars):
    quotes = quote_data(bars)
    d3 = bars.index[5]
    quotes[d3] = quote_frame(d3, 10.05)
    quotes[d3].loc[f"{d3} 09:35", "close"] = 10.5
    return quotes


def test_contract_stages_market_horizon_and_costs():
    bars = daily_bars()
    quotes = quote_data(bars)
    result = simulate(bars, quotes, hold_days=3)
    assert result["status"] == "closed"
    assert result["mode"] == "sampled_quotes_1450"
    assert result["staged"] is True
    assert result["exit_rule"] == "ma5_or_horizon"
    assert result["hold_days"] == 3
    assert [leg["entry_time"] for leg in result["legs"]] == [
        f"{bars.index[4]}T14:51:00",
        f"{bars.index[5]}T14:51:00",
    ]
    assert result["exit_date"] == bars.index[7]
    assert result["exit_reason"] == "horizon"
    assert [leg["notional"] for leg in result["legs"]] == [50000, 50000]
    assert result["uninvested_cash"] == 0
    assert result["gross_return_pct"] == 0
    assert result["net_return_pct"] < 0
    assert result["net_pnl"] == result["realized_net_pnl"]
    assert "sampled_price_surge_definition" in result["evidence_flags"]
    assert "strict_minute_execution" not in result["evidence_flags"]
    assert "historical_st_status_unavailable" in result["evidence_flags"]
    assert "historical_delisting_pool_unavailable" in result["evidence_flags"]
    assert all(
        pd.Timestamp(leg["entry_time"]) > pd.Timestamp(leg["entry_decision_time"])
        for leg in result["legs"]
    )


def test_d2_decision_ignores_unfinished_daily_ohlcv_and_future_quotes():
    bars = daily_bars(5)
    quotes = quote_data(bars)
    expected = simulate(bars, quotes)
    d2 = bars.index[4]
    bars.loc[d2, ["open", "high", "low", "close", "volume"]] = [20, 30, 1, 1, 0]
    quotes[d2].loc[f"{d2} 14:52" :, ["close", "volume"]] = float("nan")
    assert simulate(bars, quotes) == expected
    assert expected["legs"][0]["entry_price"] == 10


@pytest.mark.parametrize("missing_1450", [True, False])
def test_zero_volume_is_observed_and_1449_snapshot_cannot_fill_1450(missing_1450):
    bars = daily_bars(5)
    quotes = quote_data(bars)
    d2 = bars.index[4]
    quotes[d2].loc[f"{d2} 14:49", ["close", "volume"]] = [10.0, 0]
    if missing_1450:
        quotes[d2] = quotes[d2].drop(pd.Timestamp(f"{d2} 14:50"))
    else:
        quotes[d2].loc[f"{d2} 14:50", ["close", "volume"]] = [10.0, 0]
    quotes[d2].loc[f"{d2} 14:51", ["close", "volume"]] = [10.1, 0]
    quotes[d2].loc[f"{d2} 14:52", ["close", "volume"]] = [float("nan"), 0]
    quotes[d2].loc[f"{d2} 14:53", "close"] = 10.2
    result = simulate(bars, quotes)
    leg = result["legs"][0]
    assert leg["entry_time"] == f"{d2}T14:53:00"
    assert leg["entry_decision_time"] == f"{d2}T14:50:00"
    assert leg["entry_price"] == 10.2
    snapshot = next(e for e in result["evidence"] if e["action"] == "snapshot_1450")
    assert snapshot["time"] == f"{d2}T14:{'49' if missing_1450 else '50'}:00"
    assert snapshot["price"] == 10


def test_invalid_1450_price_can_use_last_valid_1449_observation():
    bars = daily_bars(5)
    quotes = quote_data(bars)
    day = bars.index[4]
    quotes[day].loc[f"{day} 14:50", "close"] = float("nan")
    result = simulate(bars, quotes)
    assert result["legs"][0]["entry_time"] == f"{day}T14:51:00"
    assert result["evidence"][0]["time"] == f"{day}T14:49:00"


def test_stale_snapshot_is_unverifiable_without_using_1451():
    bars = daily_bars(5)
    quotes = quote_data(bars)
    day = bars.index[4]
    quotes[day] = quotes[day].drop(
        pd.date_range(f"{day} 14:49", f"{day} 14:50", freq="min")
    )
    quotes[day].loc[f"{day} 14:51", "close"] = 10.5
    result = simulate(bars, quotes)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == day
    assert result["legs"] == []


def test_d2_below_dynamic_ma5_skips_before_any_add():
    bars = daily_bars()
    quotes = quote_data(bars)
    day = bars.index[4]
    quotes[day].loc[f"{day} 14:50", "close"] = 9.99
    result = simulate(bars, quotes)
    assert result["status"] == "skipped"
    assert result["legs"] == []
    assert result["net_return_pct"] == 0
    assert result["uninvested_cash"] == 100000


def test_first_actual_fill_sets_horizon_after_zero_volume_delay():
    bars = daily_bars()
    quotes = quote_data(bars)
    d2, d3 = bars.index[4:6]
    quotes[d2].loc[f"{d2} 14:51" :, "volume"] = 0
    result = simulate(bars, quotes, hold_days=2)
    assert result["status"] == "closed"
    assert result["entry_date"] == d3
    assert result["legs"][0]["entry_time"] == f"{d3}T09:31:00"
    assert result["exit_date"] == bars.index[7]


@pytest.mark.parametrize("surge_observation", ["daily_open", "sampled_close"])
def test_surge_observed_while_first_buy_waits_is_kept_after_that_fill(
    surge_observation,
):
    bars = daily_bars()
    quotes = quote_data(bars)
    d2, d3 = bars.index[4:6]
    quotes[d2].loc[f"{d2} 14:51" :, "volume"] = 0
    quotes[d3] = quote_frame(d3, 10.05)
    quotes[d3].loc[f"{d3} 09:31" : f"{d3} 09:35", "volume"] = 0
    if surge_observation == "daily_open":
        bars.loc[d3, "open"] = 10.5
    else:
        quotes[d3].loc[f"{d3} 09:35", "close"] = 10.5
    result = simulate(bars, quotes, hold_days=3)
    assert result["legs"][0]["entry_time"] == f"{d3}T09:36:00"
    assert result["legs"][1]["entry_time"] == f"{d3}T09:46:00"
    assert result["legs"][1]["entry_reason"] == "ma5_pullback_two_windows"


def test_never_filled_first_order_cannot_create_a_second_leg():
    bars = daily_bars(7)
    quotes = quote_data(bars)
    for day, frame in quotes.items():
        frame.loc[:, "volume"] = 0
    result = simulate(bars, quotes)
    assert result["status"] == "data_end"
    assert result["legs"] == []
    assert result["net_return_pct"] is None
    assert not any(e["action"] == "add_queued" for e in result["evidence"])


def test_d3_small_k_uses_daily_open_and_next_sampled_close():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    d3 = bars.index[5]
    bars.loc[d3, ["high", "low", "close"]] = [30, 1, 20]
    quotes[d3].loc[f"{d3} 09:31", "close"] = 10.3
    quotes[d3].loc[f"{d3} 14:51", "close"] = 10.2
    result = simulate(bars, quotes)
    assert len(result["legs"]) == 2
    assert result["legs"][1]["entry_reason"] == "d3_small_k"
    assert result["legs"][1]["entry_time"] == f"{d3}T14:51:00"
    assert result["legs"][1]["entry_price"] == 10.2
    assert not any(e["action"] == "pullback_wait" for e in result["evidence"])


@pytest.mark.parametrize(
    "opening,price,adds",
    [
        (10.0, 10.0, True),
        (10.3, 10.1, True),
        (10.4, 10.4, False),
        (10.4, 10.1, False),
        (9.8, 10.0, False),
    ],
)
def test_d3_small_k_body_and_absolute_daily_change(opening, price, adds):
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[5]
    bars.loc[day, "open"] = opening
    quotes[day].loc[:, "close"] = price
    result = simulate(bars, quotes)
    assert len(result["legs"]) == (2 if adds else 1)


def test_sampled_surge_then_two_windows_fills_strictly_after_confirmation():
    bars = daily_bars()
    quotes = surge_data(bars)
    d3 = bars.index[5]
    # A zero-volume endpoint can confirm the band, but cannot fill the order.
    quotes[d3].loc[f"{d3} 09:40", ["close", "volume"]] = [10.05, 0]
    quotes[d3].loc[f"{d3} 09:46", "close"] = 10.11
    result = simulate(bars, quotes, hold_days=3)
    assert result["status"] == "closed"
    add = result["legs"][1]
    assert add["entry_reason"] == "ma5_pullback_two_windows"
    assert add["entry_decision_time"] == f"{d3}T09:45:00"
    assert add["entry_time"] == f"{d3}T09:46:00"
    assert add["entry_price"] == 10.11
    surge = next(e for e in result["evidence"] if e["action"] == "pullback_wait")
    assert surge["observation"] == "sampled_close"
    assert surge["price"] == 10.5
    assert "high" not in surge


@pytest.mark.parametrize("escaped,expected_fill", [("09:40", "09:51"), ("09:45", "09:56")])
def test_rally_away_from_ma5_band_restarts_pullback_confirmation(escaped, expected_fill):
    bars = daily_bars()
    quotes = surge_data(bars)
    day = bars.index[5]
    quotes[day].loc[f"{day} {escaped}", "close"] = 10.3

    result = simulate(bars, quotes, hold_days=3)

    rejected = next(e for e in result["evidence"] if e["action"] == "pullback_window"
                    and e["time"] == f"{day}T{escaped}:00")
    assert rejected["price"] > rejected["ma5"] * 1.01
    assert rejected["held"] is False
    assert result["legs"][1]["entry_time"] == f"{day}T{expected_fill}:00"


def test_d3_opening_gap_counts_even_when_first_quote_already_retraced():
    bars = daily_bars()
    quotes = quote_data(bars)
    d3 = bars.index[5]
    bars.loc[d3, "open"] = 10.5
    quotes[d3] = quote_frame(d3, 10.05)
    result = simulate(bars, quotes, hold_days=3)
    assert result["legs"][1]["entry_reason"] == "ma5_pullback_two_windows"
    assert result["legs"][1]["entry_time"] == f"{d3}T09:41:00"
    surge = next(e for e in result["evidence"] if e["action"] == "pullback_wait")
    assert surge["time"] == f"{d3}T09:30:00"
    assert surge["observation"] == "daily_open"


def test_gap_detection_uses_adjusted_previous_close():
    bars = daily_bars()
    quotes = quote_data(bars)
    d3 = bars.index[5]
    bars.loc[d3:, ["open", "high", "low", "close"]] /= 2
    bars.loc[d3:, "factor"] = 2
    bars.loc[d3, "open"] = 5.25
    for day in bars.index[5:]:
        quotes[day] = quote_frame(day, 5.025)
    result = simulate(bars, quotes, hold_days=3)
    surge = next(e for e in result["evidence"] if e["action"] == "pullback_wait")
    assert surge["reference"] == 5
    assert result["legs"][1]["entry_time"] == f"{d3}T09:41:00"


def test_future_surge_does_not_cancel_already_confirmed_small_k_add():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[5]
    quotes[day].loc[f"{day} 14:55", "close"] = 10.6
    result = simulate(bars, quotes)
    assert result["legs"][1]["entry_reason"] == "d3_small_k"
    assert result["legs"][1]["entry_time"] == f"{day}T14:51:00"


def test_waiting_for_pullback_can_continue_on_later_market_dates():
    bars = daily_bars()
    quotes = quote_data(bars)
    d3, d4 = bars.index[5:7]
    quotes[d3] = quote_frame(d3, 10.4)
    quotes[d3].loc[f"{d3} 09:35", "close"] = 10.5
    bars.loc[d3, "close"] = 10.4
    quotes[d4] = quote_frame(d4, 10.2)
    result = simulate(bars, quotes, hold_days=3)
    assert result["legs"][1]["entry_time"] == f"{d4}T09:41:00"
    assert result["legs"][1]["entry_reason"] == "ma5_pullback_two_windows"


def test_windows_cannot_bridge_lunch():
    bars = daily_bars()
    quotes = quote_data(bars)
    day = bars.index[5]
    quotes[day] = quote_frame(day, 10.4)
    quotes[day].loc[f"{day} 11:25", "close"] = 10.5
    quotes[day].loc[f"{day} 11:26" :, "close"] = 10.05
    result = simulate(bars, quotes, hold_days=3)
    assert result["legs"][1]["entry_time"] == f"{day}T13:11:00"


@pytest.mark.parametrize("gap", ["missing", "nan", "failed_endpoint"])
def test_incomplete_or_failed_windows_restart_confirmation(gap):
    bars = daily_bars()
    quotes = surge_data(bars)
    day = bars.index[5]
    t = pd.Timestamp(f"{day} 09:40")
    if gap == "missing":
        quotes[day] = quotes[day].drop(t)
    else:
        quotes[day].loc[t, "close"] = float("nan") if gap == "nan" else 9.9
    result = simulate(bars, quotes, hold_days=3)
    assert result["legs"][1]["entry_time"] == f"{day}T09:51:00"


def test_each_leg_obeys_t_plus_one_and_queues_new_leg_until_next_session():
    bars = daily_bars(7)
    quotes = surge_data(bars)
    d3, d4 = bars.index[5:7]
    quotes[d3].loc[f"{d3} 14:50" :, "close"] = 9.9
    result = simulate(bars, quotes)
    assert result["status"] == "closed"
    assert result["legs"][0]["exit_time"] == f"{d3}T14:51:00"
    assert result["legs"][1]["exit_time"] == f"{d4}T09:31:00"
    assert result["exit_reason"] == "ma5_break"
    assert "sell_queued_t_plus_one" in result["evidence_flags"]
    assert all(leg["entry_date"] < leg["exit_date"] for leg in result["legs"])


def test_partial_exit_is_preserved_when_next_required_quote_date_is_missing():
    bars = daily_bars(7)
    quotes = surge_data(bars)
    d3, d4 = bars.index[5:7]
    quotes[d3].loc[f"{d3} 14:50" :, "close"] = 9.9
    del quotes[d4]
    result = simulate(bars, quotes)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == d4
    assert result["legs"][0]["exit_date"] == d3
    assert result["legs"][1]["exit_date"] is None
    assert result["exit_date"] is None
    assert result["net_return_pct"] is None
    assert result["net_pnl"] is None
    assert result["realized_net_pnl"] == result["legs"][0]["net_pnl"]


def test_partial_exit_at_library_end_is_not_a_realized_total_return():
    bars = daily_bars(6)
    quotes = surge_data(bars)
    d3 = bars.index[5]
    quotes[d3].loc[f"{d3} 14:50" :, "close"] = 9.9
    result = simulate(bars, quotes)
    assert result["status"] == "data_end"
    assert result["legs"][0]["exit_date"] == d3
    assert result["legs"][1]["exit_date"] is None
    assert result["gross_return_pct"] is None
    assert result["invested_net_return_pct"] is None
    assert result["missing_quote_date"] is None


def test_ma5_exit_uses_next_positive_volume_quote_and_cancels_add():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[5]
    quotes[day].loc[f"{day} 14:50" :, "close"] = 9.9
    quotes[day].loc[f"{day} 14:51" : f"{day} 14:52", "volume"] = 0
    quotes[day].loc[f"{day} 14:53", "close"] = 9.8
    result = simulate(bars, quotes)
    assert result["status"] == "closed"
    assert len(result["legs"]) == 1
    assert result["legs"][0]["exit_time"] == f"{day}T14:53:00"
    assert result["legs"][0]["exit_price"] == 9.8


def test_lower_limit_can_unlock_at_a_later_sample():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[5]
    quotes[day] = quote_frame(day, 9.0)
    quotes[day].loc[f"{day} 09:40" :, "close"] = 9.1
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "closed"
    assert result["legs"][0]["exit_time"] == f"{day}T09:40:00"
    assert "sell_queued_lower_limit" in result["evidence_flags"]


def test_lower_limit_and_confirmed_suspension_queue_exit_counting_market_days():
    bars = daily_bars(8)
    quotes = quote_data(bars)
    d3, d4, d5 = bars.index[5:8]
    quotes[d3] = quote_frame(d3, 9)
    bars.loc[d3, "close"] = 9
    bars.loc[d4, ["open", "high", "low", "close", "factor"]] = float("nan")
    quotes[d4] = no_trades()
    quotes[d5] = quote_frame(d5, 9.1)
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "closed"
    assert result["exit_date"] == d5
    assert "sell_queued_lower_limit" in result["evidence_flags"]
    assert "sell_queued_suspended" in result["evidence_flags"]


def test_missing_none_is_not_suspension_even_with_nan_daily_prices():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[5]
    bars.loc[day, ["open", "high", "low", "close"]] = float("nan")
    quotes[day] = None
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == day
    assert len(result["legs"]) == 1


def test_confirmed_no_trades_on_signal_date_skips_entry():
    bars = daily_bars()
    quotes = {bars.index[4]: no_trades()}
    result = simulate(bars, quotes)
    assert result["status"] == "skipped"
    assert result["reason"] == "signal_no_trades"
    assert result["legs"] == []
    assert result["missing_quote_date"] is None


def test_confirmed_no_trade_days_count_toward_horizon_without_using_their_factor():
    bars = daily_bars(8)
    quotes = quote_data(bars)
    d3, d4, d5 = bars.index[5:8]
    for day in (d3, d4):
        quotes[day] = no_trades()
        bars.loc[day, :] = float("nan")
    result = simulate(bars, quotes, hold_days=2)
    assert result["status"] == "closed"
    assert len(result["legs"]) == 1
    assert result["exit_reason"] == "horizon"
    assert result["exit_date"] == d5


def test_confirmed_no_trade_day_does_not_count_as_a_closing_observation():
    bars = daily_bars(8)
    quotes = quote_data(bars)
    d3 = bars.index[5]
    bars.loc[d3, :] = float("nan")
    quotes[d3] = no_trades()
    result = simulate(bars, quotes, hold_days=3)
    assert result["status"] == "closed"
    later_snapshot = next(
        e
        for e in result["evidence"]
        if e["action"] == "snapshot_1450" and e["date"] == bars.index[6]
    )
    assert later_snapshot["ma5"] == 10


def test_confirmed_no_trade_day_ignores_stale_daily_prices_and_unused_bad_factor():
    bars = daily_bars(8)
    quotes = quote_data(bars)
    day = bars.index[5]
    bars.loc[day, "factor"] = float("nan")
    quotes[day] = no_trades()
    result = simulate(bars, quotes, hold_days=3)
    assert result["status"] == "closed"
    assert result["exit_date"] == bars.index[7]


def test_known_quote_session_with_unknown_daily_close_cannot_reuse_an_older_close():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[4]
    bars.loc[day, ["open", "high", "low", "close"]] = float("nan")
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "unverifiable"
    assert result["reason"] == f"reference_price_missing: {bars.index[5]}"
    assert len(result["legs"]) == 1
    assert result["legs"][0]["entry_date"] == day


@pytest.mark.parametrize("quotes", [None, {}, {"2024-01-08": pd.DataFrame()}])
def test_unknown_empty_day_requests_missing_date(quotes):
    bars = daily_bars(5)
    result = simulate(bars, quotes)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == bars.index[4]


def test_corporate_action_uses_raw_prices_and_factor_economic_return():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    d3 = bars.index[5]
    bars.loc[d3, ["open", "high", "low", "close"]] /= 2
    bars.loc[d3, "factor"] = 2
    quotes[d3] = quote_frame(d3, 5.25)
    result = simulate(bars, quotes, hold_days=1)
    leg = result["legs"][0]
    assert result["status"] == "closed"
    assert leg["entry_price"] == 10
    assert leg["exit_price"] == 5.25
    assert leg["entry_factor"] == 1
    assert leg["exit_factor"] == 2
    assert leg["exit_quantity"] == 2 * leg["quantity"]
    assert result["gross_pnl"] == 2500
    assert result["gross_return_pct"] == 2.5
    assert result["invested_gross_return_pct"] == 5
    assert result["invested_net_return_pct"] == 2 * result["net_return_pct"]
    assert result["uninvested_cash"] == 50000
    assert "sell_queued_lower_limit" not in result["evidence_flags"]
    assert leg["entry_costs"]["commission"] == pytest.approx(50025 * 0.0003)
    assert leg["exit_costs"]["stamp_tax"] == pytest.approx(52500 * 0.9995 * 0.0005)


@pytest.mark.parametrize("factor", [0.5, 2.0])
def test_ex_rights_reference_does_not_falsely_block_first_buy(factor):
    bars = daily_bars(6)
    quotes = quote_data(bars)
    for day in bars.index[4:]:
        bars.loc[day, ["open", "high", "low", "close"]] /= factor
        bars.loc[day, "factor"] = factor
        quotes[day] = quote_frame(day, 10 / factor)
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "closed"
    assert result["legs"][0]["entry_price"] == 10 / factor
    assert result["gross_return_pct"] == 0


@pytest.mark.parametrize("price,status", [(11.05, "closed"), (11.06, "skipped")])
@pytest.mark.parametrize("factor", [1.0, 1.81])
def test_upper_limit_rounds_half_up_to_cents(price, status, factor):
    bars = daily_bars(6)
    bars.loc[:, ["open", "high", "low", "close"]] = 10.05
    bars.loc[:, "factor"] = factor
    quotes = {day: quote_frame(day, 10.05) for day in bars.index[4:]}
    day = bars.index[4]
    quotes[day].loc[f"{day} 14:51", "close"] = price
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == status
    if status == "skipped":
        assert result["reason"] == "first_buy_upper_limit"
        assert result["legs"] == []


@pytest.mark.parametrize(
    "code,entry_day,price,status",
    [
        ("300001", "2020-08-21", 11, "skipped"),
        ("300001", "2020-08-24", 11, "closed"),
        ("300001.SZ", "2020-08-24", 12, "skipped"),
        ("688001.SH", "2024-01-09", 12, "skipped"),
        ("430001.BJ", "2024-01-09", 12, "closed"),
        ("920001", "2024-01-09", 13, "skipped"),
        ("600001", "2024-01-09", 11, "skipped"),
    ],
)
def test_board_and_historical_limit_rules_are_reused(code, entry_day, price, status):
    bars = daily_bars(6)
    days = pd.bdate_range(end=entry_day, periods=5).append(
        pd.bdate_range(entry_day, periods=2)[1:]
    )
    bars.index = days.strftime("%Y-%m-%d")
    quotes = quote_data(bars)
    quotes[entry_day].loc[f"{entry_day} 14:51", "close"] = price
    result = simulate_quote_opportunity(
        bars, entry_day, code=code, quotes=quotes, hold_days=1
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
        ("1991-06-12", 0, 0),
    ],
)
def test_stamp_boundaries_and_minimum_commission(entry_day, buy_rate, sell_rate):
    bars = daily_bars(6)
    days = pd.bdate_range(end=entry_day, periods=5).append(
        pd.bdate_range(entry_day, periods=2)[1:]
    )
    bars.index = days.strftime("%Y-%m-%d")
    result = simulate(bars, quote_data(bars), hold_days=1, notional=1000)
    assert result["status"] == "closed"
    leg = result["legs"][0]
    assert leg["entry_costs"]["stamp_rate"] == buy_rate
    assert leg["exit_costs"]["stamp_rate"] == sell_rate
    assert leg["entry_costs"]["commission"] == 5
    assert leg["exit_costs"]["commission"] == 5
    assert leg["entry_costs"]["slippage"] == 0.25
    assert leg["exit_costs"]["slippage"] == 0.25
    if entry_day < "1996-12-16":
        assert (
            "price_limit_regime_unverified_before_1996_12_16"
            in result["evidence_flags"]
        )
    if entry_day < "1992-06-12":
        assert "stamp_tax_unverified_before_1992_06_12" in result["evidence_flags"]


@pytest.mark.parametrize("opening", [False, True])
def test_both_240_and_241_sources_and_shanghai_timezone(opening):
    bars = daily_bars(6)
    quotes = quote_data(bars, opening=opening)
    assert all(len(frame) == (241 if opening else 240) for frame in quotes.values())
    for frame in quotes.values():
        frame.index = frame.index.tz_localize("Asia/Shanghai").tz_convert("UTC")
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "closed"
    assert (
        result["legs"][0]["exit_time"]
        == f"{bars.index[5]}T09:{'30' if opening else '31'}:00"
    )


@pytest.mark.parametrize("factor", [0, float("nan"), float("inf")])
def test_required_history_factor_is_not_replaced_by_older_close(factor):
    bars = daily_bars()
    quotes = quote_data(bars)
    bars.loc[bars.index[3], "factor"] = factor
    result = simulate(bars, quotes)
    assert result["status"] == "unverifiable"
    assert result["legs"] == []
    assert result["missing_quote_date"] is None


def test_insufficient_four_prior_observations_is_unverifiable():
    bars = daily_bars()
    day = bars.index[2]
    result = simulate_quote_opportunity(
        bars, day, code="600001", quotes={day: quote_frame(day)}
    )
    assert result["reason"] == "insufficient_ma5_history"
    assert result["legs"] == []


@pytest.mark.parametrize("factor", [0, float("nan")])
def test_bad_factor_at_exit_retains_occurred_entry(factor):
    bars = daily_bars(6)
    quotes = quote_data(bars)
    bars.loc[bars.index[5], "factor"] = factor
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "unverifiable"
    assert len(result["legs"]) == 1
    assert result["legs"][0]["exit_date"] is None


@pytest.mark.parametrize("bad", [0, float("nan"), "unused_bad_data"])
def test_closed_trade_is_invariant_to_future_bad_factors_daily_fields_and_quotes(bad):
    bars = daily_bars()
    quotes = quote_data(bars)
    expected = simulate(bars.iloc[:6], quotes, hold_days=1)
    assert expected["status"] == "closed"
    bars = bars.astype(object)
    bars.loc[bars.index[6] :, :] = bad
    for day in bars.index[6:]:
        quotes[day] = pd.DataFrame({"bad_future_schema": [bad]})
    d3 = bars.index[5]
    quotes[d3] = quotes[d3].astype(object)
    quotes[d3].loc[f"{d3} 09:32" :, :] = bad
    bars.loc[d3, ["high", "low", "close", "volume"]] = bad
    assert simulate(bars, quotes, hold_days=1) == expected


@pytest.mark.parametrize(
    "field,bad", [("close", float("nan")), ("volume", float("nan")), ("volume", -1)]
)
def test_unknown_next_execution_quote_does_not_skip_to_a_later_fill(field, bad):
    bars = daily_bars(5)
    quotes = quote_data(bars)
    day = bars.index[4]
    quotes[day].loc[f"{day} 14:51", field] = bad
    result = simulate(bars, quotes)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == day
    assert result["legs"] == []


def test_missing_next_execution_sample_requests_same_day_not_later_fill():
    bars = daily_bars(5)
    quotes = quote_data(bars)
    day = bars.index[4]
    quotes[day] = quotes[day].drop(pd.Timestamp(f"{day} 14:51"))
    result = simulate(bars, quotes)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == day
    assert result["legs"] == []


def test_horizon_requires_early_session_samples_to_prove_first_executable_quote():
    bars = daily_bars(6)
    quotes = quote_data(bars)
    day = bars.index[5]
    quotes[day] = quotes[day].loc[f"{day} 14:50" :]
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "unverifiable"
    assert result["missing_quote_date"] == day
    assert len(result["legs"]) == 1


def test_horizon_cancels_waiting_add_and_exits_at_first_positive_volume_quote():
    bars = daily_bars(6)
    quotes = surge_data(bars)
    day = bars.index[5]
    quotes[day].loc[f"{day} 09:31" : f"{day} 09:33", "volume"] = 0
    result = simulate(bars, quotes, hold_days=1)
    assert result["status"] == "closed"
    assert len(result["legs"]) == 1
    assert result["legs"][0]["exit_time"] == f"{day}T09:34:00"


def test_data_end_with_open_leg_does_not_mark_to_market_as_realized():
    bars = daily_bars(5)
    result = simulate(bars, quote_data(bars))
    assert result["status"] == "data_end"
    assert len(result["legs"]) == 1
    assert result["exit_date"] is None
    assert result["net_pnl"] is None
    assert result["net_return_pct"] is None
    assert result["realized_gross_pnl"] == 0


def test_inputs_remain_unchanged_and_parallel_calls_are_independent():
    bars = daily_bars(8)
    quotes = surge_data(bars)
    original = bars.copy(deep=True)
    originals = {day: frame.copy(deep=True) for day, frame in quotes.items()}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(lambda _: simulate(bars, quotes, hold_days=3), range(8))
        )
    assert results[0]["status"] == "closed"
    assert all(result == results[0] for result in results)
    assert json.loads(json.dumps(results[0])) == results[0]
    assert_frame_equal(bars, original)
    for day, frame in quotes.items():
        assert_frame_equal(frame, originals[day])
        assert frame.attrs == originals[day].attrs


@pytest.mark.parametrize("hold_days", [0, -1, True, 1.5])
def test_invalid_horizon_is_rejected(hold_days):
    bars = daily_bars(5)
    with pytest.raises(ValueError, match="hold_days"):
        simulate(bars, quote_data(bars), hold_days=hold_days)


@pytest.mark.parametrize("notional", [0, -1, float("nan"), float("inf")])
def test_invalid_notional_is_rejected(notional):
    bars = daily_bars(5)
    with pytest.raises(ValueError, match="notional"):
        simulate(bars, quote_data(bars), notional=notional)
