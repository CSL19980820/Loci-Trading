"""Seven-month frozen-input research; reuse Loci's execution engine, never trade live."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, run_backtest


VARIANTS = {
    "breakout20": {"breakout": 20, "hold": 40, "stop": -6.0},
    "breakout60": {"breakout": 60, "hold": 60, "stop": -6.0},
    "momentum120": {"breakout": 0, "hold": 20, "stop": None},
    "quiet_breakout20": {"breakout": 20, "hold": 40, "stop": -6.0, "style": "quiet"},
    "quiet_breakout60": {"breakout": 60, "hold": 60, "stop": -6.0, "style": "quiet"},
    "trend_pullback": {"breakout": 0, "hold": 20, "stop": -6.0, "style": "pullback"},
}
PERIODS = {"train": ("2025-02-01", "2025-08-31"),
           "validation": ("2026-02-01", "2026-08-31")}


def features(frame: pd.DataFrame, breakout: int, style: str = "strength") -> pd.DataFrame:
    """All rolling windows end on or before the signal close."""
    close = frame.close * frame.factor
    high = frame.high * frame.factor
    ma120 = close.rolling(120).mean()
    liquid = (frame.close * frame.volume).rolling(20).mean() >= 50_000_000
    eligible = (liquid & (frame.close >= 5) & (frame.volume > 0)
                & (close > ma120) & (ma120 > ma120.shift(20))
                & (close > close.rolling(50).mean()))
    if breakout:
        eligible &= (close > high.rolling(breakout).max().shift(1))
        eligible &= frame.volume > frame.volume.rolling(20).mean().shift(1) * 1.2
    score = close / close.shift(120) - 1
    if style == "quiet":
        returns = close.pct_change(fill_method=None)
        vol20 = returns.rolling(20).std()
        eligible &= (vol20 < returns.rolling(60).std()) & (close / close.rolling(50).mean() < 1.15)
        score = -vol20
    if style == "pullback":
        return3 = close / close.shift(3) - 1
        eligible &= return3.between(-.08, -.04)
        score = -return3
    return pd.DataFrame({"eligible": eligible.fillna(False), "score": score})


def load_frame(db: sqlite3.Connection, code: str, dates: list[str]) -> pd.DataFrame:
    frame = pd.read_sql_query("SELECT trade_date,open,high,low,close,volume FROM quotes_daily "
                              "WHERE code=? ORDER BY trade_date", db, params=(code,))
    frame = frame.set_index("trade_date").reindex(dates)
    factors = db.execute("SELECT trade_date,hfq_factor FROM adjust_factors "
                         "WHERE code=? ORDER BY trade_date", (code,)).fetchall()
    if factors:
        series = pd.Series(dict(factors), dtype=float)
        frame["factor"] = series.reindex(series.index.union(frame.index)).sort_index().ffill().reindex(frame.index).fillna(1)
    else:
        frame["factor"] = 1.0
    return frame


def rank_candidates(db: sqlite3.Connection, dates: list[str], universe: list[tuple]) -> dict:
    choices = {phase: {key: {} for key in VARIANTS} for phase in PERIODS}
    eligible_counts = Counter()
    for number, (code, name, listed) in enumerate(universe):
        frame = load_frame(db, code, dates)
        for key, variant in VARIANTS.items():
            computed = features(frame, variant["breakout"], variant.get("style", "strength"))
            for phase, (start, end) in PERIODS.items():
                phase_dates = [day for day in dates if start <= day <= end]
                if key == "momentum120":
                    phase_dates = phase_dates[::21]
                for day in phase_dates:
                    if not bool(computed.at[day, "eligible"]):
                        continue
                    if not listed or (pd.Timestamp(day) - pd.Timestamp(listed)).days < 180:
                        continue
                    score = float(computed.at[day, "score"])
                    if not np.isfinite(score):
                        continue
                    eligible_counts[(phase, key)] += 1
                    bucket = choices[phase][key].setdefault(day, [])
                    bucket.append({"code": code, "name": name, "score": score})
                    bucket.sort(key=lambda row: (-row["score"], row["code"]))
                    del bucket[10:]
        if number % 500 == 0:
            print(f"ranked {number}/{len(universe)}", flush=True)
    return {"choices": choices, "eligible_counts": {"/".join(k): v for k, v in eligible_counts.items()}}


def event_trades(db: sqlite3.Connection, dates: list[str], choices: dict,
                 variant: dict, end: str, stop_override: float | None = None) -> tuple:
    codes = sorted({item["code"] for rows in choices.values() for item in rows})
    bounded_dates = [day for day in dates if day <= end]
    events, marks, raw_entries, factors, skips = {}, {}, {}, {}, Counter()
    cfg = BacktestConfig(hold_days=variant["hold"], stop_loss_pct=variant["stop"]
                         if stop_override is None else stop_override,
                         commission_bps=3.1, stamp_duty_bps=5, slippage_bps=5, benchmark=None)
    for code in codes:
        frame = load_frame(db, code, bounded_dates)
        signals = pd.DataFrame(False, index=bounded_dates, columns=[code])
        for day, rows in choices.items():
            if any(row["code"] == code for row in rows):
                signals.at[day, code] = True
        # A next-open order at an apparent main-board limit-up is not guaranteed a fill.
        # This filter uses the open and prior adjusted close; no intraday unlock is assumed.
        open_return = (frame.open * frame.factor) / (frame.close * frame.factor).shift(1) - 1
        blocked_entries = open_return >= .095
        skipped_signals = signals[code] & blocked_entries.shift(-1, fill_value=False)
        skips["open_near_upper_limit"] += int(skipped_signals.sum())
        signals.loc[skipped_signals, code] = False
        panels = {field: pd.DataFrame({code: frame[field] * frame.factor}, index=frame.index)
                  for field in ("open", "high", "low", "close")}
        panels["volume"] = pd.DataFrame({code: frame.volume}, index=frame.index)
        result = run_backtest(signals, panels, entry_timing="next_open", config=cfg)
        skips.update(result.skipped)
        if result.skipped.get("持有期内始终无法卖出", 0):
            raise ValueError(f"Unresolved exit for {code}: cannot silently omit a held position")
        for trade in result.trades:
            events[(trade.signal_date, code)] = asdict(trade)
            raw_entries[(trade.entry_date, code)] = float(frame.at[trade.entry_date, "open"])
            factors[(trade.entry_date, code)] = float(frame.at[trade.entry_date, "factor"])
        marks[code] = (frame.close * frame.factor).ffill()
    return events, marks, raw_entries, factors, dict(skips)


def trade_metrics(trades: list[dict]) -> dict:
    values = np.array([row["net_return_pct"] for row in trades], dtype=float)
    pnl = np.array([row["pnl"] for row in trades], dtype=float)
    wins, losses = values[values > 0], values[values < 0]
    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": float((values > 0).mean() * 100) if len(values) else None,
        "avg_win_pct": float(wins.mean()) if len(wins) else None,
        "avg_loss_pct": float(losses.mean()) if len(losses) else None,
        "payoff_ratio": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
        "profit_factor": float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else None,
        "expectancy_pct": float(values.mean()) if len(values) else None,
        "total_realized_pnl": float(pnl.sum()),
        "best_trade_pct": float(values.max()) if len(values) else None,
        "worst_trade_pct": float(values.min()) if len(values) else None,
        "profit_after_removing_best_three": float(pnl.sum() - np.sort(pnl[pnl > 0])[-3:].sum()),
    }


def account(choices: dict, events: dict, marks: dict, raw: dict, factors: dict,
            dates: list[str], *, cost_multiplier: float = 1,
            max_positions: int = 10, slot_capital: float = 20_000,
            risk_budget: float | None = None, max_per_theme: int | None = None,
            reserve_orders: bool = False) -> dict:
    """Allocate ranked signals without consulting outcomes; preserve open end positions."""
    cash, initial = 200_000.0, 200_000.0
    positions, closed, daily = {}, [], []
    skipped = Counter()
    prior = None
    for day in dates:
        submitted, reserved_cash = 0, 0.0
        opening_slots = max_positions - len(positions)
        opening_themes = Counter(p.get("theme") for p in positions.values()) if reserve_orders else None
        # Entries precede exits; proceeds from today's sale cannot fund today's open.
        for candidate in choices.get(prior, []) if prior else []:
            code = candidate["code"]
            if code in positions:
                skipped["already_held"] += 1
                continue
            if len(positions) >= max_positions:
                skipped["slots_full"] += 1
                break
            if reserve_orders and submitted >= opening_slots:
                skipped["order_slots_reserved"] += 1
                break
            theme_count = opening_themes[candidate.get("theme")] if reserve_orders else sum(
                p.get("theme") == candidate.get("theme") for p in positions.values())
            if max_per_theme is not None and theme_count >= max_per_theme:
                skipped["theme_capacity"] += 1
                continue
            order_budget = min(slot_capital, max(0.0, cash - reserved_cash))
            if reserve_orders:
                submitted += 1
                reserved_cash += order_budget
                opening_themes[candidate.get("theme")] += 1
            trade = events.get((prior, code))
            if trade is None:
                skipped["entry_not_executable"] += 1
                continue
            assert trade["entry_date"] == day
            raw_price = raw[(day, code)]
            if reserve_orders:
                reserved_cash -= order_budget
            budget = min(order_budget, max(0.0, cash - reserved_cash))
            if risk_budget is not None:
                assert float(trade["risk_pct"]) > 0
                budget = min(budget, risk_budget / (float(trade["risk_pct"]) / 100))
            quantity = int(budget / (raw_price * 1.002) / 100) * 100
            if quantity <= 0:
                skipped["cash_or_lot"] += 1
                continue
            notional = quantity * raw_price
            buy_cost = (max(5.0, notional * .0003) + notional * .00051) * cost_multiplier
            if notional + buy_cost > cash:
                skipped["cash"] += 1
                continue
            cash -= notional + buy_cost
            positions[code] = {**trade, "quantity": quantity, "notional": notional,
                               "buy_cost": buy_cost, "entry_factor": factors[(day, code)],
                               "name": candidate["name"], "score": candidate["score"]}
            if "theme" in candidate:
                positions[code]["theme"] = candidate["theme"]
        for code, position in list(positions.items()):
            if position["exit_reason"] == "data_end" or position["exit_date"] != day:
                continue
            value = position["notional"] * (1 + position["gross_return_pct"] / 100)
            sell_cost = (max(5.0, value * .0003) + value * .00101) * cost_multiplier
            cash += value - sell_cost
            pnl = value - sell_cost - position["notional"] - position["buy_cost"]
            closed.append({**position, "sell_cost": sell_cost, "pnl": pnl,
                           "net_return_pct": pnl / position["notional"] * 100})
            del positions[code]
        market_value = sum(p["quantity"] * float(marks[c].loc[day]) / p["entry_factor"]
                           for c, p in positions.items())
        assert cash >= -1e-6 and len(positions) <= max_positions
        daily.append({"date": day, "equity": cash + market_value, "cash": cash,
                      "open_positions": len(positions), "market_value": market_value})
        prior = day
    curve = np.array([initial] + [day["equity"] for day in daily])
    assert np.isfinite(curve).all()
    open_pnl = sum(p["quantity"] * float(marks[c].loc[dates[-1]]) / p["entry_factor"]
                   - p["notional"] - p["buy_cost"] for c, p in positions.items())
    assert abs(curve[-1] - initial - sum(t["pnl"] for t in closed) - open_pnl) < .01
    monthly, previous = {}, initial
    for month in sorted({day["date"][:7] for day in daily}):
        rows = [day for day in daily if day["date"].startswith(month)]
        monthly[month] = (rows[-1]["equity"] / previous - 1) * 100
        previous = rows[-1]["equity"]
    metrics = trade_metrics(closed)
    metrics.update({"return_pct": (curve[-1] / initial - 1) * 100,
                    "max_drawdown_pct": float((curve / np.maximum.accumulate(curve) - 1).min() * 100),
                    "ending_equity": float(curve[-1]), "unrealized_net_buy_cost_pnl": open_pnl,
                    "open_positions": len(positions), "trading_days": len(dates),
                    "monthly_return_pct": monthly, "cost_multiplier": cost_multiplier})
    return {"metrics": metrics, "trades": closed, "daily": daily,
            "open_positions": list(positions.values()), "skipped": dict(skipped)}


def evaluate(db: sqlite3.Connection, all_dates: list[str], choices: dict, phase: str,
             variant: dict, stop: float | None = None) -> tuple:
    start, end = PERIODS[phase]
    data = event_trades(db, all_dates, choices, variant, end, stop)
    dates = [day for day in all_dates if start <= day <= end]
    result = account(choices, *data[:4], dates)
    result["execution_skipped"] = data[4]
    return result, account(choices, *data[:4], dates, cost_multiplier=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    dates = [row[0] for row in db.execute("SELECT trade_date FROM trading_calendar ORDER BY trade_date")]
    universe = db.execute("SELECT code,name,list_date FROM instruments WHERE instrument_type='STOCK' "
                          "AND (code LIKE '60%' OR code LIKE '00%') "
                          "AND upper(name) NOT LIKE '%ST%' AND name NOT LIKE '%退%' ORDER BY code").fetchall()
    frozen = rank_candidates(db, dates, universe)
    (args.output / "signals.json").write_text(json.dumps(frozen, ensure_ascii=False), encoding="utf-8")
    report = {"periods": PERIODS, "variants": VARIANTS, "universe_count": len(universe),
              "snapshot_sha256": hashlib.file_digest(args.db.open("rb"), "sha256").hexdigest(),
              "results": {}, "status": "exploratory_non_pit_survivor_universe"}
    for key, variant in VARIANTS.items():
        result, _ = evaluate(db, dates, frozen["choices"]["train"][key], "train", variant)
        report["results"][f"train/{key}"] = result
        print("TRAIN", key, json.dumps(result["metrics"]), flush=True)
    # Selection uses only the prior-year sample. No high-payoff winner is forced.
    qualified = [key for key in VARIANTS if
                 (report["results"][f"train/{key}"]["metrics"]["payoff_ratio"] or 0) >= 2
                 and report["results"][f"train/{key}"]["metrics"]["trades"] >= 30
                 and report["results"][f"train/{key}"]["metrics"]["return_pct"] > 0
                 and report["results"][f"train/{key}"]["metrics"]["max_drawdown_pct"] > -20]
    selected = max(qualified, key=lambda key: report["results"][f"train/{key}"]["metrics"]["profit_factor"] or 0) if qualified else None
    report["selected_on_train"] = selected
    (args.output / "selection_before_validation.json").write_text(json.dumps({
        "selected": selected, "qualified": qualified,
        "training_metrics": {key: report["results"][f"train/{key}"]["metrics"] for key in VARIANTS}
    }, indent=2), encoding="utf-8")
    for key, variant in VARIANTS.items():
        result, stress = evaluate(db, dates, frozen["choices"]["validation"][key], "validation", variant)
        report["results"][f"validation/{key}"] = result
        report["results"][f"double_cost/{key}"] = stress
        print("VALIDATION", key, json.dumps(result["metrics"]), flush=True)
    if selected and VARIANTS[selected]["stop"] is not None:
        for stop in (-4.0, -8.0):
            result, _ = evaluate(db, dates, frozen["choices"]["validation"][selected],
                                 "validation", VARIANTS[selected], stop)
            report["results"][f"sensitivity_stop{stop}"] = result
    benchmark = db.execute("SELECT trade_date,close FROM quotes_daily WHERE code='000300' "
                           "AND trade_date BETWEEN '2026-01-30' AND '2026-08-31' ORDER BY trade_date").fetchall()
    report["benchmark"] = {"name": "CSI300 price index, no dividends", "first": benchmark[0],
                            "last": benchmark[-1], "return_pct": (benchmark[-1][1] / benchmark[0][1] - 1) * 100}
    (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("FINISHED", json.dumps({"selected": selected, "benchmark": report["benchmark"]}), flush=True)


if __name__ == "__main__":
    main()
