"""Bounded column-independent screening with the original daily date axes."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.market import normalize_code, panel_read_window
from src.strategy.application.audit import guard_runtime_strategy
from src.strategy.application.audit_policy import runtime_audit_mode
from src.strategy.application.compute_runtime import (
    computation_scope, compute_result, execution_profile,
)
from src.strategy.domain.base import SignalResult, StrategyError


@dataclass(frozen=True)
class IndependentRequest:
    """A resolved daily input; the caller owns history and universe policy."""

    day: str
    start: str
    end: str
    codes: Sequence[str]
    min_bars: int
    adjust: str = "qfq"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class IndependentScreen:
    result: SignalResult
    # Ordinary required input fields, including requested price adjustment.
    raw_panels: dict[str, pd.DataFrame]
    columns: pd.Index


def _quote_axis(store: Any, codes: tuple[str, ...], start: str, end: str) -> pd.Index:
    """Union before min_bars filtering; never substitute a chunk's date axis."""
    dates: set[str] = set()
    for offset in range(0, len(codes), 900):
        batch = codes[offset:offset + 900]
        rows = store.conn.execute(
            "SELECT DISTINCT trade_date FROM quotes_daily "
            "WHERE trade_date >= ? AND trade_date <= ? AND code IN ("
            + ",".join("?" for _ in batch) + ")",
            [start, end, *batch],
        )
        dates.update(str(row[0]) for row in rows)
    return pd.Index(sorted(dates), name="trade_date")


def _panels(store: Any, fields: tuple[str, ...], codes: tuple[str, ...],
            request: IndependentRequest, axis: pd.Index) -> dict[str, Any]:
    # Adjustment follows the global axis: a suspended chunk can have its last
    # actual quote before an intervening corporate-action factor change.
    loaded = store.load_panel(fields=fields, codes=codes, start=request.start,
                              end=request.end, min_bars=request.min_bars, adjust="none")
    columns = next(iter(loaded.values())).columns if loaded else pd.Index([], name="code")
    panels = {name: loaded.get(name, pd.DataFrame()).reindex(index=axis, columns=columns)
              for name in fields}
    if request.adjust != "none" and len(axis) and len(columns):
        panels = store.adjust_panels(panels, request.adjust)
    for name, value in request.metadata.items():
        if name in fields:
            raise StrategyError(f"元数据不能覆盖行情字段：{name}")
        panels[name] = (value.reindex(index=axis, columns=columns)
                        if isinstance(value, pd.DataFrame) else value)
    return panels


def _share_projection_axes(result: SignalResult, raw: dict[str, pd.DataFrame]) -> None:
    """Share equivalent immutable axes; projected frames retain their own values."""
    frames = [result.signals, *result.factors.values(), *raw.values()]
    if result.watch_signals is not None:
        frames.append(result.watch_signals)
    pools: list[list[pd.Index]] = [[], []]
    for frame in frames:
        for dimension, current in enumerate((frame.index, frame.columns)):
            shared = next((axis for axis in pools[dimension]
                           if axis.dtype == current.dtype and axis.names == current.names
                           and axis.equals(current)), None)
            if shared is None:
                pools[dimension].append(current)
            elif dimension == 0:
                frame.index = shared
            else:
                frame.columns = shared


def _size(frame: pd.DataFrame, seen_axes: set[int] | None = None) -> int:
    values = frame.to_numpy(copy=False)
    data = (values.nbytes if values.dtype.kind in "biufc"
            else int(frame.memory_usage(index=False, deep=True).sum()))
    seen = set() if seen_axes is None else seen_axes
    size = int(data)
    for axis in (frame.index, frame.columns):
        if id(axis) not in seen:
            seen.add(id(axis))
            size += int(axis.memory_usage(deep=True))
    return size


def _result_size(result: SignalResult, raw: dict[str, pd.DataFrame]) -> int:
    frames = [result.signals, *result.factors.values(), *raw.values()]
    if result.watch_signals is not None:
        frames.append(result.watch_signals)
    seen_axes: set[int] = set()
    return 512 + sum(_size(frame, seen_axes) for frame in frames)


def _join(parts: list[IndependentScreen], axis: pd.Index,
          fields: tuple[str, ...], *, signal_rows: int = 3) -> IndependentScreen:
    rows = axis[-3:]
    if not parts:
        empty = pd.DataFrame(index=axis[-signal_rows:], columns=pd.Index([], name="code"), dtype=bool)
        result = SignalResult(empty)
        raw = {name: pd.DataFrame(index=rows, columns=empty.columns, dtype=float) for name in fields}
        _share_projection_axes(result, raw)
        return IndependentScreen(result, raw, raw[fields[0]].columns)
    factors = parts[0].result.factors.keys()
    watch = parts[0].result.watch_signals is not None
    if any(part.result.factors.keys() != factors
           or (part.result.watch_signals is not None) != watch for part in parts):
        raise StrategyError("列独立策略的分批因子或观察信号结构不一致")

    def join(frames: list[pd.DataFrame]) -> pd.DataFrame:
        frame = pd.concat(frames, axis=1)
        return frame.loc[:, sorted(frame.columns)]

    result = SignalResult(
        join([part.result.signals for part in parts]),
        {name: join([part.result.factors[name] for part in parts]) for name in factors},
        join([part.result.watch_signals for part in parts]) if watch else None,
    )
    raw = {name: join([part.raw_panels[name] for part in parts]) for name in fields}
    _share_projection_axes(result, raw)
    return IndependentScreen(result, raw, raw[fields[0]].columns)


