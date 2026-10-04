"""Apply a fixed cash/position budget to an already frozen research trade stream.

This is a conservative daily capacity overlay, not a broker or lot-size simulator.
It never searches strategy parameters and never refills an unavailable candidate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

INITIAL_CAPITAL = 1_000_000.0
POSITION_BUDGET = 100_000.0
MAX_POSITIONS = 10
MAX_NEW_POSITIONS_PER_DAY = 2
COST_PCT = 0.21
ENTRY_COST_PCT = 0.08
EXIT_COST_PCT = 0.13


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_trades(path: Path, start: str, end: str) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    seen = set()
    entry_counts = defaultdict(int)
    for row in rows:
        for field in ("entry_price", "exit_price", "entry_factor", "exit_factor",
                      "gross_return_pct", "net_return_pct"):
            row[field] = float(row[field])
            if not math.isfinite(row[field]):
                raise ValueError(f"Nonfinite {field}: {row['code']}")
        if not start <= row["entry_date"] < row["exit_date"] <= end:
            raise ValueError("Every supplied event must be closed in-period and obey T+1")
        if row.get("exit_reason") == "data_end":
            raise ValueError("Unresolved positions must not enter a closed-event overlay")
        if min(row[k] for k in ("entry_price", "exit_price", "entry_factor", "exit_factor")) <= 0:
            raise ValueError("Prices and economic factors must be positive")
        implied = (row["exit_price"] * row["exit_factor"] /
                   (row["entry_price"] * row["entry_factor"]) - 1) * 100
        if abs(implied-row["gross_return_pct"]) > 1e-7:
            raise ValueError("Economic price return differs from frozen event")
        if abs(row["gross_return_pct"]-COST_PCT-row["net_return_pct"]) > 1e-7:
            raise ValueError("Unexpected event cost; this audit freezes 0.21 percent")
        key = row["code"], row["entry_date"]
        if key in seen:
            raise ValueError(f"Duplicate supplied entry {key}")
        seen.add(key)
        entry_counts[row["entry_date"]] += 1
    if any(n > MAX_NEW_POSITIONS_PER_DAY for n in entry_counts.values()):
        raise ValueError("Upstream must freeze daily Top2 before order fills; do not select from hindsight-filled trades")
    return rows


def price_marks(db: Path, trades: list[dict], start: str, end: str):
    conn = sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    try:
        days = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM quotes_daily WHERE trade_date BETWEEN ? AND ? "
            "ORDER BY trade_date", (start, end))]
        codes = sorted({t["code"] for t in trades})
        marks = {}
        entry_factors = {}
        entry_keys = {(t["entry_date"], t["code"]) for t in trades}
        quote_pairs = 0
        for offset in range(0, len(codes), 400):
            batch = codes[offset:offset+400]
            slots = ",".join("?" for _ in batch)
            factors = defaultdict(list)
            for code, day, factor in conn.execute(
                f"SELECT code,trade_date,hfq_factor FROM adjust_factors "
                f"WHERE code IN ({slots}) AND trade_date<=? ORDER BY code,trade_date",
                [*batch, end],
            ):
                factors[code].append((day, float(factor)))
            quotes = defaultdict(dict)
            for code, day, close in conn.execute(
                f"SELECT code,trade_date,close FROM quotes_daily WHERE code IN ({slots}) "
                "AND trade_date BETWEEN ? AND ? ORDER BY code,trade_date",
                [*batch, start, end],
            ):
                if close is not None and math.isfinite(close) and close > 0:
                    quotes[code][day] = float(close)
            for code in batch:
                changes = factors[code]
                j, current = 0, None
                for day in days:
                    while j < len(changes) and changes[j][0] <= day:
                        current = changes[j][1]
                        j += 1
                    if day in quotes[code]:
                        if current is None or not math.isfinite(current) or current <= 0:
                            raise ValueError(f"Missing economic factor {code} {day}")
                        marks[(day, code)] = quotes[code][day] * current
                        if (day, code) in entry_keys:
                            entry_factors[(day, code)] = current
                        quote_pairs += 1
        for trade in trades:
            observed = entry_factors.get((trade["entry_date"], trade["code"]))
            if observed is None or not math.isclose(observed, trade["entry_factor"], rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f"Entry factor differs from snapshot: {trade['code']} {trade['entry_date']}")
        return days, marks, quote_pairs
    finally:
        conn.close()


def simulate(days: list[str], trades: list[dict], marks: dict, cost_pct: float):
    by_day = defaultdict(list)
    for trade in trades:
        by_day[trade["entry_date"]].append(trade)
    if set(by_day) - set(days):
        raise ValueError("Entry dates missing from the common trading calendar")
    cash, peak = INITIAL_CAPITAL, INITIAL_CAPITAL
    fee_scale = cost_pct/COST_PCT
    entry_notional = POSITION_BUDGET/(1+ENTRY_COST_PCT*fee_scale/100)
    exit_fee_rate = EXIT_COST_PCT*fee_scale/100
    held, daily, decisions, accepted = {}, [], [], []
    stale_marks = 0
    for day in days:
        new_count = 0
        for row in sorted(by_day[day], key=lambda r: r["code"]):
            code = row["code"]
            if code in held:
                reason = "same_code_held_including_exit_day"
            elif new_count >= MAX_NEW_POSITIONS_PER_DAY:
                reason = "daily_entry_quota"
            elif len(held) >= MAX_POSITIONS:
                reason = "position_capacity"
            elif cash+1e-8 < POSITION_BUDGET:
                reason = "insufficient_cash"
            else:
                reason = "accepted"
                new_count += 1
                cash -= POSITION_BUDGET
                held[code] = {"trade": row, "mark": row["entry_price"]*row["entry_factor"]}
                accepted.append(row)
            decisions.append({"entry_date": day, "code": code, "decision": reason,
                              "signal_date": row.get("signal_date", "")})
        positions_before_exits = len(held)
        realized = 0.0
        for code, position in list(held.items()):
            row = position["trade"]
            if row["exit_date"] == day:
                proceeds = entry_notional*(1+row["gross_return_pct"]/100-exit_fee_rate)
                profit = proceeds-POSITION_BUDGET
                cash += proceeds
                realized += profit
                del held[code]
        value = cash
        for code, position in held.items():
            row = position["trade"]
            if (day, code) in marks:
                position["mark"] = marks[(day, code)]
            else:
                stale_marks += 1
            ratio = position["mark"]/(row["entry_price"]*row["entry_factor"])
            # Entry fee was funded by POSITION_BUDGET; reserve only the exit fee
            # in the mark. Thus ten tickets never borrow cash to pay entry fees.
            value += entry_notional*(ratio-exit_fee_rate)
        peak = max(peak, value)
        daily.append({"date": day, "cash": cash, "equity": value,
                      "drawdown_pct": (value/peak-1)*100,
                      "new_positions": new_count, "end_positions": len(held),
                      "positions_before_exits": positions_before_exits,
                      "realized_pnl": realized})
    if held:
        raise ValueError("Portfolio ends with unresolved positions")
    counts = defaultdict(int)
    for row in decisions:
        counts[row["decision"]] += 1
    return {
        "initial_capital": INITIAL_CAPITAL, "ending_equity": cash,
        "total_return_pct": (cash/INITIAL_CAPITAL-1)*100,
        "max_drawdown_pct": min((r["drawdown_pct"] for r in daily), default=0),
        "accepted_trades": len(accepted), "supplied_closed_trades": len(trades),
        "decisions": dict(counts), "daily_budget_slots": len(days)*2,
        "max_simultaneous_positions": max((r["positions_before_exits"] for r in daily), default=0),
        "mean_positions_before_exits": sum(r["positions_before_exits"] for r in daily)/len(days) if days else 0,
        "carried_stale_close_marks": stale_marks,
    }, daily, decisions


def self_check():
    def trade(code, entry, exit_, gross):
        return dict(code=code, entry_date=entry, exit_date=exit_, entry_price=10.0,
                    entry_factor=1.0, gross_return_pct=gross)
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    rows = [trade("A", days[0], days[2], 10), trade("B", days[0], days[1], -5),
            trade("C", days[0], days[1], 1), trade("A", days[2], days[3], 99)]
    marks = {(d, c): 10.0 for d in days for c in ("A", "B", "C")}
    result, _, decisions = simulate(days, rows, marks, .21)
    assert result["accepted_trades"] == 2
    assert math.isclose(result["ending_equity"], INITIAL_CAPITAL+100_000/1.0008*.0458)
    assert {d["decision"] for d in decisions} == {
        "accepted", "daily_entry_quota", "same_code_held_including_exit_day"}
    assert result["max_simultaneous_positions"] == 2
    # A future realized return never changes a prior entry/cash decision.
    altered = [dict(r, gross_return_pct=-40.0) if r["code"] == "A" else r for r in rows]
    _, _, before = simulate(days, altered, marks, .21)
    assert before == decisions
    return {"status": "passed", "checks": ["entry_quota", "same_code_exit_day",
            "cash_return", "no_future_proceeds", "position_count"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["self-check", "run"])
    parser.add_argument("--db", type=Path)
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    if args.phase == "self-check":
        print(json.dumps(self_check()))
        return
    if not all((args.db, args.trades, args.output, args.start, args.end)):
        parser.error("run requires db, trades, output, start and end")
    if args.output.exists():
        raise FileExistsError("Preserve the previous audit; choose a new output directory")
    rows = load_trades(args.trades, args.start, args.end)
    days, marks, quote_pairs = price_marks(args.db, rows, args.start, args.end)
    result = {}
    outputs = []
    for name, cost in (("base", .21), ("double_cost", .42)):
        summary, daily, decisions = simulate(days, rows, marks, cost)
        result[name] = summary
        outputs.extend([(f"{name}-daily.csv", daily), (f"{name}-decisions.csv", decisions)])
    args.output.mkdir(parents=True)
    for name, contents in outputs:
        if not contents:
            continue
        with (args.output/name).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(contents[0]))
            writer.writeheader()
            writer.writerows(contents)
    result.update({
        "completed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "period": [args.start, args.end], "quote_pairs": quote_pairs,
        "source_sha256": digest(Path(__file__)), "trades_sha256": digest(args.trades),
        "snapshot_sha256": digest(args.db), "self_check": self_check(),
        "contract": {
            "initial_capital": INITIAL_CAPITAL, "fixed_ticket_including_entry_fee": POSITION_BUDGET,
            "max_positions": MAX_POSITIONS, "max_new_positions_per_day": MAX_NEW_POSITIONS_PER_DAY,
            "priority": "code ascending among already frozen selected trade events",
            "cash_timing": "All same-day exit cash available only next session; even opening exits",
            "no_refill": True, "same_code_exit_day_entry": "rejected",
            "fees": "Entry 0.08 percent funded inside the cash ticket; reserve exit 0.13 percent in marks; stress doubles both. Costs use entry notional, matching frozen event conventions.",
        },
        "limitations": [
            "Fixed notional economic-return capacity overlay, not a lot-size/order-book/account simulator",
            "Receives a frozen event stream; cash-skipped events do not unlock rank3 or downstream signals",
            "Daily total-return marks use current stored adjustment factors; not strict point-in-time",
            "Stress fee may change later cash availability and hence accepted trade count",
            "Missing closes are carried and explicitly counted; no intraday portfolio drawdown",
            "Requires upstream evidence of zero unresolved positions and pre-fill daily Top2; closed CSV alone cannot prove those conditions",
        ],
    })
    (args.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "base": result["base"], "double_cost": result["double_cost"]}))


if __name__ == "__main__":
    main()
