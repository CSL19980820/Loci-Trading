"""策略衰减监测：发现战法开始失效的最早信号。

策略会失效。最危险的不是"突然跌停"而是"缓慢变差"——
胜率从55%逐渐滑到45%，每周都在亏，但每周亏得不多，
所以没人触发止损，直到亏够了才意识到。

这里用滚动窗口胜率 vs 历史基线做偏离检测。
优先用精选候选的 T+5 收益序列；无候选时回退手工复盘。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.ledger import PalaceStore

if TYPE_CHECKING:
    from src.market import MarketStore


@dataclass
class StrategyDecayReport:
    strategy_tag: str
    total_records: int
    baseline_win_rate: float | None  # first baseline_window records, None if < 2
    recent_win_rate: float | None    # last window records, None if < 1
    decay_signal: str                # "ok" | "warning" | "critical"
    note: str = ""
    recent_count: int = 0
    baseline_count: int = 0
    source: str = "reviews"

    def to_dict(self) -> dict:
        return {
            "strategy_tag": self.strategy_tag,
            "total_records": self.total_records,
            "baseline_win_rate": self.baseline_win_rate,
            "recent_win_rate": self.recent_win_rate,
            "signal": self.decay_signal,
            "decay_signal": self.decay_signal,
            "note": self.note,
            "recent_count": self.recent_count,
            "baseline_count": self.baseline_count,
            "source": self.source,
        }


def _decay_from_returns(
    strategy_tag: str,
    returns: list[float],
    *,
    window: int,
    baseline_window: int,
    source: str,
    empty_note: str,
) -> StrategyDecayReport:
    total = len(returns)
    if total == 0:
        return StrategyDecayReport(
            strategy_tag=strategy_tag,
            total_records=0,
            baseline_win_rate=None,
            recent_win_rate=None,
            decay_signal="ok",
            note=empty_note,
            source=source,
        )

    baseline_slice = returns[:baseline_window]
    recent_slice = returns[-window:]

    baseline_win_rate: float | None = None
    if len(baseline_slice) >= 2:
        wins = sum(1 for x in baseline_slice if x > 0)
        baseline_win_rate = round(wins / len(baseline_slice) * 100, 2)

    recent_win_rate: float | None = None
    if len(recent_slice) >= 1:
        wins = sum(1 for x in recent_slice if x > 0)
        recent_win_rate = round(wins / len(recent_slice) * 100, 2)

    signal = "ok"
    note = ""
    if recent_win_rate is not None:
        if recent_win_rate < 30.0:
            signal = "critical"
            note = f"近期胜率 {recent_win_rate}% 低于 30%"
        elif baseline_win_rate is not None:
            drop = baseline_win_rate - recent_win_rate
            if drop >= 20.0:
                signal = "critical"
                note = f"相对基线下降 {drop:.1f} 个百分点"
            elif drop >= 10.0:
                signal = "warning"
                note = f"相对基线下降 {drop:.1f} 个百分点"

    return StrategyDecayReport(
        strategy_tag=strategy_tag,
        total_records=total,
        baseline_win_rate=baseline_win_rate,
        recent_win_rate=recent_win_rate,
        decay_signal=signal,
        note=note,
        recent_count=len(recent_slice),
        baseline_count=len(baseline_slice),
        source=source,
    )


def check_decay(
    palace: PalaceStore,
    strategy_tag: str,
    window: int = 20,
    baseline_window: int = 100,
) -> StrategyDecayReport:
    """单战法衰减检测（手工复盘口径）。"""
    returns = palace.review_returns_for_tag(strategy_tag)
    return _decay_from_returns(
        strategy_tag,
        returns,
        window=window,
        baseline_window=baseline_window,
        source="reviews",
        empty_note="暂无复盘收益数据",
    )


def check_all_decay(
    palace: PalaceStore,
    window: int = 20,
    baseline_window: int = 100,
    market: MarketStore | None = None,
) -> list[StrategyDecayReport]:
    """全战法衰减扫描。有行情仓时优先用精选候选 T+5。"""
    by_tag: dict[str, StrategyDecayReport] = {}

    if market is not None:
        from src.review.application.outcomes import evaluate_candidates

        outcomes = evaluate_candidates(palace, market, limit=2000)
        series: dict[str, list[tuple[str, float]]] = {}
        for outcome in outcomes:
            if not outcome.selected:
                continue
            value = outcome.returns.get(5)
            if value is None:
                continue
            series.setdefault(outcome.strategy_tag(), []).append((outcome.base_date, value))
        for tag, pairs in series.items():
            pairs.sort(key=lambda item: item[0])
            by_tag[tag] = _decay_from_returns(
                tag,
                [value for _, value in pairs],
                window=window,
                baseline_window=baseline_window,
                source="candidates",
                empty_note="暂无候选 T+5 样本",
            )

    for tag in palace.review_strategy_tags_with_returns():
        if tag in by_tag and by_tag[tag].total_records > 0:
            continue
        by_tag[tag] = check_decay(palace, tag, window, baseline_window)

    return sorted(by_tag.values(), key=lambda r: (-r.total_records, r.strategy_tag))
