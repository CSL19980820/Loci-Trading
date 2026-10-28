"""Read-only planner for missing historical turnover values.

Uses the same ``_RollingSharesAsOf`` and ``compute_turnover`` functions as the
writer, scans dates in ascending order, and reports how many positive-volume
rows can be filled without using future share counts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.turnover_math import compute_turnover
from src.market.infrastructure.turnover_repair import _RollingSharesAsOf


def _value(row, key: str, position: int):
    return row[key] if hasattr(row, "keys") else row[position]


def plan_turnover(store: MarketStore, *, since: str | None = None) -> dict:
    clauses = ["(turnover IS NULL OR turnover <= 0)", "volume > 0"]
    params: list[object] = []
    if since:
        clauses.append("trade_date >= ?")
        params.append(str(since))
    where = " AND ".join(clauses)
    rows = store.conn.execute(
        f"SELECT DISTINCT trade_date FROM quotes_daily WHERE {where} ORDER BY trade_date",
        params,
    ).fetchall()
    dates = [str(_value(row, "trade_date", 0)) for row in rows]
    shares = _RollingSharesAsOf(store)
    fillable = 0
    skipped = 0
    fillable_by_source: Counter[str] = Counter()
    skipped_by_source: Counter[str] = Counter()
    changes: list[dict] = []
    started = time.monotonic()
    for position, trade_date in enumerate(dates, start=1):
        shares_map = shares.shares_for(trade_date)
        rows = store.conn.execute(
            "SELECT code, volume, amount, close, source, outstanding_share "
            "FROM quotes_daily "
            "WHERE trade_date = ? AND (turnover IS NULL OR turnover <= 0)",
            (trade_date,),
        ).fetchall()
        for row in rows:
            code = str(_value(row, "code", 0))
            volume = _value(row, "volume", 1)
            amount = _value(row, "amount", 2)
            close = _value(row, "close", 3)
            source = str(_value(row, "source", 4) or "unknown")
            if volume is None or float(volume) <= 0:
                continue
            share_count = shares_map.get(code)
            turnover = compute_turnover(
                volume=float(volume),
                amount=float(amount) if amount is not None else None,
                close=float(close) if close is not None else None,
                shares=float(share_count) if share_count is not None else None,
            )
            if turnover is None:
                skipped += 1
                skipped_by_source[source] += 1
            else:
                fillable += 1
                fillable_by_source[source] += 1
                changes.append(
                    {
                        "code": code,
                        "trade_date": trade_date,
                        "volume": float(volume),
                        "amount": float(amount) if amount is not None else None,
                        "close": float(close) if close is not None else None,
                        "old_outstanding_share": (
                            float(_value(row, "outstanding_share", 5))
                            if _value(row, "outstanding_share", 5) is not None
                            else None
                        ),
                        "shares_asof": float(share_count),
                        "turnover": float(turnover),
                        "source": source,
                    }
                )
        if position % 100 == 0 or position == len(dates):
            elapsed = time.monotonic() - started
            print(
                f"  {position}/{len(dates)} 日，可补 {fillable}，跳过 {skipped}，"
                f"{position / max(elapsed, 1e-9):.2f} 日/秒"
            )
    return {
        "since": since or "",
        "dates_scanned": len(dates),
        "fillable": fillable,
        "skipped": skipped,
        "fillable_by_source": dict(fillable_by_source),
        "skipped_by_source": dict(skipped_by_source),
        "changes": changes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读模拟缺换手率回填")
    parser.add_argument("--since", default=None)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    store = MarketStore()
    try:
        report = plan_turnover(store, since=args.since)
    finally:
        store.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
