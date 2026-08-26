"""2026 YTD backtest of live qianlong V3.2 vs archived ROC5 Top2."""
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

START = "2026-01-05"
END = "2026-08-12"
OUT = PROJECT_ROOT / "docs" / "research" / "_scratch_qianlong_v32_2026.json"


def _as_bool(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.fillna(False).astype(bool)


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
    month_end = []
    months = []
    for i, day in enumerate(calendar):
        key = day[:7]
        if not months or months[-1] != key:
            months.append(key)
        month_end.append((key, i))
    last_by_month = {}
    for key, i in month_end:
        last_by_month[key] = i
    return {
        "sleeve_days": k,
        "portfolio_return_pct": round(float(curve[-1] - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float((curve / peak - 1.0).min()) * 100.0, 4),
        "occupancy_pct": round(float(invested.mean()) * 100.0, 2),
        "signal_days": int((batch_cnt > 0).sum()),
        "filled_trades": int(batch_cnt.sum()),
        "month_end_nav": [
            {
                "month": month,
                "date": calendar[i],
                "nav": round(float(curve[i]) * 100.0, 4),
            }
            for month, i in last_by_month.items()
        ],
    }


def _clip(signals: pd.DataFrame, start: str, end: str, index: pd.Index) -> pd.DataFrame:
    out = signals
    if start:
        out = out[out.index >= start]
    if end:
        out = out[out.index <= end]
    return out.reindex(index).fillna(False)


def _summarize(result, calendar: list[str], sleeve_days: int) -> dict:
    stats = dict(result.metrics or {})
    months = stats.pop("by_month", None) or []
    for drop in ("percentiles", "return_distribution", "by_year"):
        stats.pop(drop, None)
    return {
        "trades": stats.get("trades"),
        "win_rate": stats.get("win_rate"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "avg_net": stats.get("avg_net_return"),
        "median": stats.get("median_net_return"),
        "avg_win": stats.get("avg_win"),
        "avg_loss": stats.get("avg_loss"),
        "best": stats.get("best"),
        "worst": stats.get("worst"),
        "exit_reasons": stats.get("exit_reasons"),
        "portfolio": overlapping_nav(result.trades, calendar, sleeve_days),
        "months": months,
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
    days = [d for d in store.trading_days() if START <= d <= END]
    print(f"{engine.name} {engine.version} rank={engine.screen_rank_factor}", flush=True)
    print(f"load {START}..{END} ({len(days)} days) …", flush=True)
    ctx = prepare_backtest_context(store, engine, start=START, end=END, config=cfg)
    signal = engine.compute(ctx["panels"], ctx["resolved_params"])
    eligible = _as_bool(signal.factors["条件候选"]) & _as_bool(
        signal.factors["弱市可交易"]
    )
    masks = {
        "v32_chenxing": _as_bool(signal.signals),
        "v31_roc5": _top_n(eligible, signal.factors["ROC5"], 2),
    }
    sleeve_days = 1 + int(cfg.hold_days)
    variants = {}
    for name, mask in masks.items():
        run_ctx = dict(ctx)
        run_ctx["signals"] = _clip(mask, START, END, ctx["panels"]["close"].index)
        print(f"backtest {name} …", flush=True)
        result = execute_backtest_context(None, run_ctx, use_fast=False)
        variants[name] = _summarize(result, days, sleeve_days)
        body = variants[name]
        print(
            f"  trades={body['trades']} wr={body['win_rate']} avg={body['avg_net']} "
            f"port={body['portfolio']['portfolio_return_pct']} dd={body['portfolio']['max_drawdown_pct']}",
            flush=True,
        )
    payload = {
        "window": [START, END],
        "trading_days": len(days),
        "engine": {
            "slug": engine.slug,
            "name": engine.name,
            "version": engine.version,
            "revision": engine.strategy_revision,
            "rank": engine.screen_rank_factor,
        },
        "costs_bps": {"commission": 3.0, "stamp_duty": 5.0, "slippage": 10.0},
        "variants": variants,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
