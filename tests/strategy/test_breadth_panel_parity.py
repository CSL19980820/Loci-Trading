"""市场宽度广播保留原Series字典的索引、列、空值与扩展dtype。"""
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.qianlong import QianlongCloseePickerV3, _QianlongCore
from src.strategy.domain.base import SignalResult


@pytest.mark.parametrize("dtype", ["float64", "Float64"])
@pytest.mark.parametrize("rows", [0, 1, 5])
@pytest.mark.parametrize("named", [False, True])
def test_breadth_matches_original_dictionary(dtype: str, rows: int, named: bool) -> None:
    index = pd.Index([f"day-{i}" for i in range(rows)], name="trade_date" if named else None)
    columns = pd.Index(["600003", "300001", "000002"], name="code" if named else None)
    close = pd.DataFrame(np.arange(rows * 3).reshape(rows, 3) + 10, index=index, columns=columns, dtype=dtype)
    if rows > 2:
        close.iloc[2, 0] = np.nan
        close.iloc[3, 1] = 8
    turnover = pd.DataFrame(.05, index=index, columns=columns)
    core = SignalResult(signals=close.notna(), factors={"白线贴近度": close * .01})
    previous = close.shift(1)
    valid = close.notna() & previous.notna()
    count = valid.sum(axis=1)
    breadth = ((close > previous) & valid).sum(axis=1).div(count.where(count > 0))
    expected = pd.DataFrame({code: breadth for code in close.columns}, index=close.index)
    with patch.object(_QianlongCore, "compute", return_value=core):
        result = QianlongCloseePickerV3().compute({"close": close, "turnover": turnover})
    pd.testing.assert_frame_equal(result.factors["市场上涨家数占比"], expected, check_exact=True)
