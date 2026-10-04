"""受控内建的全部因子因果性、真实有限窗口和横截面执行契约。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.qianlong import QianlongCloseePickerV3
from src.strategy.application.tail_resonance import SanyuanTailResonance
from src.strategy.application.yangshi_tail import YangshiTailPickerV1


ENGINES = (QianlongCloseePickerV3, SanyuanTailResonance, YangshiTailPickerV1)


def _panels(seed=17, days=240):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2025-01-02", periods=days).strftime("%Y-%m-%d")
    columns = pd.Index(["600001", "000002", "300001", "688001", "830001", "600002",
                        "002003", "301002", "600003", "000001", "003001", "601003"], name="code")
    raw = 9.5 * np.exp(np.cumsum(rng.normal(.0003, .018, (days, len(columns))), axis=0))
    close = raw * .93
    open_ = close * (1 + rng.normal(0, .006, close.shape))
    volume = rng.uniform(4e6, 12e6, close.shape)
    values = {"close": close, "open": open_, "high": np.maximum(close, open_) * 1.012,
              "low": np.minimum(close, open_) * .988, "volume": volume,
              "turnover": rng.uniform(.025, .13, close.shape),
              "amount": volume * raw, "outstanding_share": rng.uniform(5e7, 2.3e8, close.shape),
              "__raw_close": raw}
    panels = {key: pd.DataFrame(value, index=index, columns=columns) for key, value in values.items()}
    panels["__instrument_names__"] = {code: "ST测试" if code == "600002" else "测试证券"
                                       for code in columns}
    for key, frame in panels.items():
        if isinstance(frame, pd.DataFrame):
            frame.iloc[:7, 0] = np.nan
            frame.iloc[170:172, 3] = np.nan
    return panels


def _slice(panels, start=None, end=None):
    return {key: value.loc[start:end].copy() if isinstance(value, pd.DataFrame) else value
            for key, value in panels.items()}


def _assert_rows_equal(full, partial, dates, *, exact=True):
    pd.testing.assert_frame_equal(full.signals.loc[dates], partial.signals.loc[dates])
    if full.watch_signals is not None:
        pd.testing.assert_frame_equal(full.watch_signals.loc[dates], partial.watch_signals.loc[dates])
    assert full.factors.keys() == partial.factors.keys()
    for name in full.factors:
        pd.testing.assert_frame_equal(full.factors[name].loc[dates], partial.factors[name].loc[dates],
                                      check_exact=exact, rtol=1e-12, atol=1e-12, obj=name)


@pytest.mark.parametrize("engine_type", ENGINES)
def test_all_twenty_two_prefixes_preserve_signals_watch_and_every_factor(engine_type):
    engine = engine_type()
    panels = _panels(seed=7)
    full = engine.compute(panels)
    assert full.signals.to_numpy().any() or full.watch_signals.to_numpy().any()
    for day in panels["close"].index[-22:]:
        partial = engine.compute(_slice(panels, end=day))
        _assert_rows_equal(full, partial, [day])


@pytest.mark.parametrize("engine_type", ENGINES)
def test_future_price_and_metadata_dataframes_cannot_change_earlier_factor_values(engine_type):
    engine = engine_type()
    panels = _panels()
    cutoff = panels["close"].index[-24]
    before = engine.compute(panels)
    future = _slice(panels)
    for key, frame in future.items():
        if isinstance(frame, pd.DataFrame):
            frame.loc[frame.index > cutoff] *= 3.7
    changed = engine.compute(future)
    _assert_rows_equal(before, changed, list(panels["close"].index[panels["close"].index <= cutoff]))


@pytest.mark.parametrize("engine_type,params,window", [
    (QianlongCloseePickerV3, None, 41),
    (QianlongCloseePickerV3, {"death_lookback": 1, "below_window": 2}, 27),
    (QianlongCloseePickerV3, {"death_lookback": 35, "below_window": 70}, 90),
    (YangshiTailPickerV1, None, 41),
])
def test_finite_profiles_include_true_dependence_for_each_different_origin_suffix(engine_type, params, window):
    engine = engine_type()
    profile = engine.execution_profile(params)
    assert profile.pure and profile.causal
    assert profile.column_mode == "coupled"
    assert profile.origin == "finite" and profile.lookback_bars == window
    assert profile.metadata_fields == ("__raw_close", "__instrument_names__")
    panels = _panels(seed=29)
    full = engine.compute(panels, params)
    for position in range(len(panels["close"]) - 22, len(panels["close"])):
        origin, day = panels["close"].index[position - window + 1], panels["close"].index[position]
        suffix = engine.compute(_slice(panels, start=origin, end=day), params)
        # pandas' compensated rolling sums can differ in their last bits with
        # a new origin. Boolean decisions stay exact; all values stay within
        # the same numerical tolerance used for the underlying rolling API.
        _assert_rows_equal(full, suffix, [day], exact=False)


@pytest.mark.parametrize("params", [{"death_lookback": 0}, {"below_window": 0}])
def test_cumulative_qianlong_windows_are_origin_sensitive(params):
    profile = QianlongCloseePickerV3().execution_profile(params)
    assert profile.pure and profile.causal
    assert profile.column_mode == "coupled"
    assert profile.origin == "sensitive" and profile.lookback_bars is None


def test_resonance_recursive_ema_keeps_actual_origin_and_existing_warmup():
    engine = SanyuanTailResonance()
    profile = engine.execution_profile()
    assert profile.pure and profile.causal
    assert profile.column_mode == "coupled"
    assert profile.origin == "sensitive" and profile.lookback_bars is None
    assert profile.metadata_fields == ("__raw_close",)
    assert engine.warmup_bars == 100
