"""选股执行器：把"行情仓 + 策略"接成一次可复现的全市场扫描。

之所以单独一层，是因为选股要保证两件事，而这两件事不该散落在每个策略里：

1. **只加载必要的字段与窗口。** 全市场十年日线是千万行级，但选最近一天
   只需要最近几十根 K 线。按策略声明的 min_bars 反推起始日期，内存占用
   从 GB 级掉到 MB 级——服务器可用内存只有 1.1G，这不是优化是必要条件。
2. **结果自带解释。** 选中一只票必须能说出是哪几条成立、各项数值多少，
   否则复盘时无法区分"规则有效"和"撞运气"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.market.store import MarketStore
from src.strategies.base import SignalResult, StrategyEngine, StrategyError, get, merge_params


@dataclass
class ScreenResult:
    """一次选股的完整产出，可直接落库或转 JSON 给前端。"""

    strategy_slug: str
    trade_date: str
    picks: list[dict[str, Any]] = field(default_factory=list)
    universe_size: int = 0
    elapsed_seconds: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    entry_timing: str = ""

    def summary(self) -> str:
        return (
            f"[{self.strategy_slug}] {self.trade_date} 选出 {len(self.picks)} 只"
            f"（候选池 {self.universe_size} 只，耗时 {self.elapsed_seconds:.2f}s，"
            f"入场={self.entry_timing}）"
        )


def _resolve_start(store: MarketStore, end: str | None, bars: int) -> tuple[str, str]:
    """按需要的 K 线根数反推起始交易日，避免整库加载。"""
    days = store.trading_days(end=end)
    if not days:
        raise StrategyError("行情仓没有任何交易日数据，请先执行同步")
    target_end = days[-1]
    start_index = max(0, len(days) - bars)
    return days[start_index], target_end


def screen(
    store: MarketStore,
    strategy: str | StrategyEngine,
    *,
    trade_date: str | None = None,
    params: dict[str, Any] | None = None,
    codes: list[str] | None = None,
    extra_bars: int = 20,
    adjust: str = "qfq",
) -> ScreenResult:
    """在指定交易日跑一次全市场选股。

    trade_date 为空时取行情仓里最新的交易日。extra_bars 是在策略声明的
    min_bars 之上额外多取的根数，用来吸收停牌造成的空洞——某只票停牌 10 天，
    它的有效 K 线就比日历天数少 10 根，不留余量会让指标算不出来。
    """
    import time

    engine = get(strategy) if isinstance(strategy, str) else strategy
    resolved_params = merge_params(engine, params)
    started = time.monotonic()

    bars = engine.min_bars() + max(0, extra_bars)
    start, end = _resolve_start(store, trade_date, bars)

    panels = store.load_panel(
        fields=engine.required_fields(),
        codes=codes,
        start=start,
        end=end,
        adjust=adjust,
        min_bars=engine.min_bars(),
    )
    reference = panels.get("close")
    if reference is None or reference.empty:
        return ScreenResult(
            strategy_slug=engine.slug,
            trade_date=end,
            universe_size=0,
            elapsed_seconds=time.monotonic() - started,
            params=resolved_params,
            entry_timing=engine.entry_timing,
        )

    result: SignalResult = engine.compute(panels, resolved_params)
    target_date = trade_date or str(result.signals.index[-1])
    if target_date not in result.signals.index:
        target_date = str(result.signals.index[-1])

    picks = [
        {
            "code": code,
            "close": _cell(panels.get("close"), target_date, code),
            "open": _cell(panels.get("open"), target_date, code),
            "factors": result.explain(target_date, code),
        }
        for code in result.picks_on(target_date)
    ]

    return ScreenResult(
        strategy_slug=engine.slug,
        trade_date=target_date,
        picks=picks,
        universe_size=int(reference.shape[1]),
        elapsed_seconds=time.monotonic() - started,
        params=resolved_params,
        entry_timing=engine.entry_timing,
    )


def _cell(panel: pd.DataFrame | None, trade_date: str, code: str) -> float | None:
    if panel is None or trade_date not in panel.index or code not in panel.columns:
        return None
    value = panel.at[trade_date, code]
    return None if pd.isna(value) else round(float(value), 4)
