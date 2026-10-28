"""Acquire and replay observed minute prices without inventing minute OHLC.

The existing daily experiment stays frozen. This separate experiment preserves
every setup and explicitly uses one-minute last-price sampling for decisions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.first_wave_data import ro_connect
from scripts.first_wave_research import load_minutes, load_panels, metrics, serializable
from src.market.infrastructure.tdx_minute import _close_client, _fetch_day, _open_client


def read_setups(directory: Path) -> pd.DataFrame:
    rows = pd.read_csv(directory / "all-wave-setups.csv", dtype=str, keep_default_na=False)
    return rows.loc[rows["status"].eq("setup_ready") & rows["d2_date"].ne("")].copy()


def _check_receipt_dates(record: dict[str, Any], code: str, day: str) -> dict[str, Any]:
    if record.get("code") != code or record.get("requested_date") != day:
        return {**record, "status": "request_identity_mismatch"}
    if record.get("records"):
        timestamps = pd.to_datetime([row["datetime"] for row in record["records"]], errors="coerce")
        if timestamps.isna().any() or (timestamps.strftime("%Y-%m-%d") != day).any():
            return {**record, "status": "quote_date_mismatch"}
    return record


class QuoteCache:
    """Task-specific public-price cache; each worker owns a distinct stock code."""

    def __init__(self, db: Path, root: Path, observed: dict, probes: Path):
        self.db, self.root, self.observed, self.probes = db, root, observed, probes
        self.local = threading.local()
        self.clients = []

    def fetch(self, con, code: str, day: str) -> dict[str, Any]:
        path = self.root / code / f"{day}.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as source:
                return _check_receipt_dates(json.load(source), code, day)
        raw_day = con.execute("SELECT open,high,low,close,volume FROM quotes_daily WHERE code=? AND trade_date=?", (code, day)).fetchone()
        record: dict[str, Any] = {"code": code, "requested_date": day, "captured_at": datetime.now(timezone.utc).isoformat(),
                                  "status": "history_empty", "source_kind": "historical_last_price_samples", "records": []}
        if raw_day is not None and raw_day[4] == 0:
            record["status"] = "confirmed_no_trades"
        else:
            known = self.observed.get(code, {}).get(day)
            probe = self.probes / f"tdx-{code}-{day}.json"
            try:
                if known is not None:
                    frame = known[["close", "volume"]].copy()
                    frame.insert(0, "datetime", frame.index.strftime("%Y-%m-%d %H:%M"))
                    record["source_kind"] = "observed_minute_bar_closes"
                elif probe.exists():
                    seed = json.loads(probe.read_text(encoding="utf-8"))
                    frame = pd.DataFrame(seed.get("records", []))
                    record["seed_probe"] = str(probe)
                else:
                    client = getattr(self.local, "client", None)
                    if client is None:
                        client = _open_client()
                        self.local.client = client
                        self.clients.append(client)
                    frame = _fetch_day(client, code, day)
                    time.sleep(0.1)
                if not frame.empty:
                    values = frame[["close", "volume"]].to_numpy(dtype=float)
                    record["records"] = frame[["datetime", "close", "volume"]].to_dict("records")
                    record["quote_count"] = len(frame)
                    if not (np.isfinite(values).all() and (values[:, 0] > 0).all() and (values[:, 1] >= 0).all()):
                        record["status"] = "invalid_quote_values"
                    elif raw_day is None or not all(v is not None and np.isfinite(v) and v > 0 for v in raw_day[:4]):
                        record["status"] = "daily_validation_missing"
                    else:
                        prices = values[:, 0]
                        record["daily_reference"] = {"open": raw_day[0], "high": raw_day[1], "low": raw_day[2], "close": raw_day[3]}
                        record["closing_difference"] = float(prices[-1] - raw_day[3])
                        record["all_prices_inside_daily_range"] = bool(prices.min() >= raw_day[2] - 0.011 and prices.max() <= raw_day[1] + 0.011)
                        record["status"] = "verified" if abs(record["closing_difference"]) <= 0.011 and record["all_prices_inside_daily_range"] else "daily_price_mismatch"
                        record["date_validation"] = "requested historical date plus closing-price and full-range crosscheck; response does not independently timestamp its day"
            except Exception as exc:
                # A provider/transport failure is evidence failure, not a zero
                # return. The negative receipt is kept to avoid a retry storm.
                record.update(status="source_error", error_type=type(exc).__name__, error=str(exc))
                client = getattr(self.local, "client", None)
                if client is not None:
                    _close_client(client)
                    self.local.client = None
        record = _check_receipt_dates(record, code, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(staging, "wt", encoding="utf-8", compresslevel=1) as target:
            json.dump(serializable(record), target, ensure_ascii=False, allow_nan=False)
        staging.replace(path)
        return record

    def frame(self, con, code: str, day: str) -> tuple[pd.DataFrame | None, dict]:
        record = self.fetch(con, code, day)
        if record["status"] == "confirmed_no_trades":
            frame = pd.DataFrame(columns=["close", "volume"], index=pd.DatetimeIndex([]))
            frame.attrs["confirmed_no_trades"] = True
            return frame, record
        if record["status"] != "verified":
            return None, record
        frame = pd.DataFrame(record["records"])
        frame.index = pd.to_datetime(frame.pop("datetime"))
        return frame, record

    def close(self) -> None:
        for client in self.clients:
            _close_client(client)


def capture_initial(db: Path, directory: Path, root: Path, overlay: Path | None) -> dict:
    setups = read_setups(directory)
    with ro_connect(db) as con:
        observed, coverage = load_minutes(con, overlay)
    cache = QuoteCache(db, root, observed, root.parent / "minute-probes")
    counts = Counter()
    groups = list(setups.groupby("code", sort=True))

    def fetch_stock(item):
        code, group = item
        with ro_connect(db) as con:
            return [cache.fetch(con, code, day)["status"] for day in group["d2_date"]]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(fetch_stock, item) for item in groups]
            for n, job in enumerate(as_completed(jobs), 1):
                counts.update(job.result())
                if n % 50 == 0 or n == len(groups):
                    print("captured_codes", n, "/", len(groups), "D2", dict(counts), flush=True)
    finally:
        cache.close()
    report = {"opportunities": len(setups), "codes": len(groups), "d2_status_counts": dict(counts),
              "cache": str(root.resolve()), "observed_minute_coverage": coverage,
              "assumption": "Price samples have no true minute OHLC; unavailable dates are not filled from daily bars."}
    (directory / "quote-data-capture.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def replay(db: Path, directory: Path, root: Path, overlay: Path | None) -> dict:
    from scripts.first_wave_quote_execution import simulate_quote_opportunity

    setups = read_setups(directory)
    baseline = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    inputs = (Path(__file__), ROOT / "scripts/first_wave_quote_execution.py", ROOT / "scripts/first_wave_execution.py")
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (directory / "quote-protocol.json").write_text(json.dumps({
        "frozen_at": datetime.now(timezone.utc).isoformat(), "source_hashes": hashes,
        "baseline_database_sha256": baseline["database_sha256"], "setup_ledger_sha256": hashlib.sha256((directory / "all-wave-setups.csv").read_bytes()).hexdigest(),
        "resolution": "observed one-minute last prices; no claimed intraminute high/low",
        "decision": "14:50 using known quote and previous four adjusted closes",
        "execution": "next observed positive-volume price, with baseline research fees and T+1",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with ro_connect(db) as con:
        dates, codes, panels, quality = load_panels(con)
        observed, coverage = load_minutes(con, overlay)
    cache = QuoteCache(db, root, observed, root.parent / "minute-probes")
    positions = {code: j for j, code in enumerate(codes)}

    def replay_stock(item):
        code, group = item
        j = positions[code]
        bars = pd.DataFrame({field: value[:, j] for field, value in panels.items()}, index=dates, copy=False)
        quote_frames = {}
        stock_results = []
        with ro_connect(db) as con:
            for _, setup in group.iterrows():
                requested = set()
                day = setup["d2_date"]
                while True:
                    if day not in quote_frames:
                        frame, receipt = cache.frame(con, code, day)
                        requested.add(day)
                        if frame is not None:
                            quote_frames[day] = frame
                    result = simulate_quote_opportunity(bars, setup["d2_date"], code=code, quotes=quote_frames, hold_days=10, notional=100000)
                    missing = result.get("missing_quote_date")
                    if not missing or missing in requested or missing > dates[-1]:
                        if missing:
                            _, receipt = cache.frame(con, code, missing)
                            result["quote_source_failure"] = {k: v for k, v in receipt.items() if k != "records"}
                        break
                    day = missing
                for gate, passed in (("no_mainline", True), ("price_resonance_proxy", setup["mainline_proxy_passed"].lower() == "true"), ("observed_theme", setup["theme_status"] == "verified")):
                    row = {**result, "mainline_gate": gate, "d0_date": setup["d0_date"], "d1_date": setup["d1_date"],
                           "variant": f"{gate}__sampled_quotes_1450__h10__staged__ma5_or_horizon"}
                    if not passed:
                        row = {k: v for k, v in row.items() if k in ("code", "signal_date", "mode", "hold_days", "staged", "exit_rule", "variant", "mainline_gate", "d0_date", "d1_date")}
                        row.update(status="mainline_unverifiable" if gate == "observed_theme" and setup["theme_status"] == "unknown" else "mainline_rejected",
                                   legs=[], net_return_pct=None, gross_return_pct=None, exit_reason=None)
                    stock_results.append(row)
        return stock_results

    results = []
    groups = list(setups.groupby("code", sort=True))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(replay_stock, item) for item in groups]
            for n, job in enumerate(as_completed(jobs), 1):
                results.extend(job.result())
                if n % 25 == 0 or n == len(groups):
                    print("replayed_codes", n, "/", len(groups), "rows", len(results), flush=True)
    finally:
        cache.close()
    if any(hashlib.sha256(p.read_bytes()).hexdigest() != hashes[str(p.relative_to(ROOT))] for p in inputs):
        raise RuntimeError("Quote replay implementation changed during the experiment")
    results.sort(key=lambda row: (row["signal_date"], row["code"], row["mainline_gate"]))
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(), "opportunities": len(setups), "ledger_rows": len(results),
        "source_hashes": hashes, "baseline_database_sha256": baseline["database_sha256"], "quality": quality,
        "resolution": "one-minute price sampling, not complete minute OHLC or tick paths",
        "coverage": coverage, "cache": str(root.resolve()), "variants": {},
    }
    for variant in sorted({r["variant"] for r in results}):
        rows = [r for r in results if r["variant"] == variant]
        summary["variants"][variant] = {"overall": metrics(rows),
            "by_year": {str(y): metrics([r for r in rows if r["signal_date"][:4] == str(y)]) for y in range(1990, 2027)}}
    with (directory / "quote-opportunities.jsonl").open("w", encoding="utf-8") as target:
        for row in results:
            target.write(json.dumps(serializable(row), ensure_ascii=False, allow_nan=False) + "\n")
    (directory / "quote-summary.json").write_text(json.dumps(serializable(summary), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "replay"))
    parser.add_argument("db", type=Path)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--minute-overlay", type=Path)
    args = parser.parse_args()
    result = (capture_initial if args.phase == "capture" else replay)(args.db, args.directory, args.cache, args.minute_overlay)
    print(json.dumps(serializable({k: v for k, v in result.items() if k != "variants"}), ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
