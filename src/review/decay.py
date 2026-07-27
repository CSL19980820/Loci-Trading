"""策略衰减监测：发现战法开始失效的最早信号。

策略会失效。最危险的不是"突然跌停"而是"缓慢变差"——
胜率从55%逐渐滑到45%，每周都在亏，但每周亏得不多，
所以没人触发止损，直到亏够了才意识到。

这里用滚动窗口胜率 vs 历史基线做偏离检测。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.palace import PalaceStore


@dataclass
class StrategyDecayReport:
    strategy_tag: str
    total_records: int
    baseline_win_rate: float | None  # first baseline_window records, None if < 2
    recent_win_rate: float | None    # last window records, None if < 1
    decay_signal: str                # "ok" | "warning" | "critical"
    note: str = ""


def check_decay(
    palace: PalaceStore,
    strategy_tag: str,
    window: int = 20,
    baseline_window: int = 100,
) -> StrategyDecayReport:
    """单战法衰减检测。"""
    rows = palace.conn.execute(
        """
        SELECT return_pct FROM reviews
        WHERE return_pct IS NOT NULL AND strategy_tag = ?
        ORDER BY reviewed_on ASC, created_at ASC
        """,
        (strategy_tag,),
    ).fetchall()

    total = len(rows)
    if total == 0:
        return StrategyDecayReport(
            strategy_tag=strategy_tag,
            total_records=0,
            baseline_win_rate=None,
            recent_win_rate=None,
            decay_signal="ok",
            note="no data",
        )

    returns = [float(r["return_pct"]) for r in rows]

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
            note = f"recent_win_rate {recent_win_rate}% < 30%"
        elif baseline_win_rate is not None:
            drop = baseline_win_rate - recent_win_rate
            if drop >= 20.0:
                signal = "critical"
                note = f"dropped {drop:.1f}pp vs baseline"
            elif drop >= 10.0:
                signal = "warning"
                note = f"dropped {drop:.1f}pp vs baseline"

    return StrategyDecayReport(
        strategy_tag=strategy_tag,
        total_records=total,
        baseline_win_rate=baseline_win_rate,
        recent_win_rate=recent_win_rate,
        decay_signal=signal,
        note=note,
    )


def check_all_decay(
    palace: PalaceStore,
    window: int = 20,
    baseline_window: int = 100,
) -> list[StrategyDecayReport]:
    """全战法衰减扫描。"""
    tags_rows = palace.conn.execute(
        "SELECT DISTINCT strategy_tag FROM reviews WHERE return_pct IS NOT NULL"
    ).fetchall()
    tags = [r["strategy_tag"] for r in tags_rows]
    return [check_decay(palace, tag, window, baseline_window) for tag in tags]
