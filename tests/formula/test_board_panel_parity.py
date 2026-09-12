"""比例面板只替换构造方式，板块和名称优先级继续由原函数决定。"""

import numpy as np
import pandas as pd
import pytest

from src.formula.domain.board import limit_ratio_for, limit_ratio_panel


def reference(close, names=None) -> pd.DataFrame:
    lookup = names or {}
    ratios = [limit_ratio_for(str(code), lookup.get(str(code), "")) for code in close.columns]
    row = pd.Series(ratios, index=close.columns, dtype=float)
    return pd.DataFrame(
        [row.to_numpy()] * len(close.index), index=close.index, columns=close.columns
    )


@pytest.mark.parametrize("rows", [0, 1, 3, 120, 441])
@pytest.mark.parametrize("names", [None, {}, {
    "600001": "*ST测试", "300001": "st创业板", "688001": "ST科创",
    "830001": "ST北交", " 000001 ": "st空格", "000001": "ST主板",
}])
@pytest.mark.parametrize("columns", [
    pd.Index([], name="code"),
    pd.Index(["600001", "000001", "300001", "301001", "688001", "689001", "830001", "430001", "920001"], name="code"),
    pd.Index(["600001", "600001", " 000001 ", 300001, "invalid", None], name="code"),
])
def test_broadcast_matches_original_for_shapes_labels_and_names(rows, names, columns) -> None:
    close = pd.DataFrame(
        np.full((rows, len(columns)), np.nan),
        index=pd.date_range("2020-08-20", periods=rows, name="date"),
        columns=columns,
    )
    expected = reference(close, names)
    actual = limit_ratio_panel(close, names)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    if rows and len(columns):
        np.testing.assert_array_equal(
            actual.to_numpy().view(np.uint64), expected.to_numpy().view(np.uint64)
        )
    assert close.isna().all().all()


def test_board_priority_and_row_mutation_stay_independent() -> None:
    close = pd.DataFrame(10., index=["2020-08-21", "2020-08-24"],
                         columns=["600001", "300001", "688001", "830001"])
    names = {code: "*ST测试" for code in close.columns}
    result = limit_ratio_panel(close, names)
    np.testing.assert_array_equal(result.to_numpy(), [[.05, .2, .2, .3], [.05, .2, .2, .3]])
    # 广播视图不可直接返回：一行修改不得污染其他行或下一次调用。
    result.iloc[0, 0] = 0.7
    assert result.iloc[1, 0] == .05
    assert limit_ratio_panel(close, names).iloc[0, 0] == .05
    assert close.eq(10.).all().all()


def test_duplicate_dates_and_multiindex_columns_match_original() -> None:
    close = pd.DataFrame(
        10., index=pd.Index(["a", "a", "b"], name="date"),
        columns=pd.MultiIndex.from_tuples([("600001", "a"), ("300001", "b")]),
    )
    pd.testing.assert_frame_equal(limit_ratio_panel(close), reference(close), check_exact=True)
