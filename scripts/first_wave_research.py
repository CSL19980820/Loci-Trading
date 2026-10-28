"""Whole-database first-wave research, with every setup retained in a ledger.

The 14:50 strategy requires minute evidence. next_open is a separate causal
daily-bar comparison, never a fabricated historical 14:50 execution.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.first_wave_data import ro_connect
from scripts.first_wave_theme_evidence import load_theme_evidence
from src.strategy.application.first_wave_pullback import (
    FirstWaveConfig,
    detect_first_waves,
    price_resonance_mainline,
)


def load_panels(con: sqlite3.Connection) -> tuple[list[str], list[str], dict[str, np.ndarray], dict[str, Any]]:
    dates = [str(r[0]) for r in con.execute("SELECT DISTINCT trade_date FROM quotes_daily ORDER BY trade_date")]
    instruments = {str(r[0]): {"name": r[1], "type": r[2], "list_date": r[3]} for r in con.execute(
        "SELECT code,name,instrument_type,list_date FROM instruments")}
    all_codes = [str(r[0]) for r in con.execute("SELECT DISTINCT code FROM quotes_daily ORDER BY code")]
    codes = [code for code in all_codes if instruments.get(code, {}).get("type") != "INDEX"]
    date_axis, code_axis = pd.Index(dates), pd.Index(codes)
    fields = ("open", "high", "low", "close", "volume")
    panels = {field: np.full((len(dates), len(codes)), np.nan) for field in fields}
    quality: dict[str, Any] = {"invalid_rows": 0, "prelisting_rows": 0, "by_year": {},
                               "universe": "union of all stored non-index codes, no present-day status filter",
                               "unknown_instrument_codes": [c for c in codes if c not in instruments]}
    for year in sorted({d[:4] for d in dates}):
        frame = pd.read_sql_query(
            "SELECT trade_date,code,open,high,low,close,volume FROM quotes_daily WHERE trade_date>=? AND trade_date<?",
            con, params=(year + "-01-01", str(int(year) + 1) + "-01-01"),
        )
        columns = code_axis.get_indexer(frame["code"])
        frame = frame.loc[columns >= 0].copy()
        columns = columns[columns >= 0]
        rows = date_axis.get_indexer(frame["trade_date"])
        values = frame[list(fields)].to_numpy(dtype=float)
        op, hi, lo, cl, vo = values.T
        valid = np.isfinite(values).all(axis=1) & (lo > 0) & (vo > 0)
        valid &= (hi + 0.005 >= np.maximum(op, cl)) & (lo - 0.005 <= np.minimum(op, cl)) & (hi >= lo)
        listing = frame["code"].map({c: x["list_date"] for c, x in instruments.items()}).fillna("")
        prelisting = (listing != "") & (frame["trade_date"].to_numpy() < listing.to_numpy())
        quality["prelisting_rows"] += int(prelisting.sum())
        quality["invalid_rows"] += int((~valid).sum())
        valid &= ~prelisting.to_numpy()
        quality["by_year"][year] = {"rows": len(frame), "valid_rows": int(valid.sum()), "invalid_rows": int((~valid).sum())}
        for k, field in enumerate(fields):
            panels[field][rows[valid], columns[valid]] = values[valid, k]
        print("loaded", year, len(frame), "valid", int(valid.sum()), flush=True)
    factor = np.full_like(panels["close"], np.nan)
    by_code: dict[str, list[tuple[str, float]]] = {}
    for code, day, value in con.execute("SELECT code,trade_date,hfq_factor FROM adjust_factors ORDER BY code,trade_date"):
        if value is not None and np.isfinite(value) and value > 0:
            by_code.setdefault(str(code), []).append((str(day), float(value)))
    for j, code in enumerate(codes):
        events = by_code.get(code, [])
        if not events:
            continue
        event_dates = np.array([x[0] for x in events])
        event_factors = np.array([x[1] for x in events])
        positions = np.searchsorted(event_dates, np.array(dates), side="right") - 1
        covered = positions >= 0
        factor[covered, j] = event_factors[positions[covered]]
    quality["valid_prices_without_factor"] = int((np.isfinite(panels["close"]) & ~np.isfinite(factor)).sum())
    panels["factor"] = factor
    return dates, codes, panels, quality


def load_minutes(con: sqlite3.Connection, overlay: Path | None = None) -> tuple[dict[str, dict[str, pd.DataFrame]], dict[str, Any]]:
    """Use observed minute points, with their own dates and quality flags.

    Wrapper trade_date is not a substitute for the timestamp of each point.
    Cached snapshots are historical price reconstructions, not evidence that
    the application had received those records at 14:50 on the old date.
    """
    buckets: dict[tuple[str, str], tuple[str, pd.DataFrame]] = {}
    audit: Counter = Counter()
    records = list(con.execute(
        "SELECT trade_date,payload_json,fetched_at FROM intel_snapshots WHERE tool='minute_data' ORDER BY fetched_at"))
    overlay_hashes = {}
    if overlay is not None:
        for path in sorted(overlay.glob("*.json")):
            raw = path.read_bytes()
            wrapper = json.loads(raw)
            records.append((wrapper["trade_date"], raw.decode("utf-8"), wrapper["fetched_at"]))
            overlay_hashes[path.name] = hashlib.sha256(raw).hexdigest()
    records.sort(key=lambda record: record[2])
    for day, payload, fetched in records:
        audit["snapshots"] += 1
        wrapper = json.loads(payload)
        if wrapper.get("is_error") or wrapper.get("truncated"):
            audit["rejected_error_or_truncated"] += 1
            continue
        body = wrapper.get("structured")
        if not isinstance(body, dict):
            audit["missing_structured"] += 1
            continue
        metadata = wrapper.get("metadata") or {}
        if any(node.get("dateStatus") == "mismatch" or any("date_mismatch" in str(w) for w in node.get("qualityWarnings", []))
               for node in (wrapper, body, metadata)):
            audit["date_mismatch"] += 1
            continue
        actual_day = body.get("actualTradeDate") or metadata.get("actualTradeDate") or body.get("tradeDate")
        if actual_day is not None and str(actual_day)[:10].replace("-", "") != str(day).replace("-", ""):
            audit["date_mismatch"] += 1
            continue
        code = str((body.get("stock") or {}).get("code") or (wrapper.get("arguments") or {}).get("code") or "")
        points = body.get("points") or []
        if not code or not isinstance(points, list) or not points:
            audit["empty_points"] += 1
            continue
        frame = pd.DataFrame(points)
        if "time" not in frame:
            audit["missing_time"] += 1
            continue
        index = pd.to_datetime(frame["time"], errors="coerce")
        frame.index = index
        frame = frame.loc[~frame.index.isna()].copy()
        for target, fallback in (("close", "price"), ("open", "price"), ("high", "price"), ("low", "price")):
            if target not in frame and fallback in frame:
                frame[target] = frame[fallback]
        if not all(field in frame for field in ("open", "high", "low", "close", "volume")):
            audit["missing_ohlcv"] += 1
            continue
        for point_day, part in frame.groupby(frame.index.strftime("%Y-%m-%d")):
            if str(point_day) != str(day):
                audit["point_wrapper_date_mismatch"] += 1
                continue
            part = part[~part.index.duplicated(keep="last")].sort_index()
            buckets[(code, str(point_day))] = (str(fetched), part)
    by_code: dict[str, dict[str, pd.DataFrame]] = {}
    for (code, day), (_, frame) in buckets.items():
        by_code.setdefault(code, {})[day] = frame
    days = sorted({day for _, day in buckets})
    return by_code, {**dict(audit), "code_days": len(buckets), "codes": len(by_code),
                     "first_date": days[0] if days else None, "last_date": days[-1] if days else None,
                     "availability_basis": "reconstructed observed minute prices; fetched_at retained in frozen source",
                     "overlay_hashes": overlay_hashes}


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [r for r in rows if r.get("status") in {"closed", "completed", "filled"}
              and r.get("exit_reason") != "data_end" and r.get("net_return_pct") is not None]
    # Execution modules use explicit statuses; unrecognized statuses remain
    # visible in the ledger rather than silently counted as realized trades.
    values = np.array([r["net_return_pct"] for r in closed], dtype=float)
    result: dict[str, Any] = {"opportunities": len(rows), "status_counts": dict(Counter(r.get("status", "unknown") for r in rows)),
                              "realized_trades": len(closed)}
    if not len(values):
        return result
    wins, losses = values[values > 0], values[values < 0]
    result.update(mean_net_pct=float(values.mean()), median_net_pct=float(np.median(values)),
                  win_rate_pct=float((values > 0).mean() * 100),
                  mean_win_pct=float(wins.mean()) if len(wins) else None,
                  mean_loss_pct=float(losses.mean()) if len(losses) else None,
                  profit_factor=float(wins.sum() / -losses.sum()) if len(losses) else None,
                  worst_trade_pct=float(values.min()), best_trade_pct=float(values.max()))
    invested_values = [r["invested_net_return_pct"] for r in closed if r.get("invested_net_return_pct") is not None]
    result["mean_invested_net_pct"] = float(np.mean(invested_values)) if invested_values else None
    result["mean_allocation_pct"] = float(np.mean([r.get("invested_notional", 0) / r.get("notional", 100000) for r in closed]) * 100)
    result["two_tranche_rate_pct"] = float(np.mean([len(r.get("legs", [])) == 2 for r in closed]) * 100)
    grouped: dict[str, list[float]] = {}
    for r in closed:
        grouped.setdefault(r["signal_date"][:7], []).append(float(r["net_return_pct"]))
    if len(grouped) >= 5:
        sums = np.array([sum(v) for v in grouped.values()])
        sizes = np.array([len(v) for v in grouped.values()])
        rng = np.random.default_rng(20261027)
        selections = rng.integers(0, len(sums), size=(1000, len(sums)))
        boot = sums[selections].sum(axis=1) / sizes[selections].sum(axis=1)
        result["mean_net_month_cluster_ci95"] = [float(x) for x in np.quantile(boot, [0.025, 0.975])]
    return result


def serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def write_outputs(output: Path, rows: list[dict[str, Any]], trades: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / "all-wave-setups.csv", index=False, encoding="utf-8-sig")
    with (output / "all-opportunities.jsonl").open("w", encoding="utf-8") as target:
        for row in trades:
            target.write(json.dumps(serializable(row), ensure_ascii=False, allow_nan=False) + "\n")
    flat = [{k: json.dumps(serializable(v), ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in trades]
    pd.DataFrame(flat).to_csv(output / "all-opportunities.csv", index=False, encoding="utf-8-sig")
    summary = serializable(summary)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    yearly = []
    for variant, item in summary["variants"].items():
        for year, result in item["by_year"].items():
            yearly.append({"variant": variant, "year": year, **{k: v for k, v in result.items() if not isinstance(v, (dict, list))}})
    pd.DataFrame(yearly).to_csv(output / "yearly-results.csv", index=False, encoding="utf-8-sig")


def run(db: Path, output: Path, minute_overlay: Path | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    config = FirstWaveConfig()
    source_files = (Path(__file__), ROOT / "src/strategy/application/first_wave_pullback.py", ROOT / "scripts/first_wave_execution.py", ROOT / "scripts/first_wave_theme_evidence.py")
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    with db.open("rb") as frozen:
        database_hash = hashlib.file_digest(frozen, "sha256").hexdigest()
    protocol = {"frozen_at": datetime.now(timezone.utc).isoformat(), "configuration": config.to_dict(),
                "source_hashes": source_hashes, "database_sha256": database_hash,
                "minute_overlay": str(minute_overlay) if minute_overlay is not None else None,
                "selection_rule": "every setup, no Top-N or account capital constraint"}
    (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    with ro_connect(db) as con:
        dates, codes, panels, quality = load_panels(con)
        minutes, minute_audit = load_minutes(con, minute_overlay)
        themes = load_theme_evidence(con)
    adjusted = panels["close"] * panels["factor"]
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    prefix_checks = 0
    for j, code in enumerate(codes):
        bars = pd.DataFrame({f: values[:, j] for f, values in panels.items()}, index=dates, copy=False)
        detected = detect_first_waves(bars, code=code, config=config)
        rows.extend(detected)
        if j % 100 == 0:
            print("scanned", j, "/", len(codes), "waves", len(rows), "ready", sum(r["status"] == "setup_ready" for r in rows), flush=True)
    pd.DataFrame(rows).to_csv(output / "all-wave-setups.csv", index=False, encoding="utf-8-sig")
    print("first-wave scan complete", dict(Counter(r["status"] for r in rows)), flush=True)
    from scripts.first_wave_execution import simulate_opportunity

    ready_by_code: dict[str, list[dict[str, Any]]] = {}
    for setup in rows:
        if setup["status"] == "setup_ready":
            ready_by_code.setdefault(setup["code"], []).append(setup)
    for j, code in enumerate(codes):
        ready = ready_by_code.get(code, [])
        if not ready:
            continue
        bars = pd.DataFrame({f: values[:, j] for f, values in panels.items()}, index=dates, copy=False)
        for setup in ready:
            d2 = setup["d2_date"]
            if not d2:
                setup["execution_status"] = "awaiting_d2"
                continue
            # Every eligible setup gets an actual truncation check. Inputs
            # beyond D2 must not alter its first-wave facts.
            prefix = detect_first_waves(bars.iloc[:setup["d2_index"] + 1], code=code, config=config)
            original_facts = {k: v for k, v in setup.items() if not k.startswith(("mainline", "theme", "execution"))}
            matched = next((r for r in prefix if r.get("d1_date") == setup["d1_date"]), None)
            if matched != original_facts:
                raise AssertionError(("First-wave prefix mismatch", code, d2, matched, original_facts))
            prefix_checks += 1
            mainline = price_resonance_mainline(adjusted, panels["volume"], target=j, asof=setup["d0_index"], codes=codes)
            historical_theme = themes.evaluate(code, setup["d0_date"], d2)
            setup["mainline_proxy_passed"] = mainline["passed"]
            setup["mainline_proxy_evidence"] = json.dumps(serializable(mainline), ensure_ascii=False)
            setup["theme_status"] = historical_theme["status"]
            setup["theme_evidence"] = json.dumps(serializable(historical_theme), ensure_ascii=False)
            gates = {"no_mainline": True, "price_resonance_proxy": mainline["passed"], "observed_theme": historical_theme["passed"]}
            variants = [("next_open", h, False, "horizon") for h in (1, 3, 5, 10, 20)]
            variants += [("next_open", 10, staged, "ma5_or_horizon") for staged in (False, True)]
            variants += [("intraday_1450", 10, True, "ma5_or_horizon")]
            for mode, horizon, staged, exit_rule in variants:
                result = simulate_opportunity(bars, d2, code=code, mode=mode, minutes=minutes.get(code),
                                              hold_days=horizon, staged=staged, exit_rule=exit_rule)
                for gate, passed in gates.items():
                    row = {**result, "mainline_gate": gate,
                           "variant": f"{gate}__{mode}__h{horizon}__{'staged' if staged else 'single_full'}__{exit_rule}",
                           "setup_start": setup["start_date"], "d0_date": setup["d0_date"], "d1_date": setup["d1_date"]}
                    if not passed:
                        row = {k: v for k, v in row.items() if k in {
                            "code", "signal_date", "mode", "hold_days", "staged", "exit_rule", "mainline_gate",
                            "variant", "setup_start", "d0_date", "d1_date",
                        }}
                        row.update(status="mainline_unverifiable" if gate == "observed_theme" and historical_theme["status"] == "unknown" else "mainline_rejected",
                                   reason=historical_theme["reason"] if gate == "observed_theme" else mainline["reason"],
                                   legs=[], exit_date=None, exit_reason=None, net_return_pct=None, gross_return_pct=None)
                    trades.append(row)
        print("executed", code, "setups", len(ready), "ledger_rows", len(trades), flush=True)
    years = sorted({day[:4] for day in dates})
    variants_summary: dict[str, Any] = {}
    for variant in sorted({r["variant"] for r in trades}):
        subset = [r for r in trades if r["variant"] == variant]
        by_year = {year: metrics([r for r in subset if r["signal_date"][:4] == year]) for year in years}
        segments = {name: metrics([r for r in subset if start <= r["signal_date"] <= end]) for name, start, end in (
            ("historical_1990_2022", "1990-01-01", "2022-12-31"),
            ("validation_2023_2025", "2023-01-01", "2025-12-31"),
            ("latest_2026", "2026-01-01", "2026-12-31"))}
        variants_summary[variant] = {"overall": metrics(subset), "by_year": by_year, "segments": segments}
    with ro_connect(db) as con:
        database_range = con.execute("SELECT MIN(trade_date),MAX(trade_date),COUNT(*) FROM quotes_daily").fetchone()
        news = con.execute("SELECT tool,MIN(trade_date),MAX(trade_date),COUNT(*) FROM intel_snapshots WHERE tool IN ('news_hotlist','cls_news','official_disclosure_evidence') GROUP BY tool").fetchall()
    current_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    if current_hashes != source_hashes:
        raise RuntimeError("Research implementation changed during the run; results are not a frozen-code experiment")
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(), "database": str(db.resolve()),
        "database_range": database_range, "database_sha256": database_hash, "stock_codes": len(codes), "market_sessions": len(dates),
        "configuration": config.to_dict(), "source_hashes": source_hashes, "quality": quality,
        "setup_counts": dict(Counter(r["status"] for r in rows)), "prefix_checks": prefix_checks,
        "minute_coverage": minute_audit, "news_coverage": news,
        "assumptions": [
            "Every signal is an independent 100000 planned-capital experiment; no capital, position or Top-N selection.",
            "The staged strategy first buys 50% of planned capital; single_full controls buy 100%. Uninvested cash earns zero; overlapping signals are independent.",
            "next_open is a distinct causal daily-bar alternative; it does not verify 14:50 execution.",
            "Price-resonance groups are an explicit statistical mainline proxy, not verified historical named sectors.",
            "Observed themes and minutes are never backfilled into dates without supporting evidence.",
            "The stored symbol universe lacks delisted history; survivor bias remains and is not claimed removed.",
            "Exit rules and 10-session cap are research assumptions added because the original rules omit exits.",
            "Chronological segments are frozen comparisons, not a claim of pre-registered independent out-of-sample discovery.",
            "Report opportunity returns, not a fund-limited portfolio, sequential compounded equity or account CAGR.",
        ],
        "variants": variants_summary,
    }
    write_outputs(output, rows, trades, summary)
    print(json.dumps(serializable({k: v for k, v in summary.items() if k != "variants"}), ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minute-overlay", type=Path)
    args = parser.parse_args()
    run(args.db, args.output, args.minute_overlay)


if __name__ == "__main__":
    main()
