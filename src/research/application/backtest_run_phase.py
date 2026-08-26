"""研究回测冻结上下文的准备与 phase 切片。

主用例 ``run_research_backtest`` 留在 ``backtest_run``；本模块只负责
上下文装配、执行面板对齐校验，以及按日期切出 train/OOS phase。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from src.backtest import BacktestConfig, prepare_backtest_context
from src.research.application.backtest_support import membership_mask as _membership_mask
from src.research.domain.temporal import MembershipSnapshot
from src.strategy import StrategyEngine


class ResearchBacktestError(ValueError):
    """研究回测输入、证据门禁或产物持久化失败。"""


def prepare_research_backtest_context(
    store: Any,
    *,
    strategy: str | StrategyEngine,
    start: str,
    end: str,
    params: Mapping[str, Any] | None,
    config: BacktestConfig,
    universe: Mapping[str, Any] | None,
    historical_universe_id: str | None,
    membership_rows: Sequence[MembershipSnapshot],
    historical_codes: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = prepare_backtest_context(
        store,
        strategy,
        start=start,
        end=end,
        params=dict(params or {}),
        config=config,
        codes=list(historical_codes) or None,
        universe=universe,
    )
    mask, summary = _membership_mask(
        context["signals"],
        context["resolved"].codes,
        historical_universe_id=historical_universe_id,
        snapshots=membership_rows,
    )
    context = dict(context)
    context["signals"] = context["signals"].where(mask, False).fillna(False)
    context["universe_control_mask"] = mask
    return context, summary


def _slice_phase_frame(
    value: Any, *, name: str, index: pd.Index, columns: pd.Index, exact: bool
) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise ResearchBacktestError(f"{name} 必须为 DataFrame")
    if value.index.has_duplicates or value.columns.has_duplicates:
        raise ResearchBacktestError(f"{name} 的交易日索引或股票列不能重复")
    if exact and (not value.index.equals(index) or not value.columns.equals(columns)):
        raise ResearchBacktestError(f"{name} 的交易日索引或股票列与 signals 不一致")
    if not exact and (not index.isin(value.index).all() or not columns.isin(value.columns).all()):
        raise ResearchBacktestError(f"{name} 缺少 phase 的交易日索引或股票列")
    return value if exact else value.loc[index, columns].copy()


def assert_execution_alignment(context: Mapping[str, Any]) -> None:
    signals = context.get("signals")
    if not isinstance(signals, pd.DataFrame):
        raise ResearchBacktestError("signals 必须为 DataFrame")
    if signals.index.has_duplicates or signals.columns.has_duplicates:
        raise ResearchBacktestError("signals 的交易日索引或股票列不能重复")
    index, columns = signals.index, signals.columns
    for name, panels in (
        ("panels", context.get("panels")),
        ("execution_panels", context.get("execution_panels", context.get("panels"))),
    ):
        if not isinstance(panels, Mapping):
            raise ResearchBacktestError(f"{name} 必须为面板映射")
        for field, panel in panels.items():
            if isinstance(panel, pd.DataFrame):
                _slice_phase_frame(
                    panel,
                    name=f"{name}.{field}",
                    index=index,
                    columns=columns,
                    exact=True,
                )
    for name in ("entry_price_panel", "universe_control_mask"):
        value = context.get(name)
        if value is not None:
            _slice_phase_frame(value, name=name, index=index, columns=columns, exact=True)
    benchmark = context.get("benchmark_close")
    if benchmark is not None and (
        not isinstance(benchmark, pd.Series)
        or benchmark.index.has_duplicates
        or not benchmark.index.equals(signals.index)
    ):
        raise ResearchBacktestError("benchmark_close 的交易日索引与 signals 不一致")


def slice_research_backtest_phase(context: Mapping[str, Any], start: str, end: str) -> dict[str, Any]:
    """从同一冻结上下文切出 phase；严禁按日期重新读取 MarketStore。"""
    phase = dict(context)
    signals = context.get("signals")
    if not isinstance(signals, pd.DataFrame):
        raise ResearchBacktestError("signals 必须为 DataFrame")
    phase_signals = signals.loc[(signals.index >= start) & (signals.index <= end)].copy()
    for name, panels in (
        ("panels", context.get("panels")),
        ("execution_panels", context.get("execution_panels", context.get("panels"))),
    ):
        if not isinstance(panels, Mapping):
            raise ResearchBacktestError(f"{name} 必须为面板映射")
        phase[name] = {
            field: (
                _slice_phase_frame(
                    panel,
                    name=f"{name}.{field}",
                    index=phase_signals.index,
                    columns=phase_signals.columns,
                    exact=False,
                )
                if isinstance(panel, pd.DataFrame)
                else panel
            )
            for field, panel in panels.items()
        }
    for name in ("entry_price_panel", "universe_control_mask"):
        value = context.get(name)
        if value is not None:
            phase[name] = _slice_phase_frame(
                value,
                name=name,
                index=phase_signals.index,
                columns=phase_signals.columns,
                exact=False,
            )
    benchmark = context.get("benchmark_close")
    if benchmark is not None:
        if not isinstance(benchmark, pd.Series) or not phase_signals.index.isin(benchmark.index).all():
            raise ResearchBacktestError("benchmark_close 缺少 phase 的交易日索引")
        phase["benchmark_close"] = benchmark.loc[phase_signals.index].copy()
    phase.update(signals=phase_signals, start=start, end=end)
    assert_execution_alignment(phase)
    return phase


__all__ = [
    "ResearchBacktestError",
    "assert_execution_alignment",
    "prepare_research_backtest_context",
    "slice_research_backtest_phase",
]
