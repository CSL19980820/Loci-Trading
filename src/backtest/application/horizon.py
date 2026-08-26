"""信号级 Horizon T+N 回测。

问的是：选股日后，按入场时点持有 N 个交易日，标记日最高相对选股日收盘
能涨多少——不是成交引擎那套入场价/止损账本。

口径（权威，见 docs/architecture/strategy-backtest-plan.md）：

- 分母永远是 close(D)（选股日收盘）
- 标记日 M = 入场日 E + N；E 由 entry_timing 决定
- 主收益 r = high(M) / close(D) - 1
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

DEFAULT_HORIZONS: tuple[int, ...] = (1, 3)


@dataclass
class HorizonEvent:
    code: str
    signal_date: str
    entry_date: str
    mark_date: str
    horizon: int
    base_close: float
    mark_high: float
    return_pct: float
    name: str = ""
    mark_low: float | None = None
    mark_close: float | None = None
    low_return_pct: float | None = None
    close_return_pct: float | None = None

    def to_ref(self) -> dict[str, Any]:
        """极端案例标注：个股 + 选股日/标记日 + 收益。"""
        return {
            "code": self.code,
            "name": self.name,
            "signal_date": self.signal_date,
            "entry_date": self.entry_date,
            "mark_date": self.mark_date,
            "return_pct": self.return_pct,
            "base_close": self.base_close,
            "mark_high": self.mark_high,
        }


@dataclass
class HorizonResult:
    strategy_slug: str
    entry_timing: str
    config: dict[str, Any] = field(default_factory=dict)
    horizons: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    events: list[HorizonEvent] = field(default_factory=list)

    def to_dict(self, *, include_events: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "strategy": self.strategy_slug,
            "mode": "horizon",
            "entry_timing": self.entry_timing,
            "config": self.config,
            "horizons": self.horizons,
            "skipped": self.skipped,
        }
        if include_events:
            body["events"] = [asdict(event) for event in self.events]
        return body


def entry_day_offset(entry_timing: str) -> int:
    """相对选股日 D 的入场偏移：次日入场时点 → +1，其余当日。"""
    if entry_timing in {"next_open", "next_dip"}:
        return 1
    return 0


def mark_day_offset(entry_timing: str, horizon: int) -> int:
    """相对选股日 D 的标记日偏移：E + N。"""
    return entry_day_offset(entry_timing) + max(1, int(horizon))


def aggregate_horizon_events(events: Sequence[HorizonEvent]) -> dict[str, Any] | None:
    """聚合 T+N 事件。不构造资金曲线——horizon 无真实持仓资金约束。"""
    if not events:
        return None
    from src.backtest.application.metrics import summarize_return_array

    high_stats = summarize_return_array([e.return_pct for e in events])
    best_ev = max(events, key=lambda e: e.return_pct)
    worst_ev = min(events, key=lambda e: e.return_pct)
    body: dict[str, Any] = {
        **high_stats,
        "best": round(float(best_ev.return_pct), 4),
        "worst": round(float(worst_ev.return_pct), 4),
        "best_event": best_ev.to_ref(),
        "worst_event": worst_ev.to_ref(),
        "mark_basis": "high",
        "mark_basis_note": (
            "主收益用标记日最高÷选股日收盘，属乐观上沿，不可当成可稳定兑现成交价"
        ),
        "by_month": _horizon_by_month(events),
    }

    close_vals = [
        float(e.close_return_pct)
        for e in events
        if e.close_return_pct is not None and np.isfinite(e.close_return_pct)
    ]
    if close_vals:
        close_stats = summarize_return_array(close_vals)
        body["close_n"] = close_stats["n"]
        body["close_avg"] = close_stats["avg"]
        body["close_median"] = close_stats["median"]
        body["close_win_rate"] = close_stats["win_rate"]
        body["close_best"] = close_stats["best"]
        body["close_worst"] = close_stats["worst"]
        body["close_note"] = (
            "标记日收盘÷选股日收盘；相对 high 口径更接近可兑现，仍非成交引擎净值"
        )
    return body


def _horizon_by_month(events: Sequence[HorizonEvent]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for event in events:
        key = str(event.signal_date)[:7]
        buckets.setdefault(key, []).append(float(event.return_pct))
    rows: list[dict[str, Any]] = []
    for period in sorted(buckets):
        arr = np.asarray(buckets[period], dtype=float)
        wins = int(np.sum(arr > 0))
        rows.append(
            {
                "period": period,
                "n": int(arr.size),
                "win_rate": round(float(wins / arr.size * 100.0), 2),
                "avg": round(float(arr.mean()), 4),
            }
        )
    return rows


def run_horizon_backtest(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    *,
    entry_timing: str,
    entry_price_panel: pd.DataFrame | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    strategy_slug: str = "",
) -> HorizonResult:
    """对信号面板按 T+N 窗口计价。signals 与 panels 必须同形。"""
    result = HorizonResult(strategy_slug=strategy_slug, entry_timing=entry_timing)
    clean_horizons = tuple(sorted({max(1, int(h)) for h in horizons})) or DEFAULT_HORIZONS
    result.config["horizons"] = list(clean_horizons)
    result.config["mark"] = "high"

    if signals.empty:
        result.skipped["无信号"] = 0
        result.horizons = {f"t{h}": None for h in clean_horizons}
        return result

    open_ = panels["open"]
    close = panels["close"]
    high = panels["high"]
    low = panels.get("low")
    volume = panels.get("volume")

    dates = list(signals.index)
    codes = list(signals.columns)
    open_a = open_.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float) if low is not None else None
    volume_a = volume.to_numpy(dtype=float) if volume is not None else None
    one_word = np.isclose(high_a, low_a) & np.isfinite(high_a) if low_a is not None else None

    entry_price_a: np.ndarray | None = None
    if entry_timing == "next_dip":
        if entry_price_panel is None:
            raise ValueError("entry_timing=next_dip 必须提供 entry_price_panel")
        entry_price_a = entry_price_panel.reindex(
            index=signals.index, columns=signals.columns
        ).to_numpy(dtype=float)

    e_off = entry_day_offset(entry_timing)
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    signal_rows, signal_cols = np.nonzero(signals.fillna(False).to_numpy(dtype=bool))
    events: list[HorizonEvent] = []
    by_horizon: dict[int, list[HorizonEvent]] = {h: [] for h in clean_horizons}

    for row, col in zip(signal_rows, signal_cols):
        base = close_a[row, col]
        if not np.isfinite(base) or base <= 0:
            skip("选股日无收盘价")
            continue

        entry_idx = row + e_off
        if entry_idx >= len(dates):
            skip("入场日超出数据范围")
            continue
        if volume_a is not None and not volume_a[entry_idx, col] > 0:
            skip("入场日停牌")
            continue
        if one_word is not None and one_word[entry_idx, col]:
            skip("入场日一字板买不进")
            continue
        if entry_timing == "next_dip":
            assert entry_price_a is not None
            target_price = entry_price_a[row, col]
            next_open = open_a[entry_idx, col]
            next_low = low_a[entry_idx, col] if low_a is not None else np.nan
            if not np.isfinite(target_price) or target_price <= 0:
                skip("次日低吸价无效")
                continue
            if not (
                (np.isfinite(next_open) and next_open <= target_price)
                or (np.isfinite(next_low) and next_low <= target_price)
            ):
                skip("次日低吸未触价")
                continue

        for horizon in clean_horizons:
            mark_idx = row + mark_day_offset(entry_timing, horizon)
            if mark_idx >= len(dates):
                skip(f"T+{horizon}标记日超出数据范围")
                continue
            mark_high = high_a[mark_idx, col]
            if not np.isfinite(mark_high) or mark_high <= 0:
                skip(f"T+{horizon}标记日无最高价")
                continue
            if volume_a is not None and not volume_a[mark_idx, col] > 0:
                skip(f"T+{horizon}标记日停牌")
                continue

            ret = (mark_high / base - 1.0) * 100.0
            mark_low_v = None
            mark_close_v = None
            low_ret = None
            close_ret = None
            if low_a is not None:
                lv = low_a[mark_idx, col]
                if np.isfinite(lv) and lv > 0:
                    mark_low_v = round(float(lv), 4)
                    low_ret = round(float((lv / base - 1.0) * 100.0), 4)
            cv = close_a[mark_idx, col]
            if np.isfinite(cv) and cv > 0:
                mark_close_v = round(float(cv), 4)
                close_ret = round(float((cv / base - 1.0) * 100.0), 4)

            event = HorizonEvent(
                code=codes[col],
                signal_date=str(dates[row]),
                entry_date=str(dates[entry_idx]),
                mark_date=str(dates[mark_idx]),
                horizon=horizon,
                base_close=round(float(base), 4),
                mark_high=round(float(mark_high), 4),
                return_pct=round(float(ret), 4),
                mark_low=mark_low_v,
                mark_close=mark_close_v,
                low_return_pct=low_ret,
                close_return_pct=close_ret,
            )
            events.append(event)
            by_horizon[horizon].append(event)

    result.events = events
    result.skipped = skipped
    result.horizons = {
        f"t{h}": aggregate_horizon_events(by_horizon[h]) for h in clean_horizons
    }
    return result


def attach_instrument_names(
    result: HorizonResult, name_by_code: dict[str, str]
) -> HorizonResult:
    """把证券简称写回极端案例与事件（可空）。"""
    if not name_by_code:
        return result
    for event in result.events:
        event.name = name_by_code.get(event.code, event.name)
    for stats in result.horizons.values():
        if not stats:
            continue
        for key in ("best_event", "worst_event"):
            ref = stats.get(key)
            if isinstance(ref, dict) and ref.get("code"):
                ref["name"] = name_by_code.get(str(ref["code"]), str(ref.get("name") or ""))
    return result
