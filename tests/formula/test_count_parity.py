"""COUNT 的布尔快速路径必须与原 pandas 实现严格一致。"""

import numpy as np
import pandas as pd
import pytest

from src.formula import COUNT, EVERY, EXIST


def reference_count(condition, periods) -> pd.Series | pd.DataFrame:
    flags = condition.astype(float)
    if periods == 0:
        return flags.cumsum()
    return flags.rolling(periods).sum()


def assert_equal(actual, expected) -> None:
    compare = (
        pd.testing.assert_frame_equal
        if isinstance(expected, pd.DataFrame)
        else pd.testing.assert_series_equal
    )
    compare(actual, expected, check_exact=True)


@pytest.mark.parametrize("periods", [0, 1, 2, 7, 60, 120, 121, 1000, np.int64(3)])
@pytest.mark.parametrize("rows,cols", [(0, 2), (1, 3), (120, 1), (120, 263)])
def test_boolean_windows_equal_original_for_panel_and_series(periods, rows, cols) -> None:
    rng = np.random.default_rng(912)
    panel = pd.DataFrame(
        rng.random((rows, cols)) > 0.6,
        index=pd.date_range("2026-01-01", periods=rows, name="date"),
        columns=pd.Index([f"code{i // 2}" for i in range(cols)], name="code"),
    )
    for condition in (panel, panel.iloc[:, 0], panel.iloc[::-2, ::-1]):
        original = condition.copy(deep=True)
        assert_equal(COUNT(condition, periods), reference_count(condition, periods))
        assert_equal(condition, original)


@pytest.mark.parametrize("periods", [0, 1, 2, 5, 20, 0.0, False])
@pytest.mark.parametrize("condition", [
    pd.Series([True, False, True, True], dtype=bool, name="signal"),
    pd.Series([True, pd.NA, False, True], dtype="boolean", name="signal"),
    pd.Series([True, False, True, True], dtype="boolean", name="signal"),
    pd.Series([0, 2, -3, 1], dtype="int64"),
    pd.Series([0.0, np.nan, -2.5, 0.3, np.inf, -np.inf, 1e20, 1e-20]),
    pd.Series(["0", "2", None, "-3"], dtype=object),
    pd.DataFrame({"bool": [True, False], "float": [np.nan, -2.5]}),
    pd.DataFrame(index=pd.Index(["a", "b"], name="date")),
])
def test_special_inputs_preserve_numeric_and_missing_value_contract(condition, periods) -> None:
    assert_equal(COUNT(condition, periods), reference_count(condition, periods))


@pytest.mark.parametrize("periods", [-1, True, np.bool_(True), 1.0, 1.5, None, "3"])
def test_invalid_windows_keep_original_error(periods) -> None:
    condition = pd.Series([True, False, True])
    with pytest.raises(Exception) as old:
        reference_count(condition, periods)
    with pytest.raises(type(old.value)) as new:
        COUNT(condition, periods)
    assert str(new.value) == str(old.value)


def test_window_counts_and_every_exist_do_not_include_future() -> None:
    condition = pd.Series([True, False, True, True, False, False], name="signal")
    assert_equal(COUNT(condition, 3), pd.Series([np.nan, np.nan, 2., 2., 2., 1.], name="signal"))
    for period in (1, 3, 7):
        expected = reference_count(condition, period)
        assert_equal(EVERY(condition, period), expected >= period)
        assert_equal(EXIST(condition, period), expected >= 1)
        for end in range(1, len(condition) + 1):
            assert_equal(COUNT(condition.iloc[:end], period), COUNT(condition, period).iloc[:end])
