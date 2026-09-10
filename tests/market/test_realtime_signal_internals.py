"""实时信号引擎内部快路径的等价性钉子。

``_crossed_now`` 与 ``_tail_series`` 都是为了盘中热路径绕开通用实现的特例：
前者跳过 ``CROSS`` 的整列布尔运算，后者跳过 ``pd.concat`` 的索引对齐。
它们省下的是每 tick 每票的固定开销（实测 766ms → 196ms / 500 票 6 规则），
代价是**多了一份必须与通用实现保持一致的语义**。这个文件就是那份保证：
一旦公式引擎的口径变了而这里没跟上，金叉会在盘中静默错报。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.formula.domain.functions import CROSS
from src.market.application.realtime_rules import _crossed_now
from src.market.application.realtime_signals import _tail_series

CODE = "600000"


def test_crossed_now_matches_the_formula_engine_on_random_series() -> None:
    rng = np.random.default_rng(20260909)
    for _ in range(300):
        size = int(rng.integers(1, 12))
    fast = pd.Series(rng.normal(size=size))
    slow = pd.Series(rng.normal(size=size))
    # 让两条线真的有机会交叉，否则随机噪声几乎命不中金叉。
    slow = slow * 0.2 + fast.shift(1).fillna(0.0) * 0.8
    if size >= 3:
        fast.iloc[int(rng.integers(0, size))] = float("nan")
        expected = bool(CROSS(fast, slow).iloc[-1])
        assert _crossed_now(fast, slow) is expected, (list(fast), list(slow))


def test_crossed_now_reads_the_textbook_cases() -> None:
    assert _crossed_now(pd.Series([1.0, 3.0]), pd.Series([2.0, 2.0])) is True
    # 昨日已在上方：今日继续在上方不是「上穿」。
    assert _crossed_now(pd.Series([3.0, 4.0]), pd.Series([2.0, 2.0])) is False
    # 只有一根 bar 时谈不上穿越。
    assert _crossed_now(pd.Series([3.0]), pd.Series([2.0])) is False
    # 相等不算上穿（CROSS 要求今日严格大于）。
    assert _crossed_now(pd.Series([1.0, 2.0]), pd.Series([2.0, 2.0])) is False
    # 昨日恰好相等：CROSS 的口径是「昨日 <=」，等号算穿越前夜。随机浮点几乎不
    # 可能撞出这一格，把 <= 写成 < 的变异只有这条能抓住。
    assert _crossed_now(pd.Series([2.0, 3.0]), pd.Series([2.0, 2.0])) is True
    # 任一边缺值一律不报（面板还没同步到今日的极端情形）。
    assert _crossed_now(pd.Series([1.0, float("nan")]), pd.Series([2.0, 2.0])) is False
    assert _crossed_now(pd.Series([float("nan"), 3.0]), pd.Series([2.0, 2.0])) is False


def test_tail_series_overwrites_todays_bar_instead_of_appending_a_second_one() -> None:
    index = ["2026-08-25", "2026-08-26", "2026-08-27"]
    frame = pd.DataFrame({CODE: [10.0, float("nan"), 12.0]}, index=index)
    # 面板已含今日（收盘后同步过）：实时价覆盖它，不能长出第二根。
    assert list(_tail_series(frame, CODE, "2026-08-27", 13.0)) == [10.0, 13.0]
    # 面板不含今日：追加一根未完成 bar，中间的缺口被丢掉。
    assert list(_tail_series(frame, CODE, "2026-08-28", 14.0)) == [10.0, 12.0, 14.0]


def test_tail_series_degrades_to_the_live_bar_alone() -> None:
    frame = pd.DataFrame({CODE: [10.0]}, index=["2026-08-27"])
    assert list(_tail_series(None, CODE, "2026-08-28", 9.0)) == [9.0]
    assert list(_tail_series(frame, "999999", "2026-08-28", 9.0)) == [9.0]
    assert list(_tail_series(pd.DataFrame(), CODE, "2026-08-28", 9.0)) == [9.0]


def test_tail_series_is_positional_so_rules_can_use_iloc() -> None:
    """规则全部按位置取值；返回日期索引只会让每 tick 多付一次索引对齐。"""
    frame = pd.DataFrame({CODE: [10.0, 11.0]}, index=["2026-08-26", "2026-08-27"])
    out = _tail_series(frame, CODE, "2026-08-28", 12.0)
    assert isinstance(out.index, pd.RangeIndex)
    assert out.iloc[-1] == 12.0
    assert out.dtype == np.float64
