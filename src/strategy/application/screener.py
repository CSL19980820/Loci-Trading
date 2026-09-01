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
from datetime import date
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
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.domain.base import (
    SignalResult,
    StrategyEngine,
    StrategyError,
    merge_params,
    signal_history_bars,
)


ProgressCallback = Callable[[str, float, str], None]


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
    for field in fields:
        panel = panels.get(field)
        if isinstance(panel, pd.DataFrame) and not panel.empty:
            return panel
    return None


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
    resolved_params = merge_params(engine, params)
    effective_universe = (
        universe
        if universe is not None
        else getattr(engine, "default_universe", None)
    )
    effective_adjust = str(adjust or getattr(engine, "adjust", "qfq") or "qfq")
    started = time.monotonic()

    # 静态前视闸门：entry_timing=open 裸用盘中字段等 block 级问题 fail-closed
    from src.strategy.application.audit import LookAheadError, guard_strategy

    try:
        guard_strategy(engine)
    except LookAheadError as exc:
        raise StrategyError(str(exc)) from exc

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

    bars = signal_history_bars(engine, extra_bars=extra_bars)
    requires_full_history = bool(getattr(engine, "requires_full_history", False))
    start, end = _resolve_start(
        store, trade_date, bars, full_history=requires_full_history
    )
    if live_overlay:
        end = today
    # 必须带 codes + 窗口：无范围 data_snapshot 会扫全库 source_evidence，
    # 在千万行 market.db 上易触发 disk I/O error，拖死尾盘选股。
    if data_snapshot is not None:
        snapshot = dict(data_snapshot)
    else:
        snapshot = dict(
            store.data_snapshot(codes=list(resolved.codes), start=start, end=end)
        )
    result_snapshot = {
        **snapshot,
        "fields": list(engine.required_fields()),
        "adjust": effective_adjust,
        "history_mode": "full" if requires_full_history else "window",
        "start": start,
        "end": end,
        "live_overlay": bool(live_overlay),
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
            data_snapshot=result_snapshot,
        )

    _progress("panel", 48, f"加载面板 {len(resolved.codes)} 只…")
    panels = store.load_panel(
        fields=engine.required_fields(),
        codes=resolved.codes,
        start=start,
        end=end,
        adjust=effective_adjust,
        min_bars=engine.min_bars(),
    )
    attach_raw_limit_close(
        store,
        panels,
        enabled=bool(getattr(engine, "requires_raw_limit_price", False)),
        adjust=effective_adjust,
        codes=resolved.codes,
        start=start,
        end=end,
        min_bars=engine.min_bars(),
    )
    if getattr(engine, "requires_instrument_names", False):
        panels["__instrument_names__"] = {
            code: str(info.get("name", "")) for code, info in resolved.meta.items()
        }
    if live_overlay:
        from src.market import ScreenLiveError, fetch_live_spot_bars, overlay_live_day

        types = {
            code: str((resolved.meta.get(code) or {}).get("instrument_type") or "STOCK")
            for code in resolved.codes
        }
        _progress("live", 52, f"拉取实时行情 {len(resolved.codes)} 只…")
        try:
            live_bars = fetch_live_spot_bars(
                resolved.codes, instrument_types=types
            )
        except ScreenLiveError as exc:
            raise StrategyError(str(exc)) from exc
        if not live_bars:
            raise StrategyError(
                "盘中选股拉不到实时行情，已中止（不回退昨日本地日 K）"
            )
        panels = overlay_live_day(panels, live_bars, today)
        result_snapshot["live_overlay_codes"] = len(live_bars)
        _progress("live", 56, f"已叠实时日 K {len(live_bars)} 只")
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
            data_snapshot=result_snapshot,
        )

    # 动态截断一致性：小宇宙全列，大宇宙分片全覆盖（见 audit_sampling）
    try:
        guard_strategy(engine, panels, params=resolved_params)
    except LookAheadError as exc:
        raise StrategyError(str(exc)) from exc

    _progress("compute", 62, f"计算信号 · {engine.name}…")
    result: SignalResult = engine.compute(panels, resolved_params)
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
    picks = enrich_picks(
        [
            {
                "code": code,
                "close": _cell(close_panel, target_date, code),
                "open": _cell(panels.get("open"), target_date, code),
                "pct_chg": _pct_chg(close_panel, target_date, code),
                "factors": result.explain(target_date, code),
            }
            for code in pick_codes
        ],
        resolved.meta,
    )
    watch_picks = enrich_picks(
        [
            {
                "code": code,
                "close": _cell(close_panel, target_date, code),
                "open": _cell(panels.get("open"), target_date, code),
                "pct_chg": _pct_chg(close_panel, target_date, code),
                "factors": result.explain(target_date, code),
                "intent": "observe",
            }
            for code in watch_codes
        ],
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
        data_snapshot=result_snapshot,
    )


def _cell(panel: pd.DataFrame | None, trade_date: str, code: str) -> float | None:
    if panel is None or trade_date not in panel.index or code not in panel.columns:
        return None
    value = panel.at[trade_date, code]
    return None if pd.isna(value) else round(float(value), 4)


def _pct_chg(panel: pd.DataFrame | None, trade_date: str, code: str) -> float | None:
    """相对前一交易日收盘的涨跌幅（%）。缺前收则返回 None。"""
    close = _cell(panel, trade_date, code)
    if panel is None or close is None or trade_date not in panel.index:
        return None
    try:
        loc = panel.index.get_loc(trade_date)
        idx = int(loc)
    except (KeyError, TypeError, ValueError):
        return None
    if idx <= 0 or code not in panel.columns:
        return None
    prev = panel.iloc[idx - 1][code]
    if pd.isna(prev):
        return None
    prev_f = float(prev)
    if prev_f == 0:
        return None
    return round((close / prev_f - 1.0) * 100.0, 2)
