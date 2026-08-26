"""Qianlong V3.2 turnover cap 8% vs 15%. Does not change live params."""
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
OUT = PROJECT_ROOT / "docs" / "research" / "_scratch_qianlong_turnover15.json"


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


def _pool(mask: pd.DataFrame, start: str, end: str) -> dict:
    daily = mask.loc[start:end].sum(axis=1)
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
    print(f"load {engine.name} {engine.version} …", flush=True)
    ctx = prepare_backtest_context(store, engine, start=START, end=END, config=cfg)
    sleeve_days = 1 + int(cfg.hold_days)
    variants = {
        "to_3p5_8": {"turnover_min": 0.035, "turnover_max": 0.08},
        "to_3p5_15": {"turnover_min": 0.035, "turnover_max": 0.15},
    }
    out = {}
    for name, extra in variants.items():
        print(f"compute {name} …", flush=True)
        signal = engine.compute(ctx["panels"], {**ctx["resolved_params"], **extra})
        eligible = signal.factors["条件候选"] & signal.factors["弱市可交易"]
        run_ctx = dict(ctx)
        run_ctx["signals"] = _clip(
            signal.signals, START, END, ctx["panels"]["close"].index
        )
        print(f"backtest {name} …", flush=True)
        result = execute_backtest_context(None, run_ctx, use_fast=False)
        body = _summarize(result, calendar, sleeve_days)
        body["pool"] = _pool(eligible.fillna(False).astype(bool), START, END)
        body["turnover"] = extra
        out[name] = body
        print(
            f"  trades={body['trades']} avg={body['avg_net']} "
            f"port={body['portfolio']['portfolio_return_pct']} "
            f"dd={body['portfolio']['max_drawdown_pct']} "
            f"neg={body['negative_years_2021_2025']}",
            flush=True,
        )
    payload = {
        "window": [START, END],
        "trading_days": len(calendar),
        "note": "live engine untouched; turnover_max override only; V3.2 closeness rank",
        "variants": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
