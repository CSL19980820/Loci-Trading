"""50/50 combo: qianlong V3.2 + yangshi vs qianlong V3.2 + sanyuan."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

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
OUT = PROJECT_ROOT / "docs" / "research" / "_scratch_ql_pair_combo.json"
SLUGS = ("qianlong-close-v3", "yangshi-tail-v1", "sanyuan-tail-v1")


def _config(engine) -> BacktestConfig:
    return BacktestConfig(
        hold_days=int(getattr(engine, "screen_hold_days", 3) or 3),
        stop_loss_pct=getattr(engine, "screen_stop_loss_pct", None),
        take_profit_pct=None,
        commission_bps=3.0,
        stamp_duty_bps=5.0,
        slippage_bps=10.0,
        benchmark=None,
    )


def sleeve_state(trades: list[Trade], calendar: list[str], sleeve_days: int) -> dict:
    evaluable = [t for t in trades if t.exit_reason != "data_end"]
    n = len(calendar)
    index = {day: i for i, day in enumerate(calendar)}
    batch_sum = np.zeros(n, dtype="float64")
    batch_cnt = np.zeros(n, dtype="float64")
    keys: set[tuple[str, str]] = set()
    by_day: dict[str, set[str]] = {}
    for trade in evaluable:
        keys.add((str(trade.signal_date), trade.code))
        by_day.setdefault(str(trade.signal_date), set()).add(trade.code)
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
    return {
        "curve": curve,
        "invested": invested.mean(axis=0),
        "batch_ret": batch_ret,
        "batch_cnt": batch_cnt,
        "keys": keys,
        "by_day": by_day,
        "k": k,
        "evaluable": evaluable,
    }


def _curve_stats(curve: np.ndarray, invested: np.ndarray, calendar: list[str]) -> dict:
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
    yearly_ret = []
    prev = 100.0
    for row in year_end:
        nav = row["nav"]
        yearly_ret.append(
            {
                "year": row["year"],
                "nav": nav,
                "ret_pct": round((nav / prev - 1.0) * 100.0, 2),
            }
        )
        prev = nav
    return {
        "portfolio_return_pct": round(float(curve[-1] - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float(drawdown.min()) * 100.0, 4),
        "occupancy_pct": round(float(invested.mean()) * 100.0, 2),
        "year_end_nav": year_end,
        "yearly_return": yearly_ret,
    }


def _trade_stats(trades: list[Trade]) -> dict:
    evaluable = [t for t in trades if t.exit_reason != "data_end"]
    if not evaluable:
        return {"trades": 0}
    net = np.array([t.net_return_pct for t in evaluable], dtype=float)
    wins = net[net > 0]
    losses = net[net <= 0]
    payoff = None
    if wins.size and losses.size and abs(float(losses.mean())) > 1e-9:
        payoff = round(float(wins.mean() / abs(losses.mean())), 3)
    return {
        "trades": int(net.size),
        "win_rate": round(float((net > 0).mean() * 100.0), 2),
        "payoff_ratio": payoff,
        "avg_net": round(float(net.mean()), 4),
        "median": round(float(np.median(net)), 4),
    }


def _overlap(left: dict, right: dict, calendar: list[str]) -> dict:
    keys_a, keys_b = left["keys"], right["keys"]
    shared = keys_a & keys_b
    days_a = {day for day, _code in keys_a}
    days_b = {day for day, _code in keys_b}
    both_days = days_a & days_b
    same_name_days = 0
    for day in both_days:
        if left["by_day"].get(day, set()) & right["by_day"].get(day, set()):
            same_name_days += 1
    mask = (left["batch_cnt"] > 0) | (right["batch_cnt"] > 0)
    corr = None
    if int(mask.sum()) >= 10:
        corr = round(float(np.corrcoef(left["batch_ret"][mask], right["batch_ret"][mask])[0, 1]), 3)
    return {
        "shared_trades": len(shared),
        "union_trades": len(keys_a | keys_b),
        "jaccard_pct": round(100.0 * len(shared) / len(keys_a | keys_b), 2) if keys_a or keys_b else 0.0,
        "days_a": len(days_a),
        "days_b": len(days_b),
        "both_fire_days": len(both_days),
        "same_name_days": same_name_days,
        "calendar_days": len(calendar),
        "daily_return_corr": corr,
    }


def _run_one(store: MarketStore, slug: str, calendar: list[str]) -> dict:
    engine = get(slug)
    cfg = _config(engine)
    print(f"load {slug} {engine.version} …", flush=True)
    ctx = prepare_backtest_context(store, engine, start=START, end=END, config=cfg)
    print(f"backtest {slug} …", flush=True)
    result = execute_backtest_context(None, ctx, use_fast=False)
    sleeve_days = 1 + int(cfg.hold_days)
    state = sleeve_state(result.trades, calendar, sleeve_days)
    stats = _trade_stats(result.trades)
    port = _curve_stats(state["curve"], state["invested"], calendar)
    print(
        f"  trades={stats['trades']} avg={stats['avg_net']} "
        f"port={port['portfolio_return_pct']} dd={port['max_drawdown_pct']}",
        flush=True,
    )
    return {
        "slug": slug,
        "name": engine.name,
        "version": engine.version,
        "hold_days": int(cfg.hold_days),
        "sleeve_days": sleeve_days,
        "stop_loss_pct": cfg.stop_loss_pct,
        "top_n": int(getattr(engine, "screen_top_n", 0) or 0),
        "stats": stats,
        "portfolio": port,
        "state": state,
    }


def _pair(left: dict, right: dict, calendar: list[str], label: str) -> dict:
    curve = 0.5 * left["state"]["curve"] + 0.5 * right["state"]["curve"]
    invested = 0.5 * left["state"]["invested"] + 0.5 * right["state"]["invested"]
    return {
        "label": label,
        "legs": [left["slug"], right["slug"]],
        "allocation": "50/50 capital, independent overlapping sleeves",
        "portfolio": _curve_stats(curve, invested, calendar),
        "overlap": _overlap(left["state"], right["state"], calendar),
    }


def _public(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "state"}


def main() -> None:
    store = MarketStore()
    calendar = [d for d in store.trading_days() if START <= d <= END]
    rows = {slug: _run_one(store, slug, calendar) for slug in SLUGS}
    ql, ys, sy = (rows[slug] for slug in SLUGS)
    payload = {
        "window": [START, END],
        "trading_days": len(calendar),
        "costs_bps": {"commission": 3.0, "stamp_duty": 5.0, "slippage": 10.0},
        "engines": [_public(rows[slug]) for slug in SLUGS],
        "pairs": [
            _pair(ql, ys, calendar, "潜龙V3.2 + 杨氏"),
            _pair(ql, sy, calendar, "潜龙V3.2 + 三源"),
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for pair in payload["pairs"]:
        port = pair["portfolio"]
        ov = pair["overlap"]
        print(
            f"{pair['label']}: port={port['portfolio_return_pct']} "
            f"dd={port['max_drawdown_pct']} occ={port['occupancy_pct']} "
            f"jaccard={ov['jaccard_pct']} corr={ov['daily_return_corr']}",
            flush=True,
        )
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
