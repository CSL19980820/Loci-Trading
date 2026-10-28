"""Read-only cross-check for quote rows missing both volume and amount."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market.infrastructure.sources import SinaSource
from src.market.infrastructure.store import MarketStore


def _number(value):
    return None if value is None or pd.isna(value) else float(value)


def build_plan(store: MarketStore, *, workers: int) -> dict:
    rows = store.conn.execute(
        """
        SELECT q.code, q.trade_date, q.open, q.high, q.low, q.close,
               q.turnover, q.source, i.instrument_type, i.status
          FROM quotes_daily q
          LEFT JOIN instruments i ON i.code=q.code
         WHERE q.volume IS NULL AND q.amount IS NULL
         ORDER BY q.code, q.trade_date
        """
    ).fetchall()
    targets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        targets[str(row["code"])].append(
            {
                "code": str(row["code"]),
                "trade_date": str(row["trade_date"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "turnover": row["turnover"],
                "source": row["source"],
                "instrument_type": row["instrument_type"],
                "status": row["status"],
            }
        )
    provider = SinaSource()

    def fetch(code: str):
        try:
            return code, provider.fetch_daily(code, instrument_type="STOCK")
        except Exception as exc:
            return code, {"error": f"{type(exc).__name__}: {exc}"}

    results: list[dict] = []
    unresolved: list[dict] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for position, (code, frame) in enumerate(pool.map(fetch, sorted(targets)), start=1):
            if isinstance(frame, dict):
                unresolved.extend(
                    {**item, "reason": "sina_fetch_failed", "error": frame["error"]}
                    for item in targets[code]
                )
                continue
            by_date = {
                str(row.date): row
                for row in frame.itertuples(index=False)
            }
            for item in targets[code]:
                source_row = by_date.get(item["trade_date"])
                if source_row is None:
                    unresolved.append({**item, "reason": "sina_no_bar"})
                    continue
                price_match = all(
                    abs(float(item[field]) - float(getattr(source_row, field))) <= 0.01
                    for field in ("open", "high", "low", "close")
                )
                volume = _number(source_row.volume)
                amount = _number(source_row.amount)
                if not price_match:
                    unresolved.append({**item, "reason": "sina_price_mismatch"})
                elif volume is None or amount is None or volume < 0 or amount < 0:
                    unresolved.append({**item, "reason": "sina_volume_amount_missing"})
                else:
                    results.append(
                        {
                            **item,
                            "volume": volume,
                            "amount": amount,
                            "sina_outstanding_share": _number(
                                getattr(source_row, "outstanding_share", None)
                            ),
                            "sina_turnover": _number(getattr(source_row, "turnover", None)),
                        }
                    )
            if position % 100 == 0 or position == len(targets):
                print(
                    f"  {position}/{len(targets)} 只，可修 {len(results)}，"
                    f"待核 {len(unresolved)}"
                )
    reasons: dict[str, int] = defaultdict(int)
    for item in unresolved:
        reasons[item["reason"]] += 1
    return {
        "codes": len(targets),
        "target_rows": len(rows),
        "fillable_rows": len(results),
        "unresolved_rows": len(unresolved),
        "unresolved_reasons": dict(reasons),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "changes": results,
        "unresolved": unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读复核量额双空行情")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    store = MarketStore()
    try:
        report = build_plan(store, workers=max(1, args.workers))
    finally:
        store.close()
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    summary = {key: value for key, value in report.items() if key not in {"changes", "unresolved"}}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
