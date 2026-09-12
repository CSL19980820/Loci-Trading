"""HHV/LLV 使用原 pandas Cython 极值内核，含符号位的严格回归。"""

import numpy as np
import pandas as pd
import pytest

from src.formula import HHV, LLV
from src.formula.domain import functions


def assert_same(actual, expected) -> None:
    compare = (
        pd.testing.assert_frame_equal
        if isinstance(expected, pd.DataFrame)
        else pd.testing.assert_series_equal
    )
    compare(actual, expected, check_exact=True)
    if expected.to_numpy().dtype == np.dtype(float):
        np.testing.assert_array_equal(
            actual.to_numpy().view(np.uint64), expected.to_numpy().view(np.uint64)
        )


def reference(values, periods, name) -> pd.Series | pd.DataFrame:
    return (
        getattr(values, f"cum{name}")()
        if periods == 0 else getattr(values.rolling(periods), name)()
    )


@pytest.mark.parametrize("function,name", [(HHV, "max"), (LLV, "min")])
@pytest.mark.parametrize("periods", [0, 1, 2, 7, 60, 441, 442, 1000, np.int64(5)])
@pytest.mark.parametrize("rows,cols", [(0, 2), (1, 3), (441, 1), (441, 263)])
def test_panel_and_series_match_pandas_bitwise(function, name, periods, rows, cols) -> None:
    rng = np.random.default_rng(915)
    panel = pd.DataFrame(
        rng.normal(size=(rows, cols)),
        index=pd.date_range("2026-01-01", periods=rows, name="date"),
        columns=pd.Index([f"code{i // 2}" for i in range(cols)], name="code"),
    )
    if rows > 3:
        panel.iloc[1] = np.nan
        panel.iloc[3] = np.inf
    for values in (panel, panel.iloc[:, 0], panel.iloc[::-2, ::-1]):
        original = values.copy(deep=True)
        assert_same(function(values, periods), reference(values, periods, name))
        assert_same(values, original)


@pytest.mark.parametrize("function,name", [(HHV, "max"), (LLV, "min")])
@pytest.mark.parametrize("periods", [0, 1, 2, 3, 5, 20, 0.0, False])
@pytest.mark.parametrize("values", [
    pd.Series([0., -0., 0., -0., 0., -0.]),
    pd.Series([7., 7., 7., 7., 7., 7.]),
    pd.Series([np.nan, np.inf, 3., 4., 5., -np.inf, 6., 7., np.nan]),
    pd.Series([1, 2, 3], dtype="int64"),
    pd.Series([True, False, True]),
    pd.Series([1., 2., 3.], dtype="float32"),
    pd.Series([1., pd.NA, 3.], dtype="Float64"),
    pd.DataFrame({"a": [1., 2.], "b": [1, 2]}),
    pd.DataFrame(index=pd.Index(["a", "b"], name="date")),
])
def test_boundaries_cumulative_and_dtype_fallback(function, name, periods, values) -> None:
    expected = reference(values, periods, name)
    assert_same(function(values, periods), expected)
    for end in range(1, len(values) + 1):
        assert_same(function(values.iloc[:end], periods), expected.iloc[:end])


@pytest.mark.parametrize("function,name", [(HHV, "max"), (LLV, "min")])
@pytest.mark.parametrize("periods", [-1, True, np.bool_(True), 1., 1.5, None, "3"])
def test_invalid_periods_keep_original_error(function, name, periods) -> None:
    values = pd.Series([1., 2., 3.])
    with pytest.raises(Exception) as before:
        reference(values, periods, name)
    with pytest.raises(type(before.value)) as after:
        function(values, periods)
    assert str(after.value) == str(before.value)


@pytest.mark.parametrize("function,name", [(HHV, "max"), (LLV, "min")])
@pytest.mark.parametrize("failure", ["missing", "signature", "indexer"])
def test_private_api_changes_fall_back(function, name, failure, monkeypatch) -> None:
    def incompatible(*args, **kwargs) -> None:
        raise TypeError("changed private API")
    if failure == "indexer":
        monkeypatch.setattr(functions, "_FixedWindowIndexer", incompatible)
    else:
        monkeypatch.setattr(functions, f"_roll_{name}", None if failure == "missing" else incompatible)
    values = pd.Series([1., 2., 3., np.inf, 5.])
    assert_same(function(values, 2), reference(values, 2, name))
