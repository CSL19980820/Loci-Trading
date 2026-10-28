from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import src.strategy.application.first_wave_strategy as strategy_module
from src.strategy.application.first_wave_pullback import (
    FirstWaveConfig,
    _detect_first_waves_panel,
    detect_first_waves,
)
from src.strategy.application.first_wave_strategy import FirstWavePullbackV1
from src.strategy.domain.base import StrategyError


def wave_panels() -> dict[str, pd.DataFrame]:
    close = np.array([10.0] * 20 + [10.2, 10.8, 11.5, 12.5, 12.2, 12.3, 12.4])
    index = pd.bdate_range("2024-01-02", periods=len(close)).strftime("%Y-%m-%d")
    return {
        "open": pd.DataFrame({"300001": close - 0.02}, index=index),
        "high": pd.DataFrame({"300001": close + 0.05}, index=index),
        "low": pd.DataFrame({"300001": close - 0.05}, index=index),
        "close": pd.DataFrame({"300001": close}, index=index),
        "volume": pd.DataFrame(
            {"300001": [100.0] * 20 + [130, 150, 180, 400, 240, 100, 100]},
            index=index,
        ),
    }


def test_daily_first_wave_strategy_registers_and_emits_d2_signal_without_mainline():
    engine = FirstWavePullbackV1()
    panels = wave_panels()

    result = engine.compute(panels, {"mainline_mode": "none"})

    signal_day = panels["close"].index[25]
    assert bool(result.signals.at[signal_day, "300001"])
    assert result.factors["D2守住MA5"].at[signal_day, "300001"] == 1
    assert result.factors["D1缩量比"].at[signal_day, "300001"] == pytest.approx(0.6)
    assert result.factors["首波涨幅"].at[signal_day, "300001"] == pytest.approx(
        (12.55 / 9.95 - 1) * 100
    )


def test_first_wave_strategy_is_prefix_causal_for_completed_d2_signal():
    engine = FirstWavePullbackV1()
    panels = wave_panels()
    expected = engine.compute(panels, {"mainline_mode": "none"})
    future_index = "2024-02-12"
    extended = {
        field: pd.concat(
            [frame, pd.DataFrame({"300001": [100.0]}, index=[future_index])]
        )
        for field, frame in panels.items()
    }
    actual = engine.compute(extended, {"mainline_mode": "none"})
    signal_day = panels["close"].index[25]
    assert actual.signals.at[signal_day, "300001"] == expected.signals.at[signal_day, "300001"]
    assert actual.factors["D2动态MA5"].at[signal_day, "300001"] == pytest.approx(
        expected.factors["D2动态MA5"].at[signal_day, "300001"]
    )


def test_first_wave_strategy_rejects_unknown_mainline_mode():
    with pytest.raises(StrategyError, match="mainline_mode"):
        FirstWavePullbackV1().compute(wave_panels(), {"mainline_mode": "theme"})


def _mixed_panels() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(13579)
    rows, stocks = 100, 96
    close = 10 * np.exp(np.cumsum(rng.normal(0, 0.012, (rows, stocks)), axis=0))
    volume = rng.lognormal(5, 0.5, (rows, stocks))
    close[:, :12] = 10.0
    volume[:, :12] = 100.0
    wave = wave_panels()
    for field, target in (("close", close), ("volume", volume)):
        target[41:68, :12] = wave[field].to_numpy()
    high, low = close + 0.05, close - 0.05
    # Exercise the exact volume threshold, a rejected threshold and missing bars.
    volume[63, 8] = 200  # D0/D0-1 == 2
    volume[65, 8] = 400 * 2 / 3
    volume[65, 9] = 400 * 2 / 3 + 0.01
    volume[63, 10] = np.nan
    close[64, 11] = np.nan
    volume[30, 20] = 0
    high[30, 21] = np.inf
    index = pd.bdate_range("2024-01-02", periods=rows).strftime("%Y-%m-%d")
    columns = [f"{k:06d}" for k in range(stocks)]
    return {
        name: pd.DataFrame(values, index=index, columns=columns)
        for name, values in {
            "open": close - 0.02, "high": high, "low": low,
            "close": close, "volume": volume,
        }.items()
    }


def _original_panel_scan(close, high, low, volume, index, codes, positions, config):
    # Reference the original per-stock rolling preparation and chronological scan.
    for position in positions:
        bars = pd.DataFrame(
            {"close": close[:, position], "high": high[:, position],
             "low": low[:, position], "volume": volume[:, position], "factor": 1.0},
            index=index,
        )
        yield position, detect_first_waves(bars, code=codes[position], config=config)


def test_batched_wave_scans_match_per_stock_scans_across_chunks():
    panels = _mixed_panels()
    arrays = {
        name: np.tile(panels[name].to_numpy(dtype=float), (1, 6))
        for name in ("close", "high", "low", "volume")
    }
    positions = np.arange(arrays["close"].shape[1])
    codes = [f"{position:06d}" for position in positions]
    args = (arrays["close"], arrays["high"], arrays["low"], arrays["volume"],
            panels["close"].index, codes, positions, FirstWaveConfig())
    actual = dict(_detect_first_waves_panel(*args))
    expected = dict(_original_panel_scan(*args))
    for position, waves in expected.items():
        assert actual.get(position, []) == waves
    statuses = {wave["status"] for waves in expected.values() for wave in waves}
    assert {"setup_ready", "adjustment_volume", "interrupted_wave"} <= statuses


@pytest.mark.parametrize("mode", ["none", "price_resonance_proxy"])
def test_batched_strategy_matches_original_all_stock_scan(monkeypatch, mode):
    panels = _mixed_panels()
    actual = FirstWavePullbackV1().compute(panels, {"mainline_mode": mode})
    monkeypatch.setattr(
        strategy_module, "_potential_wave_columns",
        lambda close, volume, config: np.arange(close.shape[1]),
    )
    monkeypatch.setattr(strategy_module, "_detect_first_waves_panel", _original_panel_scan)
    expected = FirstWavePullbackV1().compute(panels, {"mainline_mode": mode})

    assert actual.signals.to_numpy().sum() > 0
    assert actual.signals.iloc[66, 8]
    assert not actual.signals.iloc[66, 9]
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    assert actual.factors.keys() == expected.factors.keys()
    for name in actual.factors:
        pd.testing.assert_frame_equal(actual.factors[name], expected.factors[name], check_exact=True)


def test_batched_strategy_remains_prefix_causal_with_mainline():
    panels = _mixed_panels()
    prefix = {name: frame.iloc[:75] for name, frame in panels.items()}
    expected = FirstWavePullbackV1().compute(prefix)
    actual = FirstWavePullbackV1().compute(panels)
    pd.testing.assert_frame_equal(actual.signals.iloc[:75], expected.signals, check_exact=True)
    for name in actual.factors:
        pd.testing.assert_frame_equal(actual.factors[name].iloc[:75], expected.factors[name], check_exact=True)
