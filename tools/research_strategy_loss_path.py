"""Training-only loss attribution, not an executable alternate backtest."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/research/2026-10-04-strategy-redesign"
INPUT = ROOT / "docs/research/2026-10-04-multi-strategy-scoring"
DATABASES = {
    "contraction-rebreakout-v1": ROOT / ".local/chinext-payoff-20261004/market.db",
    "double-volume-yin-low-open-v1": ROOT / ".local/multi-strategy-scoring-20261004/market.db",
}


def moments(values) -> dict:
    a = np.array(values, dtype=float)
    a = a[np.isfinite(a)]
    return dict(n=len(a), mean=float(a.mean()) if len(a) else None,
                median=float(np.median(a)) if len(a) else None,
                positive_pct=float((a > 0).mean()*100) if len(a) else None)


def run(slug, db):
    trades = pd.read_csv(INPUT / slug / "train-baseline-trades.csv", dtype={"code": str})
    conn = sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    days = [r[0] for r in conn.execute("SELECT trade_date FROM trading_calendar WHERE trade_date BETWEEN '2023-01-01' AND '2025-06-30' ORDER BY trade_date")]
    positions = {day:i for i,day in enumerate(days)}
    marks = []
    for t in trades.itertuples():
        row = dict(code=t.code,signal_date=t.signal_date,entry_date=t.entry_date,
                   actual_net=t.net_return_pct,exit_reason=t.exit_reason)
        basis = t.entry_price*t.entry_factor
        for offset in range(4):
            index = positions[t.entry_date] + offset
            if index >= len(days):
                continue
            day = days[index]
            q = conn.execute("SELECT open,close,volume FROM quotes_daily WHERE code=? AND trade_date=?",(t.code,day)).fetchone()
            factor = conn.execute("SELECT hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",(t.code,day)).fetchone()
            for field in ("open", "close"):
                value = float(q[field]) if q and q[field] is not None else np.nan
                f = float(factor[0]) if factor else np.nan
                valid = q and q["volume"] is not None and q["volume"] > 0 and value > 0 and np.isfinite(f) and f > 0
                row[f"session{offset+1}_{field}_gross"] = (value*f/basis-1)*100 if valid else np.nan
        if slug.startswith("contraction"):
            q = conn.execute("SELECT close FROM quotes_daily WHERE code=? AND trade_date=?",(t.code,t.signal_date)).fetchone()
            f = conn.execute("SELECT hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",(t.code,t.signal_date)).fetchone()
            row["entry_gap_economic_pct"] = (basis/(float(q[0])*float(f[0]))-1)*100 if q and f else np.nan
        marks.append(row)
    conn.close()
    frame = pd.DataFrame(marks)
    frame.to_csv(OUTPUT / f"{slug}-train-paths.csv",index=False)
    by_exit={str(k):dict(**moments(g.actual_net),net_sum=float(g.actual_net.sum())) for k,g in frame.groupby("exit_reason")}
    paths={field:moments(frame[field]) for field in frame if field.endswith("_gross")}
    first=frame["session1_close_gross"]
    buckets={}
    for name,mask in {"entry_day_red":first.lt(0),"entry_day_green":first.ge(0)}.items():
        buckets[name]=moments(frame.loc[mask,"actual_net"])
    gap_buckets={}
    if "entry_gap_economic_pct" in frame:
        gap=frame.entry_gap_economic_pct
        for name,mask in {"gap_negative":gap.lt(0),"gap_0_to_3":gap.ge(0)&gap.lt(3),"gap_ge3":gap.ge(3)}.items():
            gap_buckets[name]=moments(frame.loc[mask,"actual_net"])
    return dict(strategy=slug,segment="train",cost_pct=.21,baseline=moments(frame.actual_net),
        by_exit=by_exit,unconditional_economic_marks=paths,entry_day_classification=buckets,gap_buckets=gap_buckets,
        limitations=["Entry-day mark is unavailable at opening and cannot be an opening filter.",
                     "Forward marks are diagnostic only; they do not apply limit-down exit feasibility, stops, fees, or portfolio constraints.",
                     "No stop-versus-timeout causal claim: exit categories depend on realized future prices."])


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result={slug:run(slug,db) for slug,db in DATABASES.items()}
    (OUTPUT/"loss-path-diagnostics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
