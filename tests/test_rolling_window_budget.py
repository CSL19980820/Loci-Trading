"""Window tiling bounds real 3-D kernel work without changing old reductions."""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import pandas as pd
import pytest

from src.formula.domain import functions


def old_window_result(frame, periods, name):
    """The original unbounded view and exact per-window kernel math."""
    matrix = np.asarray(frame, dtype=float)
    single = matrix.ndim == 1
    if single:
        matrix = matrix[:, None]
    out = np.full(matrix.shape, np.nan, dtype=float)
    if periods > 0 and len(matrix) >= periods and matrix.shape[1]:
        windows = sliding_window_view(matrix, periods, axis=0)
        if name == "AVEDEV":
            deviations = windows - windows.mean(axis=2, keepdims=True)
            np.abs(deviations, out=deviations)
            computed = deviations.mean(axis=2)
        else:
            reversed_windows = windows[..., ::-1]
            missing = np.isnan(reversed_windows)
            safe = np.where(missing, -np.inf if name == "HHVBARS" else np.inf, reversed_windows)
            computed = (np.argmax if name == "HHVBARS" else np.argmin)(safe, axis=2).astype(float)
            computed[missing.all(axis=2)] = np.nan
        out[periods - 1:] = computed
    if single:
        return pd.Series(out[:, 0], index=frame.index, name=frame.name)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def observe_real_kernel_windows(monkeypatch, *, budget, column_width=256):
    original = functions._rolling_column_chunks
    shapes = []
    monkeypatch.setattr(functions, "_MAX_WINDOW_CELLS", budget)
    monkeypatch.setattr(functions, "_COLUMN_CHUNK", column_width)
    def chunks(matrix, periods, kernel):
        def observe(windows):
            shapes.append(windows.shape)
            assert windows.size <= budget
            return kernel(windows)
        return original(matrix, periods, observe)
    monkeypatch.setattr(functions, "_rolling_column_chunks", chunks)
    return shapes


@pytest.mark.parametrize("name", ["AVEDEV", "HHVBARS", "LLVBARS"])
@pytest.mark.parametrize("periods", [1, 3, 20, 21])
@pytest.mark.parametrize("series", [False, True])
def test_tiled_windows_are_bit_exact_at_nan_tie_prefix_and_short_history_boundaries(
    monkeypatch, name, periods, series,
):
    rng = np.random.default_rng(782)
    values = rng.normal(size=(20, 7))
    values[:4, 0] = np.nan
    values[7:11, 1] = np.nan
    values[4:10, 2] = 3  # equal extreme values keep the nearest/current tie
    values[:, 3] = np.nan
    frame = pd.DataFrame(values, index=pd.Index(range(20), name="day"),
                         columns=pd.Index(list("abcdefg"), name="code"))
    if series:
        frame = frame["a"]
    expected = old_window_result(frame, periods, name)
    original = frame.copy(deep=True)
    shapes = observe_real_kernel_windows(monkeypatch, budget=32, column_width=3)
    observed = getattr(functions, name)(frame, periods)
    compare = pd.testing.assert_series_equal if series else pd.testing.assert_frame_equal
    compare(observed, expected, check_exact=True)
    compare(frame, original, check_exact=True)
    if periods <= len(frame):
        assert shapes and all(shape[2] == periods and np.prod(shape) <= 32 for shape in shapes)


@pytest.mark.parametrize("name", ["AVEDEV", "HHVBARS", "LLVBARS"])
def test_long_history_maximum_dsl_period_has_bounded_real_window_allocations(monkeypatch, name):
    # The former single 3001x4x1000 work array held 12 million cells (~96 MiB
    # before the extreme's extra missing mask); each actual kernel now gets <=16 MiB.
    frame = pd.DataFrame(np.random.default_rng(41).normal(size=(4000, 4)))
    frame.iloc[1001:1005, 1] = np.nan
    expected = old_window_result(frame, 1000, name)
    shapes = observe_real_kernel_windows(monkeypatch, budget=2_000_000)
    observed = getattr(functions, name)(frame, 1000)
    pd.testing.assert_frame_equal(observed, expected, check_exact=True)
    assert len(shapes) > 1
    assert max(np.prod(shape) for shape in shapes) <= 2_000_000
    assert max(shape[0] for shape in shapes) < len(frame) - 1000 + 1


def test_zero_period_empty_axes_and_public_error_contract_remain_unchanged(monkeypatch):
    observe_real_kernel_windows(monkeypatch, budget=32)
    frame = pd.DataFrame(np.ones((4, 3)))
    pd.testing.assert_frame_equal(functions.AVEDEV(frame, 0), frame * np.nan, check_exact=True)
    for function in (functions.AVEDEV, functions.HHVBARS, functions.LLVBARS):
        for empty in (frame.iloc[:0], frame.iloc[:, :0], pd.Series([], dtype=float)):
            expected = old_window_result(empty, 2, function.__name__)
            compare = pd.testing.assert_series_equal if isinstance(empty, pd.Series) else pd.testing.assert_frame_equal
            compare(function(empty, 2), expected, check_exact=True)
        with pytest.raises(ValueError):
            function(frame, -1)
    for function in (functions.HHVBARS, functions.LLVBARS):
        with pytest.raises(ValueError):
            function(frame, 0)