def prepare_independent_range(
    store: Any,
    engine: Any,
    requests: Sequence[IndependentRequest],
    params: dict[str, Any] | None = None,
    *,
    chunk_size: int = 128,
    max_panel_cells: int = 4_000_000,
    max_result_bytes: int = 64_000_000,
    max_working_bytes: int = 128_000_000,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, IndependentScreen]:
    """Read once per code batch, keeping each day's real origin and qfq anchor.

    Global axes are queried once per distinct requested code set. Raw read windows
    hold at most max_panel_cells across required fields plus presence; only three
    result/input rows per day survive. The strategy's intermediate arrays remain
    bounded by the chosen code batch rather than the entire market universe.
    """
    profile = execution_profile(engine, params)
    dynamic_validation = runtime_audit_mode(engine, params) == "dynamic"
    if not (profile.pure and profile.causal and profile.column_mode == "independent"
            and profile.origin in {"finite", "sensitive"}):
        raise StrategyError("分批选股需要已声明的纯、因果、列独立策略")
    if min(chunk_size, max_panel_cells, max_result_bytes, max_working_bytes) < 1:
        raise StrategyError("分批选股的内存预算和批大小必须为正数")
    fields = tuple(dict.fromkeys(engine.required_fields()))
    if not fields:
        raise StrategyError("分批选股需要至少一个行情字段")
    estimate = getattr(engine, "working_frames", None)
    working_frames = max(len(fields) + 1, int(estimate()) if callable(estimate) else len(fields) + 8)
    groups: dict[tuple[str, ...], list[IndependentRequest]] = defaultdict(list)
    seen: set[str] = set()
    for request in requests:
        if request.day in seen:
            raise StrategyError(f"分批选股日期重复：{request.day}")
        # day is the caller's lookup key: ordinary screening can target a holiday
        # or a date beyond the latest stored session and then use the last quote.
        if request.start > request.end:
            raise StrategyError(f"分批选股日期越界：{request.day}")
        if request.adjust not in {"none", "qfq", "hfq"} or request.min_bars < 0:
            raise StrategyError("分批选股复权方式或最小K线数非法")
        seen.add(request.day)
        codes = tuple(sorted({normalize_code(code) for code in request.codes}))
        groups[codes].append(request)
    result: dict[str, IndependentScreen] = {}
    used = 0
    conn = store.conn
    version = (conn.total_changes, conn.execute("PRAGMA data_version").fetchone()[0])
    with computation_scope(store, sorted(seen), max_bytes=max_result_bytes):
        for codes, group in groups.items():
            group.sort(key=lambda request: (request.end, request.start, request.day))
            start, end = min(request.start for request in group), max(request.end for request in group)
            union = _quote_axis(store, codes, start, end)
            axes = {request.day: union[(union >= request.start) & (union <= request.end)]
                    for request in group}
            # Budget the union for the read cache, even when each daily panel is smaller.
            width = min(
                chunk_size,
                max_panel_cells // max(1, len(union) * (len(fields) + 1)),
                max_working_bytes // max(1, len(union) * working_frames * 8),
            )
            if codes and len(union) and width < 1:
                raise StrategyError("单股票历史面板超过分批选股内存预算")
            width = max(1, width)
            parts: dict[str, list[IndependentScreen]] = {request.day: [] for request in group}
            for offset in range(0, len(codes), width):
                chunk = codes[offset:offset + width]
                if on_progress is not None:
                    on_progress(f"计算批次 {offset // width + 1}/{(len(codes) + width - 1) // width}"
                                f" · {len(chunk)}只 · {len(group)}日")
                with panel_read_window(store, start=start, end=end, max_cells=max_panel_cells):
                    if dynamic_validation:
                        latest = group[-1]
                        prime = _panels(store, fields, chunk, latest, axes[latest.day])
                        reference = prime[fields[0]]
                        if not reference.empty:
                            dates = sorted({day for axis in axes.values() for day in axis[-3:]})
                            compute_result(engine, prime, params, dates=dates)
                        del prime, reference
                    for request in group:
                        axis = axes[request.day]
                        panels = _panels(store, fields, chunk, request, axis)
                        reference = panels[fields[0]]
                        if reference.empty:
                            continue
                        output = compute_result(engine, panels, params,
                                                dates=list(axis[-3:] if dynamic_validation else axis[-1:]),
                                                reuse=dynamic_validation)
                        guard_runtime_strategy(engine, panels, params=params, baseline=output)
                        raw = {name: panels[name].iloc[-3:].copy() for name in fields}
                        _share_projection_axes(output, raw)
                        size = _result_size(output, raw)
                        if used + size > max_result_bytes:
                            raise StrategyError("分批选股投影结果超过内存预算")
                        used += size
                        parts[request.day].append(IndependentScreen(output, raw, raw[fields[0]].columns))
                        del panels, reference, output, raw
            for request in group:
                result[request.day] = _join(parts.pop(request.day), axes[request.day], fields,
                                            signal_rows=3 if dynamic_validation else 1)
    if (conn.total_changes, conn.execute("PRAGMA data_version").fetchone()[0]) != version:
        raise StrategyError("行情库在分批选股期间发生变化，请重新执行")
    return result


def prepare_independent_day(
    store: Any, engine: Any, request: IndependentRequest,
    params: dict[str, Any] | None = None, **options: Any,
) -> IndependentScreen:
    return prepare_independent_range(store, engine, [request], params, **options)[request.day]
