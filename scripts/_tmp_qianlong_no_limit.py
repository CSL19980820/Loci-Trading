"""Qianlong V3.2 with vs without T-day limit-up close filter. Live params untouched."""
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
from src.market import MarketStore  # noqa: E402
from src.strategy import get  # noqa: E402

START = "2021-01-04"
END = "2026-08-12"
OUT = PROJECT_ROOT / "docs" / "research" / "_scratch_qianlong_no_limit_filter.json"


def _as_bool(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.fillna(False).astype(bool)


def _and(*masks: pd.DataFrame) -> pd.DataFrame:
    out = _as_bool(masks[0])
    for mask in masks[1:]:
        out = out & _as_bool(mask)
    return out


def _top_n(mask: pd.DataFrame, strength: pd.DataFrame, n: int) -> pd.DataFrame:
    rank = strength.where(_as_bool(mask)).rank(axis=1, ascending=False, method="first")
    return (_as_bool(mask) & rank.le(n)).fillna(False)


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
    years = sorted({day[:4] for day in calendar})
    year_end = []
    for year in years:
        last = max(i for i, day in enumerate(calendar) if day.startswith(year))
        year_end.append(
            {"year": year, "date": calendar[last], "nav": round(float(curve[last]) * 100.0, 4)}
        )
    return {
        "sleeve_days": k,
        "portfolio_return_pct": round(float(curve[-1] - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float((curve / peak - 1.0).min()) * 100.0, 4),
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


def _pool(mask: pd.DataFrame) -> dict:
    window = mask.loc[START:END]
    daily = window.sum(axis=1)
    hit = daily[daily > 0]
    return {
        "signal_days": int(hit.size),
        "avg_names": round(float(hit.mean()), 3) if len(hit) else 0.0,
        "max_names": int(hit.max()) if len(hit) else 0,
    }


def _summarize(result, calendar: list[str], sleeve_days: int) -> dict:
    stats = dict(result.metrics or {})
    by_year = stats.pop("by_year", None) or []
    years = {
        str(row["period"]): {"n": row.get("n"), "win_rate": row.get("win_rate"), "avg": row.get("avg")}
        for row in by_year
        if isinstance(row, dict)
    }
    negative = [
        y
        for y in ("2021", "2022", "2023", "2024", "2025")
        if y in years and years[y]["avg"] is not None and float(years[y]["avg"]) < 0
    ]
    return {
        "trades": stats.get("trades"),
        "win_rate": stats.get("win_rate"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "avg_net": stats.get("avg_net_return"),
        "median": stats.get("median_net_return"),
        "portfolio": overlapping_nav(result.trades, calendar, sleeve_days),
        "years": years,
        "negative_years_2021_2025": negative,
        "skipped": dict(result.skipped or {}),
    }


def main() -> None:
    engine = get("qianlong-close-v3")
    cfg = BacktestConfig(
        hold_days=int(engine.screen_hold_days),
        stop_loss_pct=engine.screen_stop_loss_pct,
        take_profit_pct=None,
        commission_bps=3.0,
        stamp_duty_bps=5.0,
        slippage_bps=10.0,
        benchmark=None,
    )
    store = MarketStore()
    calendar = [d for d in store.trading_days() if START <= d <= END]
    print(f"load {engine.name} …", flush=True)
    ctx = prepare_backtest_context(store, engine, start=START, end=END, config=cfg)
    signal = engine.compute(ctx["panels"], ctx["resolved_params"])
    factors = signal.factors
    live = _as_bool(signal.signals)
    core_no_limit = _and(
        factors["曾死叉"],
        factors["白线下运行"],
        factors["突破日"],
        factors["白线向上"],
    )
    eligible = _and(core_no_limit, factors["换手过滤"], factors["弱市可交易"])
    no_limit = _top_n(eligible, factors["白线贴近度"], 2)
    at_limit = _as_bool(~factors["非涨停价"])
    picked_limit = (no_limit & at_limit).loc[START:END]
    sleeve_days = 1 + int(cfg.hold_days)
    out = {}
    for name, mask in (("live_block_limit", live), ("allow_limit_close", no_limit)):
        print(f"backtest {name} …", flush=True)
        run_ctx = dict(ctx)
        run_ctx["signals"] = _clip(mask, START, END, ctx["panels"]["close"].index)
        result = execute_backtest_context(None, run_ctx, use_fast=False)
        body = _summarize(result, calendar, sleeve_days)
        body["pool"] = _pool(mask)
        out[name] = body
        print(
            f"  trades={body['trades']} avg={body['avg_net']} "
            f"port={body['portfolio']['portfolio_return_pct']} "
            f"dd={body['portfolio']['max_drawdown_pct']} "
            f"skip={body['skipped']} neg={body['negative_years_2021_2025']}",
            flush=True,
        )
    payload = {
        "window": [START, END],
        "trading_days": len(calendar),
        "note": "live untouched; only drop 非涨停价 before closeness Top2",
        "limit_close_picks": {
            "signal_days": int((picked_limit.sum(axis=1) > 0).sum()),
            "names": int(picked_limit.sum().sum()),
        },
        "variants": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
