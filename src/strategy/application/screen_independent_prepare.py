"""Bind the bounded independent executor to the ordinary daily screen policy."""
from __future__ import annotations

from typing import Any

from src.market import resolve_universe
from src.strategy.application.compute_runtime import _SCOPE
from src.strategy.application.independent_screen import IndependentRequest, prepare_independent_range
from src.strategy.domain.base import StrategyError


def independent_inputs(store: Any, engine: Any, params: dict, *, day: str,
                       start: str, end: str, resolved: Any, bars: int,
                       adjust: str, min_bars: int, codes: Any, universe: Any,
                       skip_safety: bool, on_progress=None):
    scope = _SCOPE.get()
    if scope is None or not scope.refresh():
        raise StrategyError("分批选股需要独立且有效的任务读取范围")
    days = list(scope.days) if day in scope.days else [day]
    key = (id(engine), str(getattr(engine, "strategy_revision", "")), tuple(days), repr(params), bars, adjust, min_bars,
           tuple(codes or ()), repr(universe), skip_safety)
    prepared = scope.prepared.get(key)
    if prepared is None:
        requests = []
        for target in days:
            if target == day:
                daily, first, last = resolved, start, end
            else:
                daily = resolve_universe(store, universe, codes=codes, as_of=target,
                                         skip_safety=skip_safety)
                calendar = store.trading_days(end=target)
                if not calendar:
                    raise StrategyError("行情仓没有任何交易日数据，请先执行同步")
                first = calendar[0] if getattr(engine, "requires_full_history", False) else calendar[max(0, len(calendar) - bars)]
                last = calendar[-1]
            requests.append(IndependentRequest(target, first, last, daily.codes, min_bars, adjust))
        # Split the existing result budget between certified projected daily
        # outputs and exact-input audit memoization, rather than retain history.
        projection_budget = scope.independent_budget
        if projection_budget is None:
            projection_budget = max(1, scope.max_bytes // 2)
            scope.independent_budget = projection_budget
        scope.max_bytes = projection_budget
        while scope.results and scope.bytes_used > projection_budget:
            scope._drop(next(iter(scope.results)))
        scope.prepared.clear()
        certified_version = scope.version
        prepared = prepare_independent_range(store, engine, requests, params,
                                             max_result_bytes=projection_budget,
                                             on_progress=on_progress)
        if not scope.refresh() or scope.version != certified_version:
            raise StrategyError("行情版本在分批选股结束时发生变化，请重新执行")
        scope.prepared[key] = prepared
        scope.engines[id(engine)] = engine
    return prepared[day]
