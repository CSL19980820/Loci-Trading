"""Rank-lever diagnostics for qianlong / sanyuan. Does not change live engines.

Same gates, hold, stop, and costs as production. Only the cross-section pick
among already-eligible names changes. Every-fill overlapping sleeves.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import (  # noqa: E402
    BacktestConfig,
    execute_backtest_context,
    prepare_backtest_context,
)
from src.backtest.domain.models import Trade  # noqa: E402
from src.formula import REF  # noqa: E402
from src.market import MarketStore  # noqa: E402
from src.strategy import get  # noqa: E402

START = "2021-01-04"
END = "2026-08-12"
OUT = PROJECT_ROOT / "docs" / "research" / "_scratch_incumbent_rank_levers.json"


def _as_bool(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.fillna(False).astype(bool)


def _and(*masks: pd.DataFrame) -> pd.DataFrame:
    out = _as_bool(masks[0])
    for mask in masks[1:]:
        out = out & _as_bool(mask)
    return out


def _top_n(
    mask: pd.DataFrame,
    strength: pd.DataFrame,
    n: int,
    *,
    ascending: bool = False,
) -> pd.DataFrame:
    scores = strength.where(_as_bool(mask))
    rank = scores.rank(axis=1, ascending=ascending, method="first")
    return (_as_bool(mask) & rank.le(n)).fillna(False)


def _pool_stats(mask: pd.DataFrame, start: str, end: str) -> dict:
    window = mask.loc[start:end]
    daily = window.sum(axis=1)
    hit = daily[daily > 0]
    return {
        "signal_days": int(hit.size),
        "avg_names": round(float(hit.mean()), 3) if len(hit) else 0.0,
        "max_names": int(hit.max()) if len(hit) else 0,
    }


def overlapping_nav(trades: list[Trade], calendar: list[str], sleeve_days: int) -> dict:
    evaluable = [t for t in trades if t.exit_reason != "data_end"]
    n = len(calendar)
    index = {day: i for i, day in enumerate(calendar)}
    batch_sum = np.zeros(n, dtype="float64")
    batch_cnt = np.zeros(n, dtype="float64")
    for trade in evaluable:
        pos = index.get(str(trade.signal_date))
        if pos is None:
            continue
        batch_sum[pos] += float(trade.net_return_pct) / 100.0
        batch_cnt[pos] += 1.0
    batch_ret = np.divide(
        batch_sum, batch_cnt, out=np.zeros(n, dtype="float64"), where=batch_cnt > 0
    )
    k = max(1, int(sleeve_days))
    sleeves = np.ones((k, n), dtype="float64")
    invested = np.zeros((k, n), dtype=bool)
    for sleeve in range(k):
        value = 1.0
        for day in range(n):
            if day % k == sleeve and batch_cnt[day] > 0:
                value *= 1.0 + batch_ret[day]
                invested[sleeve, day : min(day + k, n)] = True
            sleeves[sleeve, day] = value
    curve = sleeves.mean(axis=0)
    peak = np.maximum.accumulate(curve)
    drawdown = curve / peak - 1.0
    year_end = []
    years = sorted({day[:4] for day in calendar})
    for year in years:
        last = max(i for i, day in enumerate(calendar) if day.startswith(year))
        year_end.append(
            {
                "year": year,
                "date": calendar[last],
                "nav": round(float(curve[last]) * 100.0, 4),
            }
        )
    return {
        "sleeve_days": k,
        "portfolio_return_pct": round(float(curve[-1] - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float(drawdown.min()) * 100.0, 4),
        "occupancy_pct": round(float(invested.mean()) * 100.0, 2),
        "signal_days": int((batch_cnt > 0).sum()),
        "filled_trades": int(batch_cnt.sum()),
        "year_end_nav": year_end,
    }


def _clip(signals: pd.DataFrame, start: str, end: str, index: pd.Index) -> pd.DataFrame:
    out = signals
    if start:
        out = out[out.index >= start]
    if end:
        out = out[out.index <= end]
    return out.reindex(index).fillna(False)


def _year_avgs(years: dict) -> dict:
    early = [years[y]["avg"] for y in ("2021", "2022", "2023") if y in years]
    late = [years[y]["avg"] for y in ("2024", "2025", "2026") if y in years]
    full = [years[y]["avg"] for y in ("2021", "2022", "2023", "2024", "2025") if y in years]
    negative = [
        y
        for y in ("2021", "2022", "2023", "2024", "2025")
        if y in years and years[y]["avg"] is not None and float(years[y]["avg"]) < 0
    ]
    return {
        "early_2021_2023": round(float(np.mean(early)), 4) if early else None,
        "late_2024_2026": round(float(np.mean(late)), 4) if late else None,
        "oos_2021_2025": round(float(np.mean(full)), 4) if full else None,
        "negative_years_2021_2025": negative,
        "pass_yearly": len(negative) == 0 and bool(full),
        "pass_split": bool(early)
        and bool(late)
        and float(np.mean(early)) >= 0
        and float(np.mean(late)) >= 0,
    }


def _summarize(result, calendar: list[str], sleeve_days: int) -> dict:
    stats = dict(result.metrics or {})
    by_year = stats.pop("by_year", None) or []
    years = {
        str(row["period"]): {
            "n": row.get("n"),
            "win_rate": row.get("win_rate"),
            "avg": row.get("avg"),
        }
        for row in by_year
        if isinstance(row, dict)
    }
    return {
        "trades": stats.get("trades"),
        "win_rate": stats.get("win_rate"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "avg_net": stats.get("avg_net_return"),
        "median": stats.get("median_net_return"),
        "portfolio": overlapping_nav(result.trades, calendar, sleeve_days),
        "years": years,
        "gate": _year_avgs(years),
        "skipped": dict(result.skipped or {}),
    }


def _run_mask(ctx: dict, mask: pd.DataFrame, calendar: list[str], sleeve_days: int) -> dict:
    run_ctx = dict(ctx)
    run_ctx["signals"] = _clip(mask, ctx["start"], ctx["end"], ctx["panels"]["close"].index)
    result = execute_backtest_context(None, run_ctx, use_fast=False)
    body = _summarize(result, calendar, sleeve_days)
    body["pool"] = _pool_stats(mask, ctx["start"], ctx["end"])
    return body


def _pct_chg(close: pd.DataFrame) -> pd.DataFrame:
    return (close / REF(close, 1) - 1.0) * 100.0


def _clv(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    high, low, close = panels["high"], panels["low"], panels["close"]
    spread = high - low
    return ((2 * close - high - low) / spread).where(spread != 0, 0.0)


def qianlong_masks(signal, panels: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    factors = signal.factors
    close = panels["close"]
    white = factors["辰星线"]
    eligible = _and(factors["条件候选"], factors["弱市可交易"])
    core = _and(
        factors["曾死叉"],
        factors["白线下运行"],
        factors["突破日"],
        factors["白线向上"],
        factors["非涨停价"],
        factors["弱市可交易"],
    )
    pct = _pct_chg(close)
    band = eligible & pct.gt(1.0) & pct.lt(5.0)
    extension = close / white - 1.0
    return {
        "live_roc5_top2": _as_bool(factors["每日前二"]),
        "eligible_all": eligible,
        "eligible_top2_pct_chg": _top_n(eligible, pct, 2),
        "eligible_top2_pct_band_1_5": _top_n(band, pct, 2),
        "eligible_top2_least_ext": _top_n(eligible, extension, 2, ascending=True),
        "core_no_to_top2_roc5": _top_n(core, factors["ROC5"], 2),
        "core_no_to_top2_least_ext": _top_n(core, extension, 2, ascending=True),
    }


def sanyuan_masks(signal, panels: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    factors = signal.factors
    eligible = _as_bool(factors["闸门后候选"])
    pct = _pct_chg(panels["close"])
    band = eligible & pct.gt(1.0) & pct.lt(5.0)
    rebound = _and(factors["B_双阴反包"], factors["弱市可交易_上涨家数>=40%"])
    clv = _clv(panels)
    return {
        "live_score_top2": _as_bool(factors["每日前二"]),
        "eligible_all": eligible,
        "eligible_top2_pct_chg": _top_n(eligible, pct, 2),
        "eligible_top2_pct_band_1_5": _top_n(band, pct, 2),
        "eligible_top2_clv_asc": _top_n(eligible, clv, 2, ascending=True),
        "double_yin_all": rebound,
        "double_yin_top2_pct_chg": _top_n(rebound, pct, 2),
    }


def _config_for(engine) -> BacktestConfig:
    return BacktestConfig(
        hold_days=int(getattr(engine, "screen_hold_days", 3) or 3),
        stop_loss_pct=getattr(engine, "screen_stop_loss_pct", None),
        take_profit_pct=None,
        commission_bps=3.0,
        stamp_duty_bps=5.0,
        slippage_bps=10.0,
        benchmark=None,
    )


def _run_engine(store: MarketStore, slug: str, mask_fn, calendar: list[str]) -> dict:
    engine = get(slug)
    cfg = _config_for(engine)
    print(f"load {slug} …", flush=True)
    ctx = prepare_backtest_context(
        store, engine, start=START, end=END, config=cfg
    )
    print(f"factors {slug} …", flush=True)
    signal = engine.compute(ctx["panels"], ctx["resolved_params"])
    masks = mask_fn(signal, ctx["panels"])
    sleeve_days = 1 + int(cfg.hold_days)
    variants = {}
    for name, mask in masks.items():
        print(f"  backtest {slug}/{name} …", flush=True)
        variants[name] = _run_mask(ctx, mask, calendar, sleeve_days)
        gate = variants[name]["gate"]
        print(
            f"    trades={variants[name]['trades']} avg={variants[name]['avg_net']} "
            f"port={variants[name]['portfolio']['portfolio_return_pct']} "
            f"neg={gate['negative_years_2021_2025']}",
            flush=True,
        )
    return {
        "slug": slug,
        "name": engine.name,
        "hold_days": int(cfg.hold_days),
        "sleeve_days": sleeve_days,
        "stop_loss_pct": cfg.stop_loss_pct,
        "variants": variants,
    }


def main() -> None:
    store = MarketStore()
    days = [d for d in store.trading_days() if START <= d <= END]
    payload = {
        "window": [START, END],
        "trading_days": len(days),
        "costs_bps": {"commission": 3.0, "stamp_duty": 5.0, "slippage": 10.0},
        "note": "live engines untouched; ranking/pool masks only",
        "engines": [
            _run_engine(store, "qianlong-close-v3", qianlong_masks, days),
            _run_engine(store, "sanyuan-tail-v1", sanyuan_masks, days),
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
