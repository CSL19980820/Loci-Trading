"""把"行情仓 + 策略 + 回测器"接成一条命令能跑完的链路。

单独一层的原因和 screener 一样：加载窗口、基准对齐、参数校验这些事
每个策略都要做一遍，散落在各处迟早会出现口径不一致的两份实现。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import inspect
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.backtest.application.engine import BacktestConfig, BacktestResult, run_backtest
from src.backtest.application.fast_engine import (
    describe_fast_backend,
    fast_backtest_enabled,
    run_backtest_fast,
)
from src.backtest.application.horizon import (
    DEFAULT_HORIZONS,
    HorizonResult,
    attach_instrument_names,
    entry_day_offset,
    run_horizon_backtest,
)
from src.market import MarketStore
from src.market import UniverseError, resolve_universe
from src.strategy.application.catalog import get
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.domain.base import (
    StrategyEngine,
    StrategyError,
    merge_params,
    signal_history_bars,
)

#: Horizon 信号窗最长自然日跨度（约 6 个月）。
MAX_HORIZON_SPAN_DAYS = 186


def resolve_backtest_config(
    strategy: str | StrategyEngine, overrides: Mapping[str, Any] | None = None,
) -> BacktestConfig:
    """历史快照战法的完整执行默认值；调用方显式值优先，旧战法不变。"""
    engine = get(strategy) if isinstance(strategy, str) else strategy
    template = getattr(engine, "backtest_config", None) or {}
    fields = BacktestConfig.__dataclass_fields__
    defaults = {
        key: value for key, value in template.items() if key in fields and key != "valuation_end"
    } if template.get("signal_dataset") else {}
    return BacktestConfig(**(defaults | dict(overrides or {})))


def backtest_strategy(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    config: BacktestConfig | None = None,
    codes: list[str] | None = None,
    universe: Mapping[str, Any] | None = None,
    skip_universe_safety: bool = False,
    adjust: str | None = None,
) -> BacktestResult:
    """在指定区间对某个策略跑成交回测（入场价 / 持有 / 止损）。"""
    ctx = prepare_backtest_context(
        store,
        strategy,
        start=start,
        end=end,
        params=params,
        codes=codes,
        universe=universe,
        skip_universe_safety=skip_universe_safety,
        adjust=adjust,
        config=config,
    )
    return execute_backtest_context(store, ctx)


def prepare_backtest_context(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    start: str | None = None,
    end: str | None = None,
    params: dict[str, Any] | None = None,
    config: BacktestConfig | None = None,
    codes: list[str] | None = None,
    universe: Mapping[str, Any] | None = None,
    skip_universe_safety: bool = False,
    adjust: str | None = None,
) -> dict[str, Any]:
    """准备一次回测的冻结上下文，供研究层生成同宇宙对照。"""
    return _prepare_signal_context(
        store,
        strategy,
        start=start,
        end=end,
        params=params,
        codes=codes,
        universe=universe,
        skip_universe_safety=skip_universe_safety,
        adjust=adjust,
        tail_days=None,
        config=config,
    )


def execute_backtest_context(
    store: MarketStore,
    ctx: Mapping[str, Any],
    *,
    use_fast: bool | None = None,
) -> BacktestResult:
    """按已准备上下文执行；研究验证可显式关闭加速旁路。"""
    cfg = ctx["config"]
    engine = ctx["engine"]
    signals = ctx["signals"]
    panels = ctx["panels"]
    execution_panels = ctx.get("execution_panels", panels)

    # 研究回测会把 benchmark 一并放进冻结 context；一旦存在就绝不能
    # 回到 MarketStore 重新读取，否则 market 在 train/OOS 之间变化会污染证据。
    if "benchmark_close" in ctx:
        benchmark_close = ctx["benchmark_close"]
    elif cfg.benchmark:
        benchmark_close = _load_benchmark(store, cfg.benchmark, panels["close"].index)
    else:
        benchmark_close = None

    fast = fast_backtest_enabled() if use_fast is None else bool(use_fast)
    result = (
        run_backtest_fast(
            signals,
            execution_panels,
            entry_timing=engine.entry_timing,
            entry_price_panel=ctx.get("entry_price_panel"),
            config=cfg,
            strategy_slug=engine.slug,
            benchmark_close=benchmark_close,
        )
        if fast
        else run_backtest(
            signals,
            execution_panels,
            entry_timing=engine.entry_timing,
            entry_price_panel=ctx.get("entry_price_panel"),
            config=cfg,
            strategy_slug=engine.slug,
            benchmark_close=benchmark_close,
        )
    )
    _attach_context(result.config, dict(ctx))
    if fast:
        # 加速旁路可能已回退经典引擎并写好了 fallback_reason，别覆盖成
        # "engine=numpy_fast"——那等于对外谎报这份结果是加速路径跑的。
        result.config.setdefault("fast", describe_fast_backend())
    return result


def build_universe_control(
    store: MarketStore,
    ctx: Mapping[str, Any],
    *,
    use_fast: bool = False,
) -> BacktestResult:
    """在策略实际命中的日期，对同一面板的全部代码生成基线事件。

    这不是把策略交易复制一份：控制信号只复用观察日期，随后让同一 A 股
    执行引擎重新检查每只股票的可成交性、T+1、涨跌停和持有期。
    """
    signals = ctx["signals"]
    control_signals = pd.DataFrame(
        False,
        index=signals.index,
        columns=signals.columns,
    )
    active_days = signals.any(axis=1)
    if bool(active_days.any()):
        membership_mask = ctx.get("universe_control_mask")
        if isinstance(membership_mask, pd.DataFrame):
            aligned = membership_mask.reindex(
                index=signals.index,
                columns=signals.columns,
            ).fillna(False)
            control_signals.loc[active_days, :] = aligned.loc[active_days, :]
        else:
            control_signals.loc[active_days, :] = True
    control_ctx = dict(ctx)
    control_ctx["signals"] = control_signals
    return execute_backtest_context(store, control_ctx, use_fast=use_fast)


def backtest_strategy_horizon(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    start: str,
    end: str,
    params: dict[str, Any] | None = None,
    codes: list[str] | None = None,
    universe: Mapping[str, Any] | None = None,
    skip_universe_safety: bool = False,
    adjust: str | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> HorizonResult:
    """信号级 Horizon T+N：标记日最高 / 选股日收盘；区间最长约 6 个月。"""
    _validate_horizon_range(start, end)
    clean = tuple(sorted({max(1, int(h)) for h in horizons})) or DEFAULT_HORIZONS
    engine_probe = get(strategy) if isinstance(strategy, str) else strategy
    tail = max(clean) + entry_day_offset(engine_probe.entry_timing) + 5

    ctx = _prepare_signal_context(
        store,
        strategy,
        start=start,
        end=end,
        params=params,
        codes=codes,
        universe=universe,
        skip_universe_safety=skip_universe_safety,
        adjust=adjust,
        tail_days=tail,
        config=None,
    )
    engine = ctx["engine"]
    execution_panels = ctx.get("execution_panels", ctx["panels"])
    result = run_horizon_backtest(
        ctx["signals"],
        execution_panels,
        entry_timing=engine.entry_timing,
        entry_price_panel=ctx.get("entry_price_panel"),
        horizons=clean,
        strategy_slug=engine.slug,
    )
    _attach_context(result.config, ctx)
    result.config["mode"] = "horizon"
    result.config["entry_timing"] = engine.entry_timing
    attach_instrument_names(result, _name_map_for_extremes(store, result))
    return result


def _name_map_for_extremes(store: MarketStore, result: HorizonResult) -> dict[str, str]:
    """只查极端案例涉及的代码，避免全表扫。"""
    needed: set[str] = set()
    for stats in result.horizons.values():
        if not stats:
            continue
        for key in ("best_event", "worst_event"):
            ref = stats.get(key)
            if isinstance(ref, dict) and ref.get("code"):
                needed.add(str(ref["code"]))
    if not needed:
        return {}
    names: dict[str, str] = {}
    for row in store.list_instruments(status=""):
        code = str(row.get("code") or "")
        if code in needed:
            names[code] = str(row.get("name") or "")
            if len(names) >= len(needed):
                break
    return names


def _validate_horizon_range(start: str, end: str) -> None:
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError as exc:
        raise StrategyError("回测区间日期格式须为 YYYY-MM-DD") from exc
    if end_d < start_d:
        raise StrategyError("回测结束日不能早于开始日")
    span = (end_d - start_d).days
    if span > MAX_HORIZON_SPAN_DAYS:
        raise StrategyError(
            f"一次性回测最长 {MAX_HORIZON_SPAN_DAYS} 天（约 6 个月），当前跨度 {span} 天"
        )


def _prepare_signal_context(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    start: str | None,
    end: str | None,
    params: dict[str, Any] | None,
    codes: list[str] | None,
    universe: Mapping[str, Any] | None,
    skip_universe_safety: bool,
    adjust: str | None,
    tail_days: int | None,
    config: BacktestConfig | None,
) -> dict[str, Any]:
    """一次 resolve + load_panel + compute；成交与 Horizon 共用。"""
    engine = get(strategy) if isinstance(strategy, str) else strategy
    resolved_params = merge_params(engine, params)
    effective_universe = (
        universe if universe is not None else getattr(engine, "default_universe", None)
    )
    effective_adjust = str(adjust or getattr(engine, "adjust", "qfq") or "qfq")
    template = getattr(engine, "backtest_config", None) or {}
    cfg = config or resolve_backtest_config(engine)
    if template.get("signal_dataset"):
        start = start or template.get("start")
        end = end or template.get("end")
        if not cfg.signal_dataset:
            raise StrategyError("该战法的历史回测必须使用14:50数据集，不能回退为收盘信号")
        if tail_days is not None:
            raise StrategyError("该战法的历史14:50数据用于成交回测，不支持horizon模式")
    if cfg.signal_dataset and (not start or not end):
        raise StrategyError("历史14:50回测必须指定开始和结束日期")
    if cfg.signal_dataset and effective_adjust != "none":
        raise StrategyError("历史14:50快照使用不复权输入，不支持替换为复权信号价")
    if cfg.signal_dataset and cfg.valuation_end is None:
        cfg = replace(cfg, valuation_end=end)

    try:
        resolved = resolve_universe(
            store,
            effective_universe,
            codes=codes,
            as_of=end or start,
            skip_safety=skip_universe_safety,
        )
    except UniverseError as exc:
        raise StrategyError(str(exc)) from exc

    # 回测要覆盖到 end 之后的持有期，否则最后一批信号会因为"数据到头"
    # 被记成 data_end / 缺标记日，混进统计里拉低结论。
    tail = tail_days if tail_days is not None else max(cfg.hold_days + 5, 10)
    days = store.trading_days()
    if not days:
        raise StrategyError("行情仓为空，请先执行 python market.py sync")

    warmup = signal_history_bars(engine, params=params)
    load_start, load_end = _expand_range(days, start, end, warmup, tail)
    if cfg.valuation_end is not None:
        if start and cfg.valuation_end < start:
            raise StrategyError("估值截止日不能早于信号开始日")
        load_end = min(load_end, cfg.valuation_end)

    if not resolved.codes:
        raise StrategyError("股票池为空（检查板块范围 / 剔 ST / 证券列表是否已同步）")

    fields = tuple(
        dict.fromkeys((*engine.required_fields(), "open", "high", "low", "close", "volume"))
    )
    panels = store.load_panel(
        fields=fields,
        codes=resolved.codes,
        start=load_start,
        end=load_end,
        adjust=effective_adjust,
        min_bars=engine.min_bars(),
    )
    attach_raw_limit_close(
        store,
        panels,
        enabled=bool(getattr(engine, "requires_raw_limit_price", False)),
        adjust=effective_adjust,
        codes=resolved.codes,
        start=load_start,
        end=load_end,
        min_bars=engine.min_bars(),
    )
    if getattr(engine, "requires_instrument_names", False):
        panels["__instrument_names__"] = {
            code: str(info.get("name", "")) for code, info in resolved.meta.items()
        }
    execution_adjust = str(getattr(engine, "execution_adjust", "") or "")
    execution_panels = panels
    if execution_adjust and execution_adjust != effective_adjust:
        execution_panels = store.load_panel(
            fields=fields,
            codes=resolved.codes,
            start=load_start,
            end=load_end,
            adjust=execution_adjust,
            min_bars=engine.min_bars(),
        )
        execution_panels = {
            field: panel.reindex(
                index=panels["close"].index,
                columns=panels["close"].columns,
            )
            for field, panel in execution_panels.items()
        }
    if panels["close"].empty:
        raise StrategyError("所选区间没有行情数据")
    if cfg.economic_returns:
        if (execution_adjust or effective_adjust) != "none":
            raise StrategyError("经济权益回测必须使用不复权执行价格")
        adjusted = store.load_panel(
            fields=("close",), codes=resolved.codes, start=load_start, end=load_end,
            adjust="hfq", min_bars=engine.min_bars(),
        )["close"].reindex(index=execution_panels["close"].index,
                          columns=execution_panels["close"].columns)
        raw = execution_panels["close"]
        quoted = raw.gt(0) & execution_panels["volume"].gt(0)
        if bool((quoted & ~(adjusted.gt(0) & np.isfinite(adjusted))).to_numpy().any()):
            raise StrategyError("实际成交日缺少有效经济权益价格，不能猜测复权因子")
        valid = quoted & adjusted.gt(0)
        factors = (adjusted / raw).where(valid).ffill().fillna(1.0)
        execution_panels = {**execution_panels, "__adjust_factor": factors}

    # 前视闸门：静态始终；大宇宙分片截断一致性（见 audit_sampling）
    from src.strategy.application.audit import LookAheadError, guard_strategy

    try:
        guard_strategy(engine, panels, params=resolved_params)
    except LookAheadError as exc:
        raise StrategyError(str(exc)) from exc

    dataset_evidence = None
    if cfg.signal_dataset:
        from src.backtest.application.asof_signals import compute_asof_signals

        try:
            signals, dataset_evidence = compute_asof_signals(
                engine, panels, resolved_params, dataset_id=cfg.signal_dataset,
                start=str(start), end=str(end),
            )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise StrategyError(str(exc)) from exc
    else:
        signals = engine.compute(panels, resolved_params).signals
    if start:
        signals = signals[signals.index >= start]
    if end:
        signals = signals[signals.index <= end]
    signals = signals.reindex(panels["close"].index).fillna(False)

    # 预挂价必须落在**执行面板**的价格坐标系里：目标价随后要跟 execution_panels
    # 的 open/low 比大小。用 qfq 信号面板算目标价、拿不复权最低价去比，两边差
    # 一个复权因子，触价判断会整体错位（除权越多错得越狠）。
    entry_price_panel = _build_entry_price_panel(
        engine, resolved_params, execution_panels
    )

    return {
        "engine": engine,
        "config": cfg,
        "resolved_params": resolved_params,
        "resolved": resolved,
        "fields": fields,
        "effective_adjust": effective_adjust,
        "load_start": load_start,
        "load_end": load_end,
        "start": start,
        "end": end,
        "panels": panels,
        "execution_panels": execution_panels,
        "execution_adjust": execution_adjust or effective_adjust,
        "signals": signals,
        "entry_price_panel": entry_price_panel,
        # 作为 context 的一部分冻结，避免执行阶段再次读取行情仓。
        "benchmark_close": _load_benchmark(store, cfg.benchmark, panels["close"].index)
        if cfg.benchmark
        else None,
        "data_snapshot": _data_snapshot(
            store,
            codes=resolved.codes,
            start=load_start,
            end=load_end,
            include_source_details=not bool(cfg.signal_dataset),
        ) | ({"signal_dataset": dataset_evidence} if dataset_evidence else {}),
    }


def _build_entry_price_panel(
    engine: StrategyEngine,
    params: dict[str, Any],
    panels: dict[str, pd.DataFrame],
) -> pd.DataFrame | None:
    """为需要预挂价的时点生成 T 日冻结的目标价面板。"""
    if engine.entry_timing != "next_dip":
        return None
    raw_dip_pct = params.get("dip_pct", params.get("DIP_PCT", 0.02))
    try:
        dip_pct = float(raw_dip_pct)
    except (TypeError, ValueError) as exc:
        raise StrategyError("next_dip 的 dip_pct 必须是数值") from exc
    if not 0 < dip_pct < 1:
        raise StrategyError("next_dip 的 dip_pct 必须在 0 与 1 之间")
    return panels["close"] * (1.0 - dip_pct)


def _attach_context(config: dict[str, Any], ctx: dict[str, Any]) -> None:
    engine = ctx["engine"]
    resolved = ctx["resolved"]
    panels = ctx["panels"]
    config["params"] = ctx["resolved_params"]
    config["strategy_revision"] = str(getattr(engine, "strategy_revision", ""))
    config["range"] = {
        "start": ctx["start"] or ctx["load_start"],
        "end": ctx["end"] or ctx["load_end"],
    }
    config["universe"] = resolved.spec
    config["universe_funnel"] = {
        **resolved.funnel.to_dict(),
        "panel_columns": int(panels["close"].shape[1]),
    }
    config["data_snapshot"] = {
        **ctx["data_snapshot"],
        "fields": list(ctx["fields"]),
        "adjust": ctx["effective_adjust"],
        "start": ctx["load_start"],
        "end": ctx["load_end"],
        "raw_limit_close": "__raw_close" in panels,
        "execution_adjust": ctx.get("execution_adjust", ctx["effective_adjust"]),
    }


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


def _data_snapshot(
    store: Any,
    *,
    codes: Sequence[str],
    start: str,
    end: str,
    include_source_details: bool = True,
) -> dict[str, Any]:
    """兼容测试替身/旧读模型，同时优先保留查询范围来源证据。"""
    method = store.data_snapshot
    parameters = inspect.signature(method).parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    kwargs: dict[str, Any] = {"codes": codes, "start": start, "end": end}
    if not include_source_details:
        kwargs["include_source_details"] = False
    if not accepts_kwargs:
        kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    # 不捕获方法内部TypeError后改做无范围全库查询。
    return dict(method(**kwargs))
