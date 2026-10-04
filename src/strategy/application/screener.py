"""选股执行器：把"行情仓 + 策略"接成一次可复现的全市场扫描。

之所以单独一层，是因为选股要保证两件事，而这两件事不该散落在每个策略里：

1. **只加载必要的字段与窗口。** 全市场十年日线是千万行级，但选最近一天
   只需要最近几十根 K 线。按策略声明的 min_bars 反推起始日期，内存占用
   从 GB 级掉到 MB 级——服务器可用内存只有 1.1G，这不是优化是必要条件。
2. **结果自带解释。** 选中一只票必须能说出是哪几条成立、各项数值多少，
   否则复盘时无法区分"规则有效"和"撞运气"。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import wraps
from typing import Any

import pandas as pd

from src.market import (
    MarketStore,
    ResolvedUniverse,
    UniverseError,
    enrich_picks,
    resolve_universe,
)
from src.strategy.application.catalog import get
from src.strategy.application.compute_runtime import (
    computation_scope, compute_result, execution_profile, range_compute_end,
)
from src.strategy.application.price_constraints import (
    attach_raw_limit_close,
)
from src.strategy.domain.base import (
    SignalResult,
    StrategyEngine,
    StrategyError,
    merge_params,
    signal_history_bars,
)


ProgressCallback = Callable[[str, float, str], None]


def _with_computation_scope(method):
    @wraps(method)
    def scoped(store, *args, **kwargs):
        with computation_scope(store):
            return method(store, *args, **kwargs)
    return scoped


@dataclass
class ScreenResult:
    """一次选股的完整产出，可直接落库或转 JSON 给前端。"""

    strategy_slug: str
    trade_date: str
    strategy_revision: str = ""
    picks: list[dict[str, Any]] = field(default_factory=list)
    watch_picks: list[dict[str, Any]] = field(default_factory=list)
    universe_size: int = 0
    elapsed_seconds: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    effective_params: dict[str, Any] = field(default_factory=dict)
    entry_timing: str = ""
    #: 选股前那次数据体检的结论。带上它，事后才能区分"当时数据是干净的"
    #: 和"当时就有警告只是没人看"——后者是复盘时最容易漏掉的解释。
    health: dict[str, Any] | None = None
    universe: dict[str, Any] = field(default_factory=dict)
    universe_funnel: dict[str, int] = field(default_factory=dict)
    data_snapshot: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"[{self.strategy_slug}] {self.trade_date} 选出 {len(self.picks)} 只，"
            f"低吸观察 {len(self.watch_picks)} 只"
            f"（候选池 {self.universe_size} 只，耗时 {self.elapsed_seconds:.2f}s，"
            f"入场={self.entry_timing}）"
        )


def _resolve_start(
    store: MarketStore, end: str | None, bars: int, *, full_history: bool = False
) -> tuple[str, str]:
    """按需要的 K 线根数反推起始交易日；递推公式必须从首根可用 K 线开始。"""
    days = store.trading_days(end=end)
    if not days:
        raise StrategyError("行情仓没有任何交易日数据，请先执行同步")
    target_end = days[-1]
    start_index = 0 if full_history else max(0, len(days) - bars)
    return days[start_index], target_end


def _reference_panel(
    panels: Mapping[str, Any], fields: tuple[str, ...]
) -> pd.DataFrame | None:
    """所有策略不一定读取 close；用首个非空必需字段作为信号面板参考。"""
    for name in fields:
        panel = panels.get(name)
        if isinstance(panel, pd.DataFrame) and not panel.empty:
            return panel
    return None


def _seal_snapshot(store: MarketStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    """收尾复核行情版本：不一致说明面板加载期间有人写过行情库。

    ``data_snapshot`` 描述的是**取证那一刻**的水位，从来不承诺整段计算期间数据库
    被冻结——2026-09 的架构复审把这点记成了遗留缺口。真做统一读事务的代价远大于
    收益（热库重建单事务重写 700 日窗口期间 WAL 无法 checkpoint），但末尾补一次
    采样是零成本的：``market_revision`` 是 meta 单行查询。

    两次不一致时显式标出来，而不是让结果看起来像在一份快照上算的。行情读写槽
    本该防住选股与同步撞车，命中这条说明槽漏了，是要查的信号而不是正常现象。
    """
    before = str(snapshot.get("market_revision") or "")
    if not before:
        return snapshot
    try:
        after = store.market_revision()
    except Exception:
        # 复核失败不能拖垮已经算完的选股结果；缺这个字段等于「没复核」。
        return snapshot
    if after == before:
        return snapshot
    return {
        **snapshot,
        "market_revision_end": after,
        "revision_changed_during_run": True,
    }


@_with_computation_scope
def screen(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    trade_date: str | None = None,
    params: dict[str, Any] | None = None,
    codes: list[str] | None = None,
    universe: Mapping[str, Any] | None = None,
    skip_universe_safety: bool = False,
    extra_bars: int = 20,
    adjust: str | None = None,
    health_check: bool = True,
    on_progress: ProgressCallback | None = None,
    data_snapshot: Mapping[str, Any] | None = None,
    live_overlay: bool | None = None,
) -> ScreenResult:
    """在指定交易日跑一次全市场选股。

    trade_date 为空时取行情仓里最新的交易日。extra_bars 是在策略声明的
    min_bars 之上额外多取的根数，用来吸收停牌造成的空洞——某只票停牌 10 天，
    它的有效 K 线就比日历天数少 10 根，不留余量会让指标算不出来。

    health_check: 选股前先体检行情仓，不合格直接抛 ``DataQualityError``。
                  默认开启，因为"选出一份静默错掉的候选池"比"选不出来"危险
                  得多——后者你立刻知道，前者可能拿去下单。只在指定 codes
                  的小范围调试时自动跳过（全市场覆盖率对单票没有意义）。
    on_progress: 可选进度回调 ``(phase, percent, message)``，供异步选股轮询。
    data_snapshot: 可复用的行情仓快照；区间选股由调用方在任务开始时提供一次。
    live_overlay: 盘中选今天时叠独立实时日 K（不写库）。``None`` 按时钟自动判断。
    """
    import time

    def _progress(phase: str, percent: float, message: str) -> None:
        if on_progress is not None:
            on_progress(phase, percent, message)

    engine = get(strategy) if isinstance(strategy, str) else strategy
    if getattr(engine, "requires_realtime_inputs", False):
        raise StrategyError("该战法须使用盘后样本与09:25实时报价入口，不能以系统行情面板代替现场筛选")
    resolved_params = merge_params(engine, params)
    effective_universe = (
        universe
        if universe is not None
        else getattr(engine, "default_universe", None)
    )
    effective_adjust = str(adjust or getattr(engine, "adjust", "qfq") or "qfq")
    started = time.monotonic()

    from src.strategy.application.audit import LookAheadError, guard_runtime_strategy
    from src.strategy.application.audit_policy import runtime_audit_mode

    try:
        guard_runtime_strategy(engine, params=resolved_params)
    except LookAheadError as exc:
        raise StrategyError(str(exc)) from exc
    runtime_validation = runtime_audit_mode(engine, resolved_params)
    dynamic_validation = runtime_validation == "dynamic"

    from src.market import should_overlay_live

    if live_overlay is None:
        live_overlay = should_overlay_live(trade_date)
    today = date.today().isoformat()

    health: dict[str, Any] | None = None
    if health_check and not codes:
        from src.market import guard_market_health

        _progress("health", 12, "数据体检…")
        health_date = trade_date
        if live_overlay:
            days = store.trading_days()
            health_date = days[-1] if days else trade_date
        health = guard_market_health(store, trade_date=health_date).to_dict()
        _progress("health", 20, "体检通过，解析宇宙…")

    try:
        _progress("universe", 28, "解析股票范围…")
        resolved: ResolvedUniverse = resolve_universe(
            store,
            effective_universe,
            codes=codes,
            as_of=trade_date or (today if live_overlay else None),
            skip_safety=skip_universe_safety,
        )
    except UniverseError as exc:
        raise StrategyError(str(exc)) from exc

    bars = signal_history_bars(engine, extra_bars=extra_bars, params=resolved_params)
    requires_full_history = bool(getattr(engine, "requires_full_history", False))
    start, end = _resolve_start(
        store, trade_date, bars, full_history=requires_full_history
    )
    if live_overlay:
        end = today
    profile = execution_profile(engine, resolved_params)
    if not profile.pure:
        # Bound the ordinary reader before it builds a large SQL/pivot heap.
        # Proven column-independent formulas use the bounded batch path instead.
        import os
        try:
            input_budget = int(os.environ.get("LOCI_SCREEN_INPUT_BYTES", "268435456"))
        except ValueError:
            input_budget = 268435456
        estimate = len(store.trading_days(start=start, end=end)) * len(resolved.codes) * max(1, len(engine.required_fields())) * 8
        if estimate > max(1, input_budget):
            raise StrategyError("策略输入超出选股内存预算，请缩小股票范围或历史窗口")
    # 必须带 codes + 窗口：无范围 data_snapshot 会扫全库 source_evidence，
    # 在千万行 market.db 上易触发 disk I/O error，拖死尾盘选股。
    if data_snapshot is not None:
        snapshot = dict(data_snapshot)
    else:
        snapshot = dict(
            store.data_snapshot(
                codes=list(resolved.codes), start=start, end=end,
                include_source_details=False,
                **({"source_evidence_mode": "compact"} if isinstance(store, MarketStore) else {}),
                **({"source_summary_only": True}
                   if getattr(engine, "source_evidence_summary", False) else {}),
            )
        )
    result_snapshot = {
        **snapshot,
        "fields": list(engine.required_fields()),
        "adjust": effective_adjust,
        "history_mode": "full" if requires_full_history else "window",
        "start": start,
        "end": end,
        "live_overlay": bool(live_overlay),
        "strategy_validation": runtime_validation,
    }
    _progress(
        "universe",
        38,
        f"宇宙 {len(resolved.codes)} 只 · 窗口 {start}→{end}",
    )

    if not resolved.codes:
        funnel = resolved.funnel.to_dict()
        return ScreenResult(
            strategy_slug=engine.slug,
            strategy_revision=str(getattr(engine, "strategy_revision", "")),
            trade_date=end,
            universe_size=0,
            elapsed_seconds=time.monotonic() - started,
            params=resolved_params,
            effective_params=resolved_params,
            entry_timing=engine.entry_timing,
            health=health,
            universe=resolved.spec,
            universe_funnel=funnel,
            data_snapshot=_seal_snapshot(store, result_snapshot),
        )

    _progress("panel", 48, f"加载面板 {len(resolved.codes)} 只…")
    pre_candidate_method = getattr(engine, "live_candidate_codes", None) if live_overlay else None
    live_prefilter = callable(pre_candidate_method)
    load_min_bars = max(1, engine.min_bars() - 1) if live_prefilter else engine.min_bars()
    independent = (profile.pure and profile.causal and profile.column_mode == "independent"
                   and profile.origin in {"finite", "sensitive"}
                   and not profile.metadata_fields and not live_overlay
                   and not getattr(engine, "requires_raw_limit_price", False)
                   and not getattr(engine, "requires_instrument_names", False))
    prepared = None
    if independent:
        from src.strategy.application.screen_independent_prepare import independent_inputs
        _progress("compute", 52, "按股票批次计算区间…")
        prepared = independent_inputs(store, engine, resolved_params, day=trade_date or end,
                                      start=start, end=end, resolved=resolved, bars=bars,
                                      adjust=effective_adjust, min_bars=load_min_bars,
                                      codes=codes, universe=effective_universe,
                                      skip_safety=skip_universe_safety,
                                      on_progress=lambda message: _progress("compute", 52, message))
        panels = prepared.raw_panels
    else:
        panels = store.load_panel(
            fields=engine.required_fields(), codes=resolved.codes, start=start,
            end=end, adjust=effective_adjust, min_bars=load_min_bars,
            **({"raw_price_fields": ("open", "high", "low", "close")
                                   if getattr(engine, "requires_raw_limit_ohlc", False) else ("close",)}
               if isinstance(store, MarketStore) and getattr(engine, "requires_raw_limit_price", False)
               else {}),
        )
    attach_raw_limit_close(
        store,
        panels,
        enabled=bool(getattr(engine, "requires_raw_limit_price", False)),
        adjust=effective_adjust,
        codes=resolved.codes,
        start=start,
        end=end,
        min_bars=load_min_bars,
        include_ohlc=bool(getattr(engine, "requires_raw_limit_ohlc", False)),
    )
    if getattr(engine, "requires_instrument_names", False):
        panels["__instrument_names__"] = {
            code: str(info.get("name", "")) for code, info in resolved.meta.items()
        }
    if live_overlay:
        from src.market import ScreenLiveError, fetch_live_spot_bars, overlay_live_day

        live_codes = list(resolved.codes)
        if live_prefilter:
            live_codes = pre_candidate_method(panels, today, resolved_params)
            result_snapshot["pre_candidate_count"] = len(live_codes)
            # 未请求股票也必须抹去旧今日K，否则会被完整compute误当实时数据。
            for field in ("open", "high", "low", "close", "volume",
                          "__raw_open", "__raw_high", "__raw_low", "__raw_close"):
                panel = panels.get(field)
                if isinstance(panel, pd.DataFrame):
                    panels[field] = panel.reindex(panel.index.union([today])).copy()
                    panels[field].loc[today, :] = float("nan")
        result_snapshot["live_requested_codes"] = len(live_codes)
        types = {
            code: str((resolved.meta.get(code) or {}).get("instrument_type") or "STOCK")
            for code in live_codes
        }
        _progress("live", 52, f"拉取实时行情 {len(live_codes)} 只…")
        strict_live = bool(getattr(engine, "strict_live_ohlcv", False))
        fetch_started_at = datetime.now(timezone.utc).isoformat() if live_codes else None
        try:
            if not live_codes:
                live_bars = {}
            elif strict_live:
                live_bars = fetch_live_spot_bars(
                    live_codes, instrument_types=types, strict=True
                )
            else:
                live_bars = fetch_live_spot_bars(
                    live_codes, instrument_types=types
                )
        except ScreenLiveError as exc:
            raise StrategyError(str(exc)) from exc
        result_snapshot.update(
            live_fetch_started_at=fetch_started_at,
            live_fetch_finished_at=datetime.now(timezone.utc).isoformat() if live_codes else None,
            strict_live_ohlcv=strict_live,
            live_fetch_atomic=False,
        )
        if strict_live and live_prefilter:
            # 留下全部预候选的当时输入，后续可复盘真实尾盘信号，而非拿收盘K代替。
            result_snapshot["live_ohlcv"] = {
                code: dict(bar) for code, bar in live_bars.items()
            }
        if not live_bars and live_codes:
            raise StrategyError(
                "盘中选股拉不到实时行情，已中止（不回退昨日本地日 K）"
            )
        overlay_bars = live_bars
        if strict_live and live_prefilter:
            # 原式要求V>昨日V，明确零量不可能命中，且停牌不得虚构新日K。
            result_snapshot["zero_volume_codes"] = sorted(
                code for code, bar in live_bars.items() if bar["volume"] == 0
            )
            if engine.entry_timing != "open":
                overlay_bars = {code: bar for code, bar in live_bars.items() if bar["volume"] != 0}
        panels = overlay_live_day(panels, overlay_bars, today)
        result_snapshot["live_overlay_codes"] = len(overlay_bars)
        _progress("live", 56, f"已叠实时日 K {len(overlay_bars)} 只")
    reference = _reference_panel(panels, engine.required_fields())
    if reference is None:
        funnel = resolved.funnel.to_dict()
        funnel["panel_columns"] = 0
        return ScreenResult(
            strategy_slug=engine.slug,
            strategy_revision=str(getattr(engine, "strategy_revision", "")),
            trade_date=end,
            universe_size=0,
            elapsed_seconds=time.monotonic() - started,
            params=resolved_params,
            effective_params=resolved_params,
            entry_timing=engine.entry_timing,
            health=health,
            universe=resolved.spec,
            universe_funnel=funnel,
            data_snapshot=_seal_snapshot(store, result_snapshot),
        )

    # One range calculation can serve later targets only when their actual inputs
    # match: original origin, axes, metadata and per-day adjustment are all keyed.
    future_end = range_compute_end(engine, panels, resolved_params) if dynamic_validation and prepared is None and profile.pure and profile.causal and not live_overlay else None
    if future_end and future_end > end:
        _progress("compute", 57, "计算区间共享信号…")
        future = store.load_panel(fields=engine.required_fields(), codes=resolved.codes,
                                  start=start, end=future_end, adjust=effective_adjust,
                                  min_bars=load_min_bars)
        # Newly eligible columns must not alter a cross-sectional target universe.
        for name, frame in future.items():
            if isinstance(frame, pd.DataFrame) and not frame.columns.equals(reference.columns):
                future[name] = frame.reindex(columns=reference.columns)
        frame = None  # Release the loop's last full-history panel before computing.
        attach_raw_limit_close(store, future,
                               enabled=bool(getattr(engine, "requires_raw_limit_price", False)),
                               adjust=effective_adjust, codes=resolved.codes, start=start,
                               end=future_end, min_bars=load_min_bars,
                               include_ohlc=bool(getattr(engine, "requires_raw_limit_ohlc", False)))
        for name in profile.metadata_fields:
            if name not in future and name in panels:
                future[name] = panels[name]
        future_reference = _reference_panel(future, engine.required_fields())
        if future_reference is not None:
            first_probe = reference.index[max(0, len(reference.index) - 3)]
            wanted = list(future_reference.index[future_reference.index >= first_probe])
            compute_result(engine, future, resolved_params, dates=wanted)
        del future, future_reference

    _progress("compute", 58, f"计算信号 · {engine.name}…")
    from src.strategy.application.screen_python import PythonScreenEngine
    worker_audited = prepared is None and not profile.pure
    if worker_audited:
        if isinstance(engine, PythonScreenEngine):
            result: SignalResult = engine.compute_audited(panels, resolved_params)
        else:
            from src.strategy.application.compute_worker import compute_in_worker

            result = compute_in_worker(engine, panels, resolved_params, audit=True)
    else:
        if prepared is not None:
            result = prepared.result
        elif dynamic_validation:
            result = compute_result(engine, panels, resolved_params)
        else:
            # Reviewed builtins need only the requested signal day. Their daily
            # origin/qfq anchor varies, so speculative cache hashes have no reuse.
            signal_day = trade_date if trade_date in reference.index else str(reference.index[-1])
            result = compute_result(engine, panels, resolved_params, dates=[signal_day], reuse=False)
    # Independent formulas may be audited in column shards; coupled rankings
    # retain the complete target universe. Both compare every factor and channel.
    try:
        if prepared is None and not worker_audited:
            if dynamic_validation:
                _progress("audit", 58, "检查前视偏差（全股票范围）…")
            guard_runtime_strategy(engine, panels, params=resolved_params, baseline=result)
    except LookAheadError as exc:
        raise StrategyError(str(exc)) from exc

    target_date = trade_date or str(result.signals.index[-1])
    if target_date not in result.signals.index:
        target_date = str(result.signals.index[-1])

    rank_by = str(getattr(engine, "screen_rank_factor", "") or "").strip() or None
    pick_codes = result.picks_on(target_date, rank_by=rank_by)
    picked = set(pick_codes)
    watch_codes = [
        code
        for code in result.watch_picks_on(target_date, rank_by=rank_by)
        if code not in picked
    ]
    _progress(
        "explain",
        78,
        f"解释因子 · 正式 {len(pick_codes)} 只 · 观察 {len(watch_codes)} 只…",
    )
    close_panel = panels.get("close")
    previous_close = _previous_close_row(close_panel, target_date)

    def explain_pick(code: str) -> dict[str, Any]:
        close = _cell(close_panel, target_date, code)
        return {
            "code": code,
            "close": close,
            "open": _cell(panels.get("open"), target_date, code),
            "pct_chg": _pct_chg(close, previous_close, code),
            "factors": result.explain(target_date, code),
        }

    picks = enrich_picks(
        [explain_pick(code) for code in pick_codes],
        resolved.meta,
    )
    watch_picks = enrich_picks(
        [{**explain_pick(code), "intent": "observe"} for code in watch_codes],
        resolved.meta,
    )

    funnel = resolved.funnel.to_dict()
    funnel["panel_columns"] = int(reference.shape[1])
    funnel["signals_true"] = len(picks)
    funnel["watch_signals_true"] = len(watch_picks)

    return ScreenResult(
        strategy_slug=engine.slug,
        strategy_revision=str(getattr(engine, "strategy_revision", "")),
        trade_date=target_date,
        picks=picks,
        watch_picks=watch_picks,
        universe_size=int(reference.shape[1]),
        elapsed_seconds=time.monotonic() - started,
        params=resolved_params,
        effective_params=resolved_params,
        entry_timing=engine.entry_timing,
        health=health,
        universe=resolved.spec,
        universe_funnel=funnel,
        data_snapshot=_seal_snapshot(store, result_snapshot),
    )


def _cell(panel: pd.DataFrame | None, trade_date: str, code: str) -> float | None:
    if panel is None or trade_date not in panel.index or code not in panel.columns:
        return None
    value = panel.at[trade_date, code]
    return None if pd.isna(value) else round(float(value), 4)


def _previous_close_row(panel: pd.DataFrame | None, trade_date: str) -> pd.Series | None:
    """正式和观察解释共用一次前收行；多数据块面板不按股票重复组装整行。"""
    if panel is None or trade_date not in panel.index:
        return None
    try:
        loc = panel.index.get_loc(trade_date)
        idx = int(loc)
    except (KeyError, TypeError, ValueError):
        return None
    return panel.iloc[idx - 1] if idx > 0 else None


def _pct_chg(close: float | None, previous_close: pd.Series | None, code: str) -> float | None:
    """沿用四位当前价与未舍入前收计算涨跌幅（%）；缺前收返回 None。"""
    if close is None or previous_close is None or code not in previous_close.index:
        return None
    prev = previous_close[code]
    if pd.isna(prev):
        return None
    prev_f = float(prev)
    if prev_f == 0:
        return None
    return round((close / prev_f - 1.0) * 100.0, 2)
