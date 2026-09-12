"""MA 复用同一 pandas 内核必须逐位相等，不能以容差掩盖交易信号变化。"""

import numpy as np
import pandas as pd
import pytest

from src.formula import MA
from src.formula.domain import functions


def assert_same(actual, expected) -> None:
    compare = (
        pd.testing.assert_frame_equal
        if isinstance(expected, pd.DataFrame)
        else pd.testing.assert_series_equal
    )
    compare(actual, expected, check_exact=True)
    # check_exact 仍视 +0/-0 相同；内核复用也不应改变其二进制符号。
    np.testing.assert_array_equal(
        actual.to_numpy().view(np.uint64), expected.to_numpy().view(np.uint64)
    )


@pytest.mark.parametrize("periods", [1, 2, 3, 7, 60, 120, 121, 1000, np.int64(5)])
@pytest.mark.parametrize("rows,cols", [(0, 2), (1, 3), (120, 1), (120, 263)])
def test_float_panel_and_series_are_bitwise_identical(periods, rows, cols) -> None:
    rng = np.random.default_rng(913)
    panel = pd.DataFrame(
        rng.normal(size=(rows, cols)) * rng.choice([1e-100, 0.1, 1e100], (rows, cols)),
        index=pd.date_range("2026-01-01", periods=rows, name="date"),
        columns=pd.Index([f"code{i // 2}" for i in range(cols)], name="code"),
    )
    if rows > 3:
        panel.iloc[1] = np.nan
        panel.iloc[3] = np.inf
    for values in (panel, panel.iloc[:, 0], panel.iloc[::-2, ::-1]):
        original = values.copy(deep=True)
        assert_same(MA(values, periods), values.rolling(periods).mean())
        compare = pd.testing.assert_frame_equal if isinstance(values, pd.DataFrame) else pd.testing.assert_series_equal
        compare(values, original, check_exact=True)


@pytest.mark.parametrize("periods", [1, 2, 3, 5, 20])
@pytest.mark.parametrize("values", [
    [0., -0., 0., -0., 0., -0.],
    [7., 7., 7., 7., 7., 7.],
    [1e16, 1., -1e16, 1e-30, 0.1, 0.2, 0.3, -1.],
    [np.nan, np.inf, 3., 4., 5., -np.inf, 6., 7., np.nan],
    [-1e-300, -1e-300, -1e-300, 1e-300, 1e-300, 1e-300],
])
def test_cancellation_missing_values_constant_and_signed_zero(values, periods) -> None:
    series = pd.Series(values, name="close")
    expected = series.rolling(periods).mean()
    assert_same(MA(series, periods), expected)
    for end in range(1, len(series) + 1):
        assert_same(MA(series.iloc[:end], periods), expected.iloc[:end])


@pytest.mark.parametrize("condition", [
    pd.Series([1, 2, 3], dtype="int64"),
    pd.Series([True, False, True]),
    pd.Series([1., 2., 3.], dtype="float32"),
    pd.Series([1., pd.NA, 3.], dtype="Float64"),
    pd.Series(["1", "2", "3"], dtype=object),
    pd.DataFrame({"a": [1., 2.], "b": [1, 2]}),
    pd.DataFrame(index=pd.Index(["a", "b"], name="date")),
])
def test_other_dtypes_and_empty_columns_keep_public_rolling(condition) -> None:
    assert_same(MA(condition, 2), condition.rolling(2).mean())


@pytest.mark.parametrize("periods", [-1, 0, True, np.bool_(True), 1., 1.5, None, "3"])
def test_invalid_periods_keep_old_validation(periods) -> None:
    series = pd.Series([1., 2., 3.])
    def old() -> pd.Series:
        if periods <= 0:
            raise ValueError("MA 的周期必须为正")
        return series.rolling(periods).mean()
    with pytest.raises(Exception) as before:
        old()
    with pytest.raises(type(before.value)) as after:
        MA(series, periods)
    assert str(after.value) == str(before.value)


@pytest.mark.parametrize("failure", ["missing", "signature", "indexer"])
def test_private_api_changes_fall_back_to_public_rolling(monkeypatch, failure) -> None:
    def incompatible(*args, **kwargs) -> None:
        raise TypeError("changed private API")
    if failure == "missing":
        monkeypatch.setattr(functions, "_roll_mean", None)
    elif failure == "signature":
        monkeypatch.setattr(functions, "_roll_mean", incompatible)
    else:
        monkeypatch.setattr(functions, "_FixedWindowIndexer", incompatible)
    series = pd.Series([1., 2., 3., np.inf, 5.])
    assert_same(MA(series, 2), series.rolling(2).mean())
