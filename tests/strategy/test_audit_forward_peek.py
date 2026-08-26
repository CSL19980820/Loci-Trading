"""静态审计：next_open 不再整段空转；热路径分片须覆盖尾/中列前视。"""
from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from src.strategy.application.audit import LookAheadError, audit_source, guard_strategy
from src.strategy.application.audit_sampling import (
    iter_guard_panel_shards,
    prepare_guard_panels,
    sample_panel_columns,
)
from src.strategy.domain.base import SignalResult


def test_next_open_warns_on_negative_shift() -> None:
    code = """
class Eng:
    entry_timing = "next_open"
    def compute(self, panels, params=None):
        close = panels["close"]
        return close.shift(-1)
"""
    report = audit_source(code, entry_timing="next_open", strategy="demo")
    checks = [f.check for f in report.findings]
    assert "forward_peek" in checks
    assert any(f.severity == "warn" for f in report.findings if f.check == "forward_peek")


def test_open_still_blocks_bare_close() -> None:
    code = 'x = panels["close"]\n'
    report = audit_source(code, entry_timing="open", strategy="demo")
    assert any(f.check == "intraday_field" and f.severity == "block" for f in report.findings)


def test_close_timing_blocks_same_day_high_low() -> None:
    """尾盘 14:50 决策时全天最高/最低还没定——与公式编译器 close 白名单同口径。"""
    code = 'x = panels["high"] - panels["low"]\n'
    report = audit_source(code, entry_timing="close", strategy="demo")
    blockers = [f for f in report.findings if f.check == "intraday_field"]
    assert blockers and blockers[0].severity == "block"
    assert {item["field"] for item in blockers[0].detail} == {"high", "low"}


def test_close_timing_allows_same_day_close_and_lagged_high() -> None:
    """收盘价在尾盘已基本定型；昨日最高本来就合法，不能误报。"""
    code = 'x = panels["close"] > REF(panels["high"], 1)\n'
    report = audit_source(code, entry_timing="close", strategy="demo")
    assert not report.failed, report.reason()
    assert not [f for f in report.findings if f.check.startswith("intraday_field")]


def test_rolling_wrapper_over_intraday_field_is_reported() -> None:
    """MA(close,5) 的窗口右端就是信号日，9:25 算不出来；公式引擎对此直接报错。"""
    code = 'x = MA(panels["close"], 5)\n'
    report = audit_source(code, entry_timing="open", strategy="demo")
    rolling = [f for f in report.findings if f.check == "intraday_field_rolling"]
    assert rolling and rolling[0].severity == "warn"
    assert rolling[0].detail == [{"field": "close", "line": 1}]


def test_lagged_field_inside_rolling_is_not_reported() -> None:
    code = 'x = MA(REF(panels["close"], 1), 5)\n'
    report = audit_source(code, entry_timing="open", strategy="demo")
    assert not [f for f in report.findings if f.check.startswith("intraday_field")]


class _FixedColumnPeekEngine:
    """只偷看指定列名——证明分片全覆盖，而非相对 columns[-1] 的巧合命中。"""

    entry_timing = "next_open"
    name = "定点列前视"

    def __init__(self, target: str) -> None:
        self.slug = f"peek-{target}"
        self._target = target

    def min_bars(self) -> int:
        return 2

    def required_fields(self) -> tuple[str, ...]:
        return ("close",)

    def compute(self, panels, params=None):  # noqa: ANN001
        close = panels["close"]
        signals = pd.DataFrame(False, index=close.index, columns=close.columns)
        if self._target in close.columns:
            signals[self._target] = close[self._target].shift(-1).notna()
        return SignalResult(signals=signals)


def test_sharded_guard_catches_tail_column_forward_peek() -> None:
    cols = [f"c{i:04d}" for i in range(500)]
    target = cols[-1]
    assert target not in cols[:40]
    index = pd.date_range("2024-01-01", periods=40, freq="B")
    panels = {"close": pd.DataFrame({col: range(40) for col in cols}, index=index)}

    with pytest.raises(LookAheadError):
        guard_strategy(_FixedColumnPeekEngine(target), panels)


def test_sharded_guard_catches_middle_column_forward_peek() -> None:
    cols = [f"c{i:04d}" for i in range(500)]
    target = cols[len(cols) // 2]
    assert target not in cols[:40]
    index = pd.date_range("2024-01-01", periods=40, freq="B")
    panels = {"close": pd.DataFrame({col: range(40) for col in cols}, index=index)}

    with pytest.raises(LookAheadError):
        guard_strategy(_FixedColumnPeekEngine(target), panels)


def test_blind_prefix40_would_miss_but_shards_cover() -> None:
    """旧热路径 columns[:40] / hash 前缀会漏检；分片合并覆盖全列。"""
    cols = [f"c{i:04d}" for i in range(500)]
    target = cols[-1]
    old_lex = set(cols[:40])
    old_hash = set(
        sorted(cols, key=lambda c: hashlib.md5(str(c).encode("utf-8")).hexdigest())[:40]
    )
    assert target not in old_lex
    assert target not in old_hash

    panels = {"close": pd.DataFrame({col: 1 for col in cols}, index=[0])}
    covered: set[str] = set()
    for shard in iter_guard_panel_shards(panels, shard_size=200):
        covered.update(str(c) for c in shard["close"].columns)
    assert target in covered
    assert covered == set(cols)


def test_sampled_prepare_still_includes_tail_for_diagnostics() -> None:
    cols = [f"c{i:04d}" for i in range(500)]
    sampled = prepare_guard_panels(
        {"close": pd.DataFrame({col: 1 for col in cols}, index=[0])},
        sample_size=40,
    )
    assert cols[-1] in sampled["close"].columns


def test_old_hash_prefix_would_miss_tail_but_sampling_includes_it() -> None:
    cols = [f"c{i:04d}" for i in range(500)]
    old_prefix = set(
        sorted(cols, key=lambda c: hashlib.md5(str(c).encode("utf-8")).hexdigest())[:40]
    )
    picked = set(sample_panel_columns(cols, sample_size=40))
    assert cols[-1] not in old_prefix
    assert cols[-1] in picked


class _MetaPanelEngine:
    """读元数据面板的最小战法。定义在模块顶层——静态审计要 ``inspect.getsource``，
    函数内的嵌套类取出来是缩进代码块，``ast.parse`` 会直接报 unexpected indent。"""

    slug = "meta-panel-demo"
    entry_timing = "next_open"
    requires_instrument_names = True

    def min_bars(self) -> int:
        return 5

    def compute(self, panels, params=None):  # type: ignore[no-untyped-def]
        frame = panels["close"]
        assert isinstance(panels["__instrument_names__"], dict)
        return SignalResult(signals=frame > 0, factors={"close": frame})


def test_truncation_tolerates_non_dataframe_panel_entries() -> None:
    """面板里混着元数据（``__instrument_names__`` 是 dict），截断不能对它调 ``.empty``。

    声明 ``requires_instrument_names`` 的战法会被注入这个 key；此前 `audit_truncation`
    无差别遍历 ``panels.items()``，任何这样的战法一进选股链路就 AttributeError。
    """
    index = pd.date_range("2026-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
    codes = ["600001", "600002"]
    panels = {
        "close": pd.DataFrame(10.0, index=index, columns=codes),
        "__instrument_names__": {code: f"名称{code}" for code in codes},
    }
    report = guard_strategy(_MetaPanelEngine(), panels)
    assert not report.failed
