"""把"行情仓 + 策略 + 回测器"接成一条命令能跑完的链路。

单独一层的原因和 screener 一样：加载窗口、基准对齐、参数校验这些事
每个策略都要做一遍，散落在各处迟早会出现口径不一致的两份实现。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from src.market.store import MarketStore
from src.strategies.base import StrategyEngine, StrategyError, get, merge_params


def backtest_strategy(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    config: BacktestConfig | None = None,
    codes: list[str] | None = None,
    adjust: str = "qfq",
) -> BacktestResult:
    """在指定区间对某个策略跑信号级回测。

    行情统一用前复权：不复权的历史价格在除权处会出现断崖，算出来的
    "涨了 50%" 可能只是送股，不是真的赚了。
    """
    engine = get(strategy) if isinstance(strategy, str) else strategy
    resolved_params = merge_params(engine, params)
    cfg = config or BacktestConfig()

    # 回测要覆盖到 end 之后的持有期，否则最后一批信号会因为"数据到头"
    # 被记成 data_end，混进统计里拉低结论。这里多取一段尾巴。
    tail = max(cfg.hold_days + 5, 10)
    days = store.trading_days()
    if not days:
        raise StrategyError("行情仓为空，请先执行 python market.py sync")

    # 起点要往前多取指标窗口，否则区间头部的信号算不出来。
    warmup = engine.min_bars() + 20
    load_start, load_end = _expand_range(days, start, end, warmup, tail)

    fields = tuple(dict.fromkeys((*engine.required_fields(), "open", "high", "low", "close", "volume")))
    panels = store.load_panel(
        fields=fields,
        codes=codes,
        start=load_start,
        end=load_end,
        adjust=adjust,
        min_bars=engine.min_bars(),
    )
    if panels["close"].empty:
        raise StrategyError("所选区间没有行情数据")

    signals = engine.compute(panels, resolved_params).signals

    # 只保留落在用户指定区间内的信号；预热段与尾巴只用来算指标和结果。
    if start:
        signals = signals[signals.index >= start]
    if end:
        signals = signals[signals.index <= end]
    signals = signals.reindex(panels["close"].index).fillna(False)

    benchmark_close = None
    if cfg.benchmark:
        benchmark_close = _load_benchmark(store, cfg.benchmark, panels["close"].index)

    result = run_backtest(
        signals,
        panels,
        entry_timing=engine.entry_timing,
        config=cfg,
        strategy_slug=engine.slug,
        benchmark_close=benchmark_close,
    )
    result.config["params"] = resolved_params
    result.config["range"] = {"start": start or load_start, "end": end or load_end}
    return result


def _expand_range(
    days: list[str], start: str | None, end: str | None, warmup: int, tail: int
) -> tuple[str, str]:
    start_pos = 0 if start is None else _search(days, start)
    end_pos = len(days) - 1 if end is None else _search(days, end)
    return days[max(0, start_pos - warmup)], days[min(len(days) - 1, end_pos + tail)]


def _search(days: list[str], target: str) -> int:
    """找到 >= target 的第一个交易日位置；找不到就退到最后一天。"""
    for index, day in enumerate(days):
        if day >= target:
            return index
    return len(days) - 1


def _load_benchmark(store: MarketStore, code: str, index: pd.Index) -> pd.Series | None:
    """加载基准指数收盘价并对齐到回测的交易日索引。

    基准缺失不该让整个回测失败——那样会因为"忘了同步指数"就得不到任何
    结论。降级为不算超额，并在结果里保持 benchmark_return 为 None。
    """
    frame = store.history(code, adjust="none")
    if frame.empty:
        return None
    series = frame.set_index("trade_date")["close"].astype(float)
    return series.reindex(index).ffill()
