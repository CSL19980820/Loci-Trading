"""杨氏战法的市场宽度、弱市分流和并列排序。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.yangshi_tail import YangshiTailPickerV1


@pytest.fixture
def panels():
    days = pd.Index([f"2026-01-{day:02d}" for day in range(5, 11)], name="trade_date")
    codes = pd.Index(["600001", "000002", "300001", "688001", "830001"], name="code")
    close = pd.DataFrame([
        [10.0, 10.0, 10.0, 10.0, np.nan],
        [10.2, 10.2, 9.8, 9.8, np.nan],
        [10.404, 10.0, 9.5, 9.4, np.nan],
        [np.nan, np.nan, np.nan, np.nan, np.nan],
        [10.0, 10.0, 10.0, 10.0, 10.0],
        [10.2, 10.2, 9.8, 9.8, 9.8],
    ], index=days, columns=codes)
    return {
        "close": close,
        "high": close * 1.02,
        "low": close * 0.98,
        "volume": pd.DataFrame(5e6, index=days, columns=codes),
        "amount": pd.DataFrame(6e7, index=days, columns=codes),
        "turnover": pd.DataFrame(0.03, index=days, columns=codes),
        "__raw_close": close * 1.1,
    }


def test_breadth_missing_prices_threshold_and_tied_rank(panels):
    result = YangshiTailPickerV1().compute(panels)
    days = panels["close"].index
    codes = panels["close"].columns
    expected = pd.DataFrame({code: [np.nan, 0.5, 0.25, np.nan, np.nan, 0.4]
                             for code in codes}, index=days)
    pd.testing.assert_frame_equal(result.factors["市场上涨家数占比"], expected, check_exact=True)

    assert result.picks_on(days[1]) == ["600001"]
    assert result.watch_picks_on(days[2]) == ["600001"]
    assert result.picks_on(days[5]) == ["600001"]  # 0.4 达到阈值；并列按面板顺序取第一只
    assert not result.signals.loc[days[[0, 2, 3, 4]]].to_numpy().any()
    assert not result.watch_signals.loc[days[[0, 1, 3, 4, 5]]].to_numpy().any()


def test_breadth_gate_can_be_disabled_without_changing_ranking(panels):
    result = YangshiTailPickerV1().compute(panels, {"weak_breadth_skip": None, "top_n": 0})
    days = panels["close"].index
    for position in (1, 5):
        assert result.signals.columns[result.signals.loc[days[position]]].tolist() == ["600001", "000002"]
    assert result.picks_on(days[2]) == ["600001"]
    assert not result.watch_signals.to_numpy().any()


def test_non_string_columns_keep_existing_breadth_axis(panels):
    numeric = {
        name: frame.set_axis(range(1, 6), axis="columns")
        for name, frame in panels.items()
    }
    result = YangshiTailPickerV1().compute(numeric)
    expected = pd.DataFrame({code: [np.nan, 0.5, 0.25, np.nan, np.nan, 0.4]
                             for code in range(1, 6)}, index=panels["close"].index)
    pd.testing.assert_frame_equal(result.factors["市场上涨家数占比"], expected, check_exact=True)
