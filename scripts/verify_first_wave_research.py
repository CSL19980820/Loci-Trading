"""Independently reconcile the whole first-wave ledger against frozen raw prices."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from math import fsum, isclose, isfinite
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def verify(db: Path, directory: Path) -> dict:
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8"))
    for name, digest in protocol["source_hashes"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise AssertionError(f"Changed implementation: {name}")
    if protocol["source_hashes"] != summary["source_hashes"]:
        raise AssertionError("Protocol and result implementations differ")
    if protocol["database_sha256"] != summary["database_sha256"]:
        raise AssertionError("Protocol and result database fingerprints differ")
    with (directory / "all-wave-setups.csv").open(encoding="utf-8-sig", newline="") as source:
        setups = list(csv.DictReader(source))
    ready = {(r["code"], r["d2_date"]): r for r in setups if r["status"] == "setup_ready" and r["d2_date"]}
    groups = defaultdict(lambda: {"ids": set(), "statuses": Counter(), "returns": [], "legs": 0})
    price_cache, factor_cache = {}, {}
    checked_legs = 0
    checked_daily_prices = 0
    records = 0
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        with (directory / "all-opportunities.jsonl").open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                records += 1
                key = (row["code"], row["signal_date"])
                group = groups[row["variant"]]
                if key not in ready or key in group["ids"]:
                    raise AssertionError(("Missing/duplicate opportunity", row["variant"], key))
                group["ids"].add(key)
                group["statuses"][row["status"]] += 1
                if row["status"] != "closed":
                    if row["status"] != "skipped" and row.get("net_return_pct") is not None:
                        raise AssertionError(("Unfinished trade counted as realized", key))
                    if row["status"].startswith("mainline_") and row.get("legs"):
                        raise AssertionError(("Rejected mainline has fabricated fills", key))
                    continue
                legs = row["legs"]
                if not legs or len(legs) > (2 if row["staged"] else 1):
                    raise AssertionError(("Incorrect tranche count", key))
                gross, net = [], []
                for leg in legs:
                    if not leg["entry_date"] < leg["exit_date"] <= summary["database_range"][1]:
                        raise AssertionError(("T+1/date-range violation", key, leg))
                    for side in ("entry", "exit"):
                        day, price = leg[f"{side}_date"], leg[f"{side}_price"]
                        factor = leg["factor"] if side == "entry" else leg["exit_factor"]
                        identity = (row["code"], day)
                        if identity not in factor_cache:
                            found = con.execute("SELECT hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? AND hfq_factor>0 ORDER BY trade_date DESC LIMIT 1", identity).fetchone()
                            factor_cache[identity] = found[0] if found else None
                        if factor_cache[identity] is None or not isclose(factor, factor_cache[identity], rel_tol=1e-12):
                            raise AssertionError(("Factor differs from frozen source", identity))
                        if row["mode"] == "next_open":
                            if identity not in price_cache:
                                found = con.execute("SELECT open FROM quotes_daily WHERE code=? AND trade_date=?", identity).fetchone()
                                price_cache[identity] = found[0] if found else None
                            if price_cache[identity] is None or not isclose(price, price_cache[identity], abs_tol=1e-9):
                                raise AssertionError(("Fill is not the raw opening price", identity, price, price_cache[identity]))
                            checked_daily_prices += 1
                    proceeds = leg["notional"] * leg["exit_price"] * leg["exit_factor"] / (leg["entry_price"] * leg["factor"])
                    expected_gross = proceeds - leg["notional"]
                    expected_net = expected_gross - leg["entry_costs"]["total"] - leg["exit_costs"]["total"]
                    if not isclose(expected_gross, leg["gross_pnl"], abs_tol=1e-6) or not isclose(expected_net, leg["net_pnl"], abs_tol=1e-6):
                        raise AssertionError(("Tranche P&L reconciliation failed", key))
                    gross.append(expected_gross)
                    net.append(expected_net)
                    checked_legs += 1
                if not isclose(fsum(gross) / row["notional"] * 100, row["gross_return_pct"], abs_tol=1e-9):
                    raise AssertionError(("Gross return reconciliation failed", key))
                if not isclose(fsum(net) / row["notional"] * 100, row["net_return_pct"], abs_tol=1e-9):
                    raise AssertionError(("Net return reconciliation failed", key))
                if not isfinite(row["net_return_pct"]):
                    raise AssertionError(("Non-finite realized return", key))
                group["returns"].append(row["net_return_pct"])
                group["legs"] += len(legs)
    finally:
        con.close()
    for variant, group in groups.items():
        result = summary["variants"][variant]
        metrics = result["overall"]
        values = group["returns"]
        if group["ids"] != ready.keys() or dict(group["statuses"]) != metrics["status_counts"]:
            raise AssertionError(("Whole-opportunity accounting failed", variant))
        if len(values) != metrics["realized_trades"]:
            raise AssertionError(("Realized count differs", variant))
        if values and not isclose(fsum(values) / len(values), metrics["mean_net_pct"], abs_tol=1e-10):
            raise AssertionError(("Mean return differs", variant))
        if sum(v["realized_trades"] for v in result["by_year"].values()) != len(values):
            raise AssertionError(("Annual reconciliation failed", variant))
        if set(result["by_year"]) != {str(y) for y in range(1990, 2027)}:
            raise AssertionError(("Missing years, including zero-opportunity years", variant))
    if len(groups) != 24 or records != len(ready) * 24 or summary["prefix_checks"] != len(ready):
        raise AssertionError("Expected 24 variants for every eligible opportunity and a prefix proof for each")
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(), "passed": True,
        "opportunities": len(ready), "variants": len(groups), "ledger_rows": records,
        "tranche_pnl_checks": checked_legs, "raw_open_price_checks": checked_daily_prices,
        "unique_raw_price_observations": len(price_cache), "unique_factor_observations": len(factor_cache),
        "source_hashes_verified": len(protocol["source_hashes"]), "actual_prefix_checks": summary["prefix_checks"],
        "scope": "All recorded variants, T+1, date ranges, raw daily opening fills, frozen factors, tranche P&L, means and annual counts. This does not fill missing historical minute/theme evidence.",
    }
    (directory / "ledger-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.db, args.directory)))
