"""Read-only conditional collection size, no returns or minute requests."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DB = ROOT/".local/chinext-payoff-20261004/market.db"
SPLITS = {"train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def write(path, result):
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def finite_positive(value):
    return value is not None and np.isfinite(value) and value > 0


def precise(value):
    scale = 10.**(9-np.floor(np.log10(abs(value))))
    return float(np.round(value*scale)/scale)


def aggregate(frame):
    unknown = frame.unknown_reason.ne("")
    excluded = frame.excluded
    assert not (unknown & excluded).any()
    return dict(total_code_days=len(frame), conditional_excluded=int(excluded.sum()),
        still_needing_minutes=int((~excluded).sum()), unknown_retained=int(unknown.sum()),
        known_not_excluded=int((~unknown & ~excluded).sum()),
        exclusion_reasons=frame.loc[excluded, "exclude_reason"].value_counts().to_dict(),
        unknown_reasons=frame.loc[unknown, "unknown_reason"].value_counts().to_dict(),
        exact_high_threshold_equal_retained=int(frame.high_equal.sum()),
        dates_with_remaining_requests=int(frame.loc[~excluded, "target_date"].nunique()))


def run():
    target = HERE/"envelope-size.json"
    if target.exists() or (HERE/"envelope-freeze-receipt.json").exists():
        raise FileExistsError("Preserve conditional estimate")
    before = {str(p.relative_to(ROOT)): sha(p) for p in (DB, HERE/"PLAN.json", HERE/"PLAN.md", HERE/"potential-code-days.csv", HERE/"daily-counts.csv")}
    receipt = dict(created_at=now(), contract_sha256=sha(HERE/"envelope-plan.md"),
        script_sha256=sha(Path(__file__)), original_inputs_sha256=before,
        no_returns_or_minute_reads=True, conditional_estimate_only=True)
    write(HERE/"envelope-freeze-receipt.json", receipt)
    pool = pd.read_csv(HERE/"potential-code-days.csv", dtype={"code": str}, float_precision="round_trip")
    with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        sparse = {}
        for code, date, factor in conn.execute("SELECT code,trade_date,hfq_factor FROM adjust_factors WHERE trade_date<=? ORDER BY code,trade_date", ("2026-09-30",)):
            if code not in sparse:
                sparse[code] = ([], [])
            sparse[code][0].append(date)
            sparse[code][1].append(factor)
        ideal, highonly, source_counts = [], [], Counter()
        for row in pool.itertuples():
            quote = conn.execute("SELECT high,volume,source FROM quotes_daily WHERE trade_date=? AND code=?", (row.target_date, row.code)).fetchone()
            high, volume, source = quote if quote is not None else (None, None, None)
            source_counts[str(source or "missing")] += 1
            factor = None
            if row.code in sparse:
                days, values = sparse[row.code]
                index = bisect_right(days, row.target_date)-1
                if index >= 0:
                    factor = values[index]
            missing_h = []
            if quote is None:
                missing_h.append("missing_quote")
            if source != "tdx":
                missing_h.append("non_tdx_or_missing_source")
            if not finite_positive(high):
                missing_h.append("missing_or_invalid_high")
            if not finite_positive(factor):
                missing_h.append("missing_or_invalid_factor")
            missing_hv = list(missing_h)
            if volume is None or not np.isfinite(volume) or volume < 0:
                missing_hv.append("missing_or_invalid_volume")
            below_h, equal_h = False, False
            if not missing_h:
                economic_high = Decimal(str(precise(float(high)*float(factor))))
                threshold = max(Decimal(str(row.prior_high5_economic)), Decimal("1.03")*Decimal(str(row.previous_close_economic)))
                below_h, equal_h = economic_high < threshold, economic_high == threshold
            below_v = not missing_hv and Decimal(str(volume)) < Decimal("1.5")*Decimal(str(row.previous_volume))
            ideal_exclude = bool(not missing_hv and (below_h or below_v))
            high_exclude = bool(not missing_h and below_h)
            reason = "high_and_volume" if below_h and below_v else "high_only" if below_h else "volume_only"
            base = dict(target_date=row.target_date, code=row.code)
            ideal.append({**base, "excluded": ideal_exclude, "exclude_reason": reason if ideal_exclude else "",
                "unknown_reason": ";".join(missing_hv), "high_equal": bool(equal_h and not ideal_exclude)})
            highonly.append({**base, "excluded": high_exclude, "exclude_reason": "high_only" if high_exclude else "",
                "unknown_reason": ";".join(missing_h), "high_equal": bool(equal_h and not high_exclude)})
    schemes = {}
    frames = {"ideal_daily_high_and_volume": pd.DataFrame(ideal), "tdx_daily_high_only": pd.DataFrame(highonly)}
    for name, frame in frames.items():
        schemes[name] = dict(full=aggregate(frame), segments={segment: aggregate(frame[frame.target_date.between(start, end)])
            for segment, (start, end) in SPLITS.items()})
    after = {path: sha(ROOT/path) for path in before}
    assert before == after
    result = dict(completed_at=now(), assumptions="envelope-plan.md, bound by envelope-freeze-receipt.json",
        status="conditional_collection_size_only_not_proven_minute_equivalence",
        code_days=len(pool), sources=dict(source_counts), schemes=schemes,
        quote_fields_read=["high", "volume", "source"], direct_factor_asof_target_day=True,
        final_close_not_read=True, score_top2_returns_not_read=True, minute_downloads=0,
        original_plan_pool_and_database_unchanged=True,
        no_global_100share_tolerance_inferred=True,
        receipt_sha256=sha(HERE/"envelope-freeze-receipt.json"))
    write(target, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    run()
