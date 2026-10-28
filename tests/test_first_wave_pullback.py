from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.first_wave_pullback import (
    detect_first_waves,
    price_resonance_mainline,
)


def wave_bars() -> pd.DataFrame:
    close = np.array([10.0] * 20 + [10.2, 10.8, 11.5, 12.5, 12.2, 12.3, 12.4])
    volume = np.array([100.0] * 20 + [130, 150, 180, 400, 240, 100, 100])
    return pd.DataFrame(
        {"open": close - 0.02, "high": close + 0.05, "low": close - 0.05,
         "close": close, "volume": volume, "factor": 1.0},
        index=pd.bdate_range("2024-01-02", periods=len(close)).strftime("%Y-%m-%d"),
    )


def test_first_wave_freezes_before_adjustment_and_preserves_volume_denominator():
    bars = wave_bars()
    row = detect_first_waves(bars, code="300001")[0]
    assert row["status"] == "setup_ready"
    assert row["d0_date"] == bars.index[23]
    assert row["d1_date"] == bars.index[24]
    assert row["d2_date"] == bars.index[25]
    assert row["wave_gain"] == pytest.approx(12.55 / 9.95 - 1)
    assert row["wave_volume_ratio"] == pytest.approx(2.15)
    assert row["terminal_volume_ratio"] == pytest.approx(400 / 180)
    assert row["adjustment_volume_ratio"] == pytest.approx(0.6)


def test_reduce_by_one_third_means_two_thirds_not_one_third():
    bars = wave_bars()
    bars.loc[bars.index[24], "volume"] = 400 * 2 / 3
    assert detect_first_waves(bars)[0]["status"] == "setup_ready"
    bars.loc[bars.index[24], "volume"] += 0.01
    assert detect_first_waves(bars)[0]["status"] == "adjustment_volume"


def test_completed_setup_is_invariant_to_future_prices_volume_and_prefix_length():
    bars = wave_bars()
    expected = detect_first_waves(bars)[0]
    cut = detect_first_waves(bars.iloc[:26])[0]
    assert cut == expected
    future = pd.concat([bars, bars.iloc[-1:].set_axis(["2024-02-09"])])
    future.iloc[-1, :] = [99, 120, 80, 100, 100000, 1]
    assert detect_first_waves(future)[0] == expected
    # D2 intraday may qualify even if its later close falls below MA5.
    bars.loc[bars.index[25], ["open", "high", "low", "close", "volume"]] = [12, 14, 4, 5, 99999]
    assert detect_first_waves(bars)[0] == expected


def test_failed_early_wave_cannot_be_relabelled_after_later_gains():
    bars = wave_bars()
    bars.loc[bars.index[21], ["high", "low", "close"]] = [10.2, 9.4, 9.5]
    result = detect_first_waves(bars)
    assert result[0]["d1_date"] == bars.index[21]
    assert result[0]["status"] == "wave_trend_failed"
    assert not any(r["status"] == "setup_ready" for r in result)


def test_first_wave_allows_a_small_internal_pause_before_twenty_percent():
    bars = wave_bars()
    bars.loc[bars.index[21], ["high", "low", "close"]] = [10.2, 10.0, 10.1]
    row = detect_first_waves(bars)[0]
    assert row["status"] == "setup_ready"
    assert row["d1_date"] == bars.index[24]


@pytest.mark.parametrize("rally,volumes", [([12.1], [220]), ([11.0, 12.1], [120, 250])])
def test_twenty_percent_wave_does_not_require_three_up_days(rally, volumes):
    close = np.array([10.0] * 20 + rally + [12.0, 12.1])
    bars = pd.DataFrame(
        {"open": close - .02, "high": close + .05, "low": close - .05,
         "close": close, "volume": [100] * 20 + volumes + [140, 100], "factor": 1.0},
        index=pd.bdate_range("2024-01-02", periods=len(close)).strftime("%Y-%m-%d"),
    )
    row = detect_first_waves(bars)[0]
    assert row["status"] == "setup_ready"
    assert row["wave_days"] == len(rally)
    assert row["slope_daily"] > .01


def test_interrupted_wave_is_reported_and_missing_future_does_not_reject_pending_wave():
    bars = wave_bars()
    assert detect_first_waves(bars.iloc[:24]) == []
    bars.loc[bars.index[22], "volume"] = np.nan
    assert detect_first_waves(bars)[0]["status"] == "interrupted_wave"


def resonance_inputs():
    rng = np.random.default_rng(13)
    returns = rng.normal(0.001, 0.004, (100, 28))
    shared = 0.012 + 0.004 * np.sin(np.arange(100) / 3)
    returns[:, :8] = shared[:, None] + rng.normal(0, 0.0002, (100, 8))
    prices = 10 * np.exp(np.cumsum(returns, axis=0))
    volumes = np.full_like(prices, 100.0)
    volumes[-5:, :8] = 200
    return prices, volumes, [f"{k:06d}" for k in range(28)]


def test_resonance_uses_other_stocks_for_group_confirmation():
    prices, volumes, codes = resonance_inputs()
    result = price_resonance_mainline(prices, volumes, target=0, asof=99, codes=codes)
    assert result["passed"] is True
    assert codes[0] not in result["peers"]
    assert result["peer_count"] >= 5
    assert result["basis"] == "causal_price_resonance_proxy"


def test_mainline_is_prefix_causal_and_cannot_read_future_volume():
    prices, volumes, codes = resonance_inputs()
    expected = price_resonance_mainline(prices, volumes, target=0, asof=99, codes=codes)
    future_prices = np.vstack([prices, np.full((20, 28), 0.01)])
    future_volumes = np.vstack([volumes, np.full((20, 28), 1e9)])
    assert price_resonance_mainline(future_prices, future_volumes, target=0, asof=99, codes=codes) == expected


def test_target_cannot_count_itself_towards_minimum_peers():
    prices, volumes, codes = resonance_inputs()
    result = price_resonance_mainline(prices[:, :5], volumes[:, :5], target=0, asof=99, codes=codes[:5])
    assert result["passed"] is False
    assert result["reason"] == "too_few_correlated_peers"


def test_suspended_or_incomplete_recent_peers_cannot_supply_mainline_confirmation():
    prices, volumes, codes = resonance_inputs()
    volumes[-5:, 1:5] = np.nan
    result = price_resonance_mainline(prices, volumes, target=0, asof=99, codes=codes)
    assert result["passed"] is False
    assert result["reason"] == "too_few_correlated_peers"
    assert result["peer_count"] == 3
