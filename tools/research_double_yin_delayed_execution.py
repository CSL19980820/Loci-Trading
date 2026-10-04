"""One frozen fifth-sample execution sensitivity on two immutable order lists.

TDX supplies ordered price/vol samples, not source timestamps or minute OHLC.
All daily checks below validate the historical dataset after preselection; they
never supply a signal or a replacement stock. Original evidence is read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.metadata
import json
import math
from pathlib import Path
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _resolve_exit  # noqa: E402
from src.market.infrastructure import tdx_minute  # noqa: E402
from tools import research_double_yin_vwap as base  # noqa: E402
from tools import research_double_yin_vwap_data_correction as correction  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-double-yin-delayed-execution"
PROBES = ROOT / "docs/research/2026-10-04-contraction-intraday-feasibility/minute-probes"
POLICIES = ["corrected_low_open", "yin_close_and_open_above_vwap"]
CANCELLED = {"official_suspension", "zero_slot_volume", "upper_limit_at_slot"}
QUALITY = {"rows": 240, "slot_zero_based": 4, "price_tolerance_yuan": .01, "price_float_tolerance": 1e-8,
           "volume_absolute_floor_shares": 100., "volume_relative_tolerance": .001}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_new(path: Path, value, *, raw_decoded: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    # SDK-decoded NaN/Infinity, if any, remain in the raw evidence and are rejected
    # by quality checks. Ordinary receipts and results require strict JSON.
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=raw_decoded)+"\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    return base.sha256(path)


def order_keys() -> pd.DataFrame:
    frame = pd.read_csv(OUTPUT / "order-keys.csv", dtype={"code": str})
    assert len(frame) == 1069 and not frame.duplicated(["decision_date", "code"]).any()
    assert frame.officially_confirmed_suspension_entry.sum() == 1
    return frame


def files_to_bind() -> dict:
    source_files = read(base.OUTPUT / "PLAN.json")["sources"]
    extra = [Path(__file__), Path(correction.__file__), ROOT / "src/market/infrastructure/tdx_minute.py",
             OUTPUT / "PLAN.md", OUTPUT / "input-manifest.json", OUTPUT / "order-keys.csv",
             correction.OUTPUT / "PLAN.json", correction.OUTPUT / "summary.json"]
    paths = {ROOT / name for name in source_files} | set(extra)
    paths.update(ROOT / item["path"] for item in read(OUTPUT / "input-manifest.json")["source_orders"])
    paths.update(ROOT / item["path"].replace("-labels.csv", "-trades.csv")
                 for item in read(OUTPUT / "input-manifest.json")["source_orders"])
    paths.update(PROBES.glob("tdx-*-source-decoded.json"))
    paths.update(PROBES.glob("tdx-*-receipt.json"))
    paths.add(PROBES / "probe-plan.json")
    return {path.relative_to(ROOT).as_posix(): base.sha256(path) for path in sorted(paths)}


def verify() -> dict:
    frozen = read(OUTPUT / "freeze-receipt.json")
    assert files_to_bind() == frozen["files_sha256"], "Frozen input/source/plan changed"
    assert base.sha256(base.DB) == frozen["snapshot_sha256"]
    assert base.sha256(base.GROUPS) == frozen["groups_sha256"]
    assert importlib.metadata.version("tdxpy") == frozen["tdxpy_version"]
    return frozen


def daily_connection():
    conn = sqlite3.connect(f"file:{base.DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def daily(conn, day: str, code: str) -> dict | None:
    row = conn.execute("SELECT trade_date,code,open,high,low,close,volume,source FROM quotes_daily "
                       "WHERE trade_date=? AND code=?", (day, code)).fetchone()
    return dict(row) if row else None


def finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def validate_sequence(rows, quote: dict | None) -> dict:
    out = {"status": "unknown", "reasons": [], "source_timestamp_present": False,
           "date_evidence": "request_parameter_plus_daily_consistency_checks_not_native_timestamp",
           "rows": len(rows) if isinstance(rows, list) else None,
           "slot_index": 4, "synthetic_slot_label": "09:35"}
    if not isinstance(rows, list) or len(rows) != 240:
        out["reasons"].append("row_count_not_240")
        return out
    prices = [finite_number(row.get("price")) if isinstance(row, dict) else None for row in rows]
    volumes = [finite_number(row.get("vol")) if isinstance(row, dict) else None for row in rows]
    if any(value is None for value in [*prices, *volumes]):
        out["reasons"].append("missing_or_nonfinite_price_volume")
        return out
    price, volume = np.asarray(prices), np.asarray(volumes)
    out.update(slot_price=float(price[4]), slot_volume_lots=float(volume[4]), slot_volume_shares=float(volume[4]*100))
    if (volume < 0).any() or (price < 0).any() or ((volume > 0) & (price <= 0)).any():
        out["reasons"].append("invalid_sample_values")
    if not quote or quote.get("source") != "tdx":
        out["reasons"].append("missing_verified_tdx_daily_quote")
        return out
    close, low, high, shares = [finite_number(quote.get(key)) for key in ("close", "low", "high", "volume")]
    if any(value is None or value <= 0 for value in (close, low, high, shares)) or high < low:
        out["reasons"].append("invalid_daily_check_values")
        return out
    tail_delta = float(price[-1]-close)
    shares_delta = float(volume.sum()*100-shares)
    tolerance = max(100., shares*.001)
    out.update(tail_price_delta_yuan=tail_delta, tail_price_abs_delta_yuan=abs(tail_delta),
               volume_sum_lots=float(volume.sum()), volume_sum_shares=float(volume.sum()*100),
               daily_volume_shares=shares, volume_signed_delta_shares=shares_delta,
               volume_abs_delta_shares=abs(shares_delta), volume_relative_delta=shares_delta/shares,
               volume_tolerance_shares=tolerance, tail_exact_numeric_match=tail_delta == 0.,
               volume_exact_numeric_match=shares_delta == 0.)
    if abs(tail_delta) > .01+1e-8:
        out["reasons"].append("tail_price_mismatch")
    if abs(shares_delta) > tolerance:
        out["reasons"].append("daily_volume_mismatch")
    active = price[price > 0]
    if ((active < low-.01-1e-8) | (active > high+.01+1e-8)).any():
        out["reasons"].append("positive_sample_outside_daily_range")
    if not out["reasons"]:
        out["status"] = "valid"
        out["match_class"] = "exact_numeric" if tail_delta == 0 and shares_delta == 0 else "within_frozen_tolerance"
    return out


def cache_folder(day: str, code: str) -> Path:
    return OUTPUT / "cache" / f"{day}-{code}"


def cached(day: str, code: str) -> dict | None:
    folder = cache_folder(day, code)
    for attempt in (1, 2):
        path = folder / f"attempt-{attempt:02d}-receipt.json"
        if not path.exists():
            continue
        receipt = read(path)
        assert receipt["requested_date"] == day and receipt["code"] == code
        raw = folder / f"attempt-{attempt:02d}-source-decoded.json"
        if receipt.get("raw_sha256"):
            assert raw.exists() and base.sha256(raw) == receipt["raw_sha256"]
        if receipt["status"] != "transport_error" or attempt == 2:
            return receipt
    return None


def connection():
    from tdxpy.hq import TdxHq_API
    errors = []
    for host, port in tdx_minute._SERVERS:
        client = TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=True)
        try:
            if client.connect(host, port, time_out=8):
                return client, {"host": host, "port": port}
            errors.append(f"{host}:{port} returned_false")
            tdx_minute._close_client(client)
        except Exception as exc:
            errors.append(f"{host}:{port} {type(exc).__name__}")
            tdx_minute._close_client(client)
    raise RuntimeError("TDX connection unavailable: "+", ".join(errors))


def cache_hashes() -> dict:
    return {path.relative_to(OUTPUT).as_posix(): base.sha256(path)
            for path in sorted((OUTPUT / "cache").glob("*/attempt-*.json"))}


def verify_collection() -> dict:
    collection = read(OUTPUT / "collection-summary.json")
    assert collection["complete"] and collection["keys"] == 1069
    assert collection["quality_csv_sha256"] == base.sha256(OUTPUT / "collection-quality.csv")
    assert collection["cache_sha256"] == cache_hashes()
    return collection


def collect() -> None:
    verify()
    if (OUTPUT / "collection-summary.json").exists():
        verify_collection()
        print("Reuse completed immutable collection", flush=True)
        return
    keys, conn = order_keys(), daily_connection()
    client, server, last_query, calls, failed_streak = None, None, 0., 0, 0
    try:
        for item in keys.itertuples():
            if item.officially_confirmed_suspension_entry:
                continue
            day, code = item.decision_date, item.code
            if cached(day, code) is not None:
                continue
            folder, quote = cache_folder(day, code), daily(conn, day, code)
            for attempt in (1, 2):
                request_path = folder / f"attempt-{attempt:02d}-request.json"
                raw_path = folder / f"attempt-{attempt:02d}-source-decoded.json"
                receipt_path = folder / f"attempt-{attempt:02d}-receipt.json"
                if receipt_path.exists():
                    continue
                if request_path.exists():
                    request = read(request_path)
                    if raw_path.exists():
                        quality = validate_sequence(read(raw_path), quote)
                        write_new(receipt_path, {**request, "status": quality["status"], "quality": quality,
                                  "raw_sha256": base.sha256(raw_path), "recovered_from_raw": True, "completed_at": base.now()})
                        break
                    write_new(receipt_path, {**request, "status": "transport_error", "reason": "interrupted_without_response",
                                             "completed_at": base.now()})
                    continue
                if client is None:
                    client, server = connection()
                request = {"code": code, "requested_date": day, "market": 1 if code.startswith("6") else 0,
                           "method": "get_history_minute_time_data", "date_argument": int(day.replace("-", "")),
                           "server": server, "attempt": attempt, "started_at": base.now(),
                           "tdxpy_version": importlib.metadata.version("tdxpy"), "source_timestamp_present": False}
                write_new(request_path, request)
                wait = .125-(time.monotonic()-last_query)
                if wait > 0:
                    time.sleep(wait)
                last_query = time.monotonic()
                calls += 1
                try:
                    rows = client.get_history_minute_time_data(request["market"], code, request["date_argument"])
                except Exception as exc:
                    write_new(receipt_path, {**request, "status": "transport_error", "reason": type(exc).__name__,
                                             "completed_at": base.now()})
                    tdx_minute._close_client(client)
                    client, server = None, None
                    if attempt == 1:
                        time.sleep(1.)
                    continue
                digest = write_new(raw_path, rows, raw_decoded=True)
                quality = validate_sequence(rows, quote)
                write_new(receipt_path, {**request, "status": quality["status"], "quality": quality,
                                         "raw_sha256": digest, "completed_at": base.now()})
                break
            receipt = cached(day, code)
            if receipt is None:
                raise AssertionError("Requested key has no terminal receipt")
            failed_streak = failed_streak+1 if receipt["status"] == "transport_error" else 0
            if calls % 50 == 0 or receipt["status"] != "valid":
                print(json.dumps({"queries_this_run": calls, "date": day, "code": code, "status": receipt["status"]}), flush=True)
            if failed_streak >= 5:
                raise RuntimeError("Five consecutive keys exhausted transport retries; preserve checkpoint and stop")
    finally:
        if client is not None:
            tdx_minute._close_client(client)
        conn.close()
    ledger = []
    for item in keys.itertuples():
        receipt = cached(item.decision_date, item.code) if not item.officially_confirmed_suspension_entry else None
        assert item.officially_confirmed_suspension_entry or receipt is not None
        ledger.append({"segment": item.segment, "decision_date": item.decision_date, "code": item.code,
                       "status": "official_suspension" if item.officially_confirmed_suspension_entry else receipt["status"],
                       **(receipt.get("quality", {}) if receipt else {})})
    frame = pd.DataFrame(ledger)
    if not (OUTPUT / "collection-summary.json").exists():
        frame.to_csv(OUTPUT / "collection-quality.csv", index=False)
        write_new(OUTPUT / "collection-summary.json", {"completed_at": base.now(), "keys": len(keys),
                  "status_counts": dict(Counter(row["status"] for row in ledger)), "queries_this_run": calls,
                  "match_classes": dict(Counter(row.get("match_class", "not_valid") for row in ledger)),
                  "quality_csv_sha256": base.sha256(OUTPUT / "collection-quality.csv"),
                  "cache_sha256": cache_hashes(), "complete": True})
    verify()
    print(json.dumps({"collection_complete": True, "status_counts": dict(Counter(row["status"] for row in ledger))}), flush=True)


def execute_order(data: dict, cfg, row: int, col: int, evidence: dict, *, officially_suspended: bool = False):
    day, code = str(data["dates"][row]), str(data["codes"][col])
    event = {"signal_date": day, "code": code, "entry_mode": "fifth_tdx_sample_proxy", "slot_index": 4,
             "source_timestamp_present": False, "synthetic_slot_label": "09:35", "status": "",
             "opportunity_net_pct": None, "slot_price": evidence.get("slot_price"),
             "slot_volume_lots": evidence.get("slot_volume_lots")}
    if officially_suspended:
        return None, {**event, "status": "official_suspension", "opportunity_net_pct": 0.}
    if evidence.get("status") != "valid":
        return None, {**event, "status": "unknown_sample_evidence", "sample_reasons": evidence.get("reasons", [])}
    price, volume = finite_number(evidence.get("slot_price")), finite_number(evidence.get("slot_volume_lots"))
    if price is None or volume is None or price < 0 or volume < 0:
        return None, {**event, "status": "unknown_slot_values"}
    if volume == 0:
        return None, {**event, "status": "zero_slot_volume", "opportunity_net_pct": 0.}
    if price <= 0:
        return None, {**event, "status": "unknown_slot_values"}
    factor = float(data["factors"][row, col])
    if not data["known"][row, col] or not np.isfinite(factor) or factor <= 0 or not np.isfinite(data["upper"][row, col]):
        return None, {**event, "status": "unknown_limit_or_factor"}
    if price >= data["upper"][row, col]-.005:
        return None, {**event, "status": "upper_limit_at_slot", "opportunity_net_pct": 0.}
    basis = price*factor
    exit_idx, exit_price, reason = _resolve_exit(
        col=col, entry_idx=row, entry_price=basis, planned_exit=row+cfg.hold_days, cfg=cfg,
        high_a=data["economic_high"], low_a=data["economic_low"], close_a=data["economic_close"],
        open_a=data["economic_open"], one_word_down=data["strict_down"], volume_a=data["volume"],
        last_index=len(data["dates"])-1)
    event.update(entry_date=day, entry_price=price, entry_factor=factor)
    if exit_idx is None or reason == "data_end" or not np.isfinite(exit_price) or exit_price <= 0:
        return None, {**event, "status": "unresolved_exit"}
    assert exit_idx > row, "T+1 must be retained"
    exit_factor = float(data["factors"][exit_idx, col])
    raw_exit = float(exit_price/exit_factor)
    for raw, economic in ((data["close"], data["economic_close"]), (data["open"], data["economic_open"])):
        if exit_price == economic[exit_idx, col]:
            raw_exit = float(raw[exit_idx, col])
            break
    gross = float((exit_price/basis-1)*100)
    trade = base.Trade(code=code, signal_date=day, entry_date=day, entry_price=price,
                       exit_date=str(data["dates"][exit_idx]), exit_price=raw_exit, hold_days=exit_idx-row,
                       gross_return_pct=gross, net_return_pct=gross-cfg.round_trip_cost_pct(),
                       mae_pct=float("nan"), mfe_pct=float("nan"), exit_reason=reason,
                       entry_factor=factor, exit_factor=exit_factor)
    event.update(status="closed", exit_date=trade.exit_date, exit_price=raw_exit, exit_reason=reason,
                 opportunity_net_pct=trade.net_return_pct, mae_mfe_status="unavailable_entry_day_intraday_path")
    return trade, event


def labels(events: list[dict], cutoff: str) -> pd.DataFrame:
    rows = []
    for event in events:
        status, available, net = "unresolved", None, None
        if event["status"] == "closed" and event["signal_date"] < event["exit_date"] <= cutoff:
            status, available, net = "closed", event["exit_date"], event["opportunity_net_pct"]
        elif event["status"] in CANCELLED:
            status, available, net = "cancelled", event["signal_date"], 0.
        rows.append({"decision_date": event["signal_date"], "code": event["code"], "label_status": status,
                     "label_available_date": available, "label_available_at": f"{available}T15:00:00+08:00" if available else None,
                     "net_return_pct": net, "execution_reason": event["status"],
                     "entry_date": event.get("entry_date"), "exit_date": event.get("exit_date")})
    return pd.DataFrame(rows)


def original_folder(segment: str) -> Path:
    return base.OUTPUT if segment == "train" else correction.OUTPUT


def evaluate(segment: str) -> dict:
    start, end = base.SPLITS[segment]
    print(f"Prepare delayed execution {segment}", flush=True)
    stage = base.prepare(start, end)
    data, overlay = correction.overlay_volume(stage["data"], start, end)
    overlay_path = OUTPUT / f"{segment}-official-overlay.json"
    if overlay_path.exists():
        assert read(overlay_path) == overlay
    else:
        write_new(overlay_path, overlay)
    dates = {str(day): row for row, day in enumerate(data["dates"])}
    codes = {str(code): col for col, code in enumerate(data["codes"])}
    keys = order_keys().query("segment == @segment")
    runs, budgets, changes = {}, {}, []
    for policy in POLICIES:
        source_labels = pd.read_csv(original_folder(segment) / f"{segment}-{policy}-labels.csv", dtype={"code": str})
        assert not source_labels.label_status.eq("unresolved").any(), "Original baseline must have complete labels"
        fixed = keys[keys.in_B if policy == POLICIES[1] else keys.in_corrected_low_open]
        assert set(zip(fixed.decision_date, fixed.code)) == set(zip(source_labels.decision_date, source_labels.code))
        trades, events = [], []
        for item in fixed.itertuples():
            receipt = cached(item.decision_date, item.code) if not item.officially_confirmed_suspension_entry else None
            evidence = receipt.get("quality", {"status": "unknown", "reasons": [receipt["status"]]}) if receipt else {"status": "unknown"}
            trade, event = execute_order(data, stage["ctx"]["config"], dates[item.decision_date], codes[item.code], evidence,
                                         officially_suspended=bool(item.officially_confirmed_suspension_entry))
            if trade is not None:
                trades.append(trade)
            events.append(event)
        trades, events, counts = base.guard_holding_paths(trades, events, data)
        labelled = labels(events, end)
        pd.DataFrame([trade.to_dict(include_factors=True) for trade in trades], columns=list(base.Trade.__dataclass_fields__)).to_csv(
            OUTPUT / f"{segment}-{policy}-trades.csv", index=False)
        pd.DataFrame(events).to_csv(OUTPUT / f"{segment}-{policy}-events.csv", index=False)
        labelled.to_csv(OUTPUT / f"{segment}-{policy}-labels.csv", index=False)
        budgets[policy] = base.order_budget(labelled, stage["days"])
        budgets[f"{policy}_original_open"] = base.order_budget(source_labels, stage["days"])
        unknown = int(labelled.label_status.eq("unresolved").sum())
        runs[policy] = {"metrics": base.metrics(trades), "selected_orders": len(fixed), "execution_accounting": counts,
                        "label_accounting": dict(Counter(labelled.label_status)), "unresolved_selected": unknown,
                        "slots": len(stage["days"])*2, "slot_mean": None if unknown else float(labelled.net_return_pct.sum()/(len(stage["days"])*2)),
                        "original_open_slot_mean": float(source_labels.net_return_pct.sum()/(len(stage["days"])*2)),
                        "active_months": len({trade.entry_date[:7] for trade in trades})}
        original_trades = pd.read_csv(original_folder(segment) / f"{segment}-{policy}-trades.csv", dtype={"code": str})
        old_map = {(row.signal_date, row.code): row for row in original_trades.itertuples()}
        new_map = {(trade.signal_date, trade.code): trade for trade in trades}
        for event in events:
            key = event["signal_date"], event["code"]
            old, new = old_map.get(key), new_map.get(key)
            changes.append({"policy": policy, "decision_date": key[0], "code": key[1],
                            "new_status": event["status"], "old_closed": old is not None, "new_closed": new is not None,
                            "old_entry_price": old.entry_price if old else None, "new_entry_price": new.entry_price if new else None,
                            "entry_price_change_pct": (new.entry_price/old.entry_price-1)*100 if old and new else None,
                            "old_exit_date": old.exit_date if old else None, "new_exit_date": new.exit_date if new else None,
                            "old_net_pct": old.net_return_pct if old else None, "new_net_pct": new.net_return_pct if new else None})
    comparisons, pair_rows = {}, []
    for name, left, right in [(f"{p}_vs_original_open", p, f"{p}_original_open") for p in POLICIES]+[("B_vs_low_at_fifth_slot", POLICIES[1], POLICIES[0])]:
        frame = budgets[left].copy()
        frame["delta_net_sum"] = frame.net_sum-budgets[right].net_sum
        frame["comparison"], frame["segment"] = name, segment
        pair_rows.append(frame)
        comparisons[name] = None if frame.delta_net_sum.isna().any() else base.paired_bootstrap(frame)
    pd.concat(pair_rows, ignore_index=True).to_csv(OUTPUT / f"{segment}-paired-calendar.csv", index=False)
    pd.DataFrame(changes).to_csv(OUTPUT / f"{segment}-execution-changes.csv", index=False)
    summary = {"segment": segment, "completed_at": base.now(), "runs": runs, "paired_comparisons": comparisons,
               "fixed_preselection_identity": "passed", "sensitivity_only": True, "original_B_strict_pass": False,
               "artifact_sha256": {path.name: base.sha256(path) for path in sorted(OUTPUT.glob(f"{segment}-*"))
                                   if path.suffix == ".csv" or path == overlay_path}}
    write_new(OUTPUT / f"{segment}-summary.json", summary)
    return summary


def evaluate_all() -> None:
    verify()
    collection = verify_collection()
    if (OUTPUT / "summary.json").exists():
        raise FileExistsError("Sensitivity already completed")
    stages = {}
    for segment in base.SPLITS:
        path = OUTPUT / f"{segment}-summary.json"
        stages[segment] = read(path) if path.exists() else evaluate(segment)
        assert all(base.sha256(OUTPUT / name) == digest for name, digest in stages[segment]["artifact_sha256"].items())
        verify()
    write_new(OUTPUT / "summary.json", {"completed_at": base.now(), "stages": stages, "sensitivity_only": True,
              "no_new_nomination": True, "original_B_strict_pass": False, "collection": collection})
    print(json.dumps({"completed": True, "groups": 6, "original_B_strict_pass": False}), flush=True)


def self_check() -> dict:
    rows = [{"price": 10., "vol": 1.} for _ in range(240)]
    quote = {"source": "tdx", "close": 10., "low": 9., "high": 11., "volume": 24000.}
    assert validate_sequence(rows, quote)["status"] == "valid"
    assert validate_sequence(rows[:-1], quote)["status"] == "unknown"
    damaged = [dict(row) for row in rows]
    damaged[4].pop("vol")
    assert validate_sequence(damaged, quote)["status"] == "unknown"
    assert validate_sequence(rows, {**quote, "volume": 2400000.})["status"] == "unknown"
    zero_outside = [dict(row) for row in rows]
    zero_outside[0] = {"price": 12., "vol": 0.}
    assert "positive_sample_outside_daily_range" in validate_sequence(zero_outside, quote)["reasons"]
    cfg = base.config("2025-01-07")
    dates = ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    data = {key: np.full((5, 1), value) for key, value in
            {"open": 10., "high": 12., "low": 9.5, "close": 11., "volume": 100., "factors": 1., "upper": 20.}.items()}
    data.update(dates=dates, codes=["600001"], known=np.ones((5, 1), dtype=bool), strict_down=np.zeros((5, 1), dtype=bool))
    data["low"][1, 0], data["low"][2, 0] = 8., 9.
    for key in ("open", "high", "low", "close"):
        data[f"economic_{key}"] = data[key]*data["factors"]
    evidence = {"status": "valid", "slot_price": 9., "slot_volume_lots": 1.}
    trade, event = execute_order(data, cfg, 1, 0, evidence)
    assert trade.entry_price == 9. and trade.exit_date == dates[-1] and trade.exit_reason == "hold_expired"
    assert data["open"][1, 0] == 10. and trade.hold_days == 3 and math.isnan(trade.mae_pct)
    expensive, _ = execute_order(data, cfg, 1, 0, {**evidence, "slot_price": 11.})
    assert expensive.exit_date == dates[2] and expensive.exit_price == 10. and expensive.exit_reason == "stop_loss"
    assert expensive.net_return_pct < -6.21  # gap uses original next-session open, not a synthetic stop price
    assert event["exit_date"] > event["entry_date"]  # entry-day low8 cannot trigger a T+0 sale
    _, zero = execute_order(data, cfg, 1, 0, {**evidence, "slot_volume_lots": 0.})
    _, missing = execute_order(data, cfg, 1, 0, {"status": "unknown"})
    _, suspended = execute_order(data, cfg, 1, 0, {}, officially_suspended=True)
    _, upper = execute_order(data, cfg, 1, 0, {**evidence, "slot_price": 20.})
    for value in (zero, suspended, upper):
        labelled = labels([value], dates[-1])
        assert labelled.label_status.eq("cancelled").all() and labelled.net_return_pct.eq(0).all()
    labelled = labels([missing], dates[-1])
    assert labelled.label_status.eq("unresolved").all() and base.order_budget(labelled, [dates[1]]).net_sum.isna().all()
    damaged_data = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in data.items()}
    damaged_data["volume"][2, 0] = np.nan
    closed, guarded, _ = base.guard_holding_paths([trade], [event], damaged_data)
    assert not closed and labels(guarded, dates[-1]).label_status.eq("unresolved").all()
    correction.self_check()
    conn = daily_connection()
    probe_checks = []
    try:
        for path in sorted(PROBES.glob("tdx-*-source-decoded.json")):
            day, code = path.name[4:14], path.name[15:21]
            assert validate_sequence(read(path), daily(conn, day, code))["status"] == "valid"
            probe_checks.append(f"{day}/{code}")
    finally:
        conn.close()
    assert len(probe_checks) == 4
    return {"status": "passed", "checks": ["exactly240", "missing_slot_unknown", "lot_share_scale_rejected_if_wrong", "positive_zero_volume_prices_still_range_checked",
            "new_entry_basis_changes_stop", "four_sessions_and_Tplus1", "gap_uses_unchanged_daily_open", "zero_volume_cancel_not_unknown",
            "unknown_budget_null", "upper_limit_at_new_price", "official_suspension_cancel", "missing_holding_path_unknown",
            "official_overlay_copy_and_dates", "entry_day_MAE_MFE_not_claimed", "four_existing_probes_pass_frozen_QA"],
            "reused_probe_keys": probe_checks, "new_network_requests": 0, "new_real_returns": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["self-check", "freeze", "collect", "evaluate", "run"])
    phase = parser.parse_args().phase
    if phase == "self-check":
        print(json.dumps(self_check()), flush=True)
    elif phase == "freeze":
        if (OUTPUT / "freeze-receipt.json").exists():
            raise FileExistsError("Execution sensitivity already frozen")
        manifest = read(OUTPUT / "input-manifest.json")
        assert base.sha256(OUTPUT / "order-keys.csv") == manifest["keyset_sha256"]
        for item in manifest["source_orders"]:
            assert base.sha256(ROOT / item["path"]) == item["sha256"]
        correction.verify()
        write_new(OUTPUT / "self-check.json", self_check())
        write_new(OUTPUT / "freeze-receipt.json", {"created_at": base.now(), "files_sha256": files_to_bind(),
                  "snapshot_sha256": base.sha256(base.DB), "groups_sha256": base.sha256(base.GROUPS),
                  "tdxpy_version": importlib.metadata.version("tdxpy"), "quality": QUALITY, "policies": POLICIES,
                  "order_keys": len(order_keys()), "new_network_requests": 0, "new_real_returns": 0})
        print(json.dumps({"frozen": True, "receipt_sha256": base.sha256(OUTPUT / "freeze-receipt.json")}), flush=True)
    elif phase == "collect":
        collect()
    elif phase == "evaluate":
        evaluate_all()
    else:
        collect()
        evaluate_all()


if __name__ == "__main__":
    main()
