"""Frozen-order incidence of a closing-limit mask on earlier stop triggers.

Read-only price facts, not a replay: no alternative exits or return calculations.
The source CSV reader deliberately excludes all return and exit-price columns.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/research/2026-10-04-exit-causality/incidence"
SAMPLED = ROOT / "docs/research/2026-10-04-contraction-sampled-entry"
VWAP = ROOT / "docs/research/2026-10-04-contraction-vwap"
YIN = ROOT / "docs/research/2026-10-04-double-yin-delayed-execution"
CORRECTION = ROOT / "docs/research/2026-10-04-double-yin-vwap/data-correction"
DBS = {"chinext": ROOT / ".local/chinext-payoff-20261004/market.db",
       "main": ROOT / ".local/multi-strategy-scoring-20261004/market.db"}
SPLITS = {"train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}
YIN_HALTS = {
    "605389": ["2025-07-04", "2025-07-07", "2025-07-08", "2025-07-09", "2025-07-10"],
    "002036": ["2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29"],
}
SAMPLED_HALTS = {("2025-05-19", "300506"), ("2025-06-20", "300959")}
SPECS = [dict(family="contraction_sampled", segment="train", policy=a, db="chinext", kind="orders",
              path=str((SAMPLED / "train" / f"{a}-orders.csv").relative_to(ROOT)))
         for a in ("sampled_early", "sampled_next_open", "original_eod")]
SPECS += [dict(family="contraction_original_later", segment=s, policy="corrected_original", db="chinext",
               kind="orders", path=str((VWAP / s / "corrected_original-orders.csv").relative_to(ROOT)))
          for s in ("validation_2025h2", "observed_2026")]
SPECS += [dict(family="double_yin_sampled", segment=s, policy=p, db="main", kind="labels",
               path=str((YIN / f"{s}-{p}-labels.csv").relative_to(ROOT)))
          for s in SPLITS for p in ("corrected_low_open", "yin_close_and_open_above_vwap")]


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(clean(value), handle, ensure_ascii=False, indent=2, allow_nan=False)


def finite(value):
    return value is not None and not pd.isna(value) and np.isfinite(value)


def positive(value):
    return finite(value) and value > 0


def csv_subset(path, columns):
    """Outcome-size and exit-price columns never enter this analysis."""
    assert not any("return" in c or c in ("exit_price", "opportunity_net_pct") for c in columns)
    return pd.read_csv(path, usecols=lambda c: c in columns, dtype={"code": str}, float_precision="round_trip")


def protected_files(output):
    paths = {Path(__file__), output / "PLAN.md", SAMPLED / "PLAN.json", SAMPLED / "freeze-receipt.json",
             SAMPLED / "train/completion-receipt.json", SAMPLED / "data-evidence/official-halt-receipt.json",
             VWAP / "PLAN.json", VWAP / "freeze-receipt.json", YIN / "PLAN.md", YIN / "freeze-receipt.json",
             YIN / "order-keys.csv", CORRECTION / "PLAN.json"}
    for spec in SPECS:
        path = ROOT / spec["path"]
        paths.add(path)
        if spec["kind"] == "labels":
            paths.update([path.with_name(path.name.replace("-labels.csv", "-events.csv")),
                          path.with_name(path.name.replace("-labels.csv", "-trades.csv"))])
    paths.update(SAMPLED.glob("data-evidence/*.pdf"))
    paths.update(CORRECTION.glob("announcements/*.pdf"))
    paths.update(YIN.glob("*-official-overlay.json"))
    paths.update(ROOT / p for p in (
        "src/backtest/application/execution_contract.py", "src/backtest/application/engine.py",
        "src/formula/domain/board.py", "src/market/infrastructure/store_rw.py",
        "tools/research_contraction_sampled_entry.py", "tools/research_contraction_vwap.py",
        "tools/research_double_yin_delayed_execution.py", "tools/research_double_yin_vwap_data_correction.py",
        "tools/research_double_yin_regime.py", "tools/research_double_yin_redesign.py"))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def verify_halt_contracts():
    receipt = read(SAMPLED / "data-evidence/official-halt-receipt.json")
    assert {(r["trade_date"], r["code"]) for r in receipt["records"]} == SAMPLED_HALTS
    for r in receipt["records"]:
        assert r["content_checked"] and r["session"] == "whole_day_from_open"
        assert sha(SAMPLED / "data-evidence" / r["file"]) == r["sha256"]
    plan = read(CORRECTION / "PLAN.json")
    assert plan["suspension_dates"] == YIN_HALTS
    for r in plan["sources"]:
        assert sha(CORRECTION / r["file"]) == r["sha256"]


def freeze(output):
    verify_halt_contracts()
    plan = dict(created_at=now(), purpose="incidence_only_no_counterfactual_exits_or_returns", specs=SPECS,
                files_sha256=protected_files(output), databases_sha256={k: sha(p) for k, p in DBS.items()},
                self_checks=self_check(), stop_pct=-6., offsets_after_actual_entry=[1, 2, 3],
                price_columns_read=["open", "high", "low", "close", "volume", "source"],
                source_return_and_exit_price_columns_excluded=True,
                unknown_rule="Do not establish first trigger after an earlier unknown possible trading bar",
                expiry_close_constraint_not_redefined=True)
    write_new(output / "PLAN.json", plan)
    write_new(output / "freeze-receipt.json", dict(created_at=now(), plan_sha256=sha(output / "PLAN.json")))
    print(json.dumps(dict(frozen=True, plan_sha256=sha(output / "PLAN.json"))))


def verify(output):
    plan = read(output / "PLAN.json")
    assert sha(output / "PLAN.json") == read(output / "freeze-receipt.json")["plan_sha256"]
    assert protected_files(output) == plan["files_sha256"]
    assert {k: sha(p) for k, p in DBS.items()} == plan["databases_sha256"]
    return plan


def load_orders(spec):
    path = ROOT / spec["path"]
    if spec["kind"] == "orders":
        frame = csv_subset(path, ["signal_date", "decision_date", "code", "label_status", "label_reason",
            "entry_date", "entry_price", "entry_factor", "exit_date", "exit_reason"])
        frame = frame.rename(columns={"label_reason": "source_reason"})
    else:
        frame = csv_subset(path, ["decision_date", "code", "label_status", "execution_reason", "entry_date", "exit_date"])
        events = csv_subset(path.with_name(path.name.replace("-labels.csv", "-events.csv")),
            ["signal_date", "code", "status", "entry_date", "entry_price", "entry_factor", "exit_date", "exit_reason"])
        events = events.rename(columns={"signal_date": "decision_date"})
        frame = frame.merge(events, on=["decision_date", "code"], how="left", validate="one_to_one", suffixes=("", "_event"))
        assert frame.status.notna().all()
        for col in ("entry_date", "exit_date"):
            assert (frame[col].fillna("") == frame[f"{col}_event"].fillna("")).all()
        frame = frame.rename(columns={"execution_reason": "source_reason"})
        frame["signal_date"] = frame.decision_date
        trades = csv_subset(path.with_name(path.name.replace("-labels.csv", "-trades.csv")),
            ["signal_date", "code", "entry_date", "entry_price", "entry_factor", "exit_date", "exit_reason"])
        closed = frame.loc[frame.label_status.eq("closed"), trades.columns].sort_values(["signal_date", "code"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(closed, trades.sort_values(["signal_date", "code"]).reset_index(drop=True), check_dtype=False)
        keys = csv_subset(YIN / "order-keys.csv", ["segment", "decision_date", "code", "in_corrected_low_open", "in_B"])
        keys = keys[keys.segment.eq(spec["segment"])]
        selected = keys[keys.in_B if spec["policy"] == "yin_close_and_open_above_vwap" else keys.in_corrected_low_open]
        assert set(zip(frame.decision_date, frame.code)) == set(zip(selected.decision_date, selected.code))
    assert not frame.duplicated(["signal_date", "code"]).any()
    assert frame.label_status.isin(["closed", "cancelled", "unresolved"]).all()
    frame = frame.rename(columns={"label_status": "source_label_status", "exit_date": "source_exit_date",
                                  "exit_reason": "source_exit_reason"})
    for key in ("family", "segment", "policy", "db"):
        frame[key] = spec[key]
    frame["group_id"] = f"{spec['family']}/{spec['segment']}/{spec['policy']}"
    return frame


class Market:
    """Direct snapshot facts and the existing raw-price reference formula."""
    def __init__(self, db, codes):
        self.conn = sqlite3.connect(f"file:{DBS[db].as_posix()}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self.dates = [r[0] for r in self.conn.execute("SELECT trade_date FROM trading_calendar WHERE trade_date>=? AND trade_date<=? ORDER BY trade_date",
                                                  ("2023-01-01", "2026-09-30"))]
        assert self.dates and self.dates == sorted(set(self.dates))
        self.indices = {d: i for i, d in enumerate(self.dates)}
        self.panels = {}
        halts = (SAMPLED_HALTS if db == "chinext" else {(d, c) for c, dates in YIN_HALTS.items() for d in dates})
        for code in sorted(codes):
            quotes = {r["trade_date"]: dict(r) for r in self.conn.execute(
                "SELECT trade_date,open,high,low,close,volume,source FROM quotes_daily WHERE code=? AND trade_date>=? AND trade_date<=? ORDER BY trade_date",
                (code, "2023-01-01", "2026-09-30"))}
            factors = self.conn.execute("SELECT trade_date,hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date",
                                        (code, "2026-09-30")).fetchall()
            factor_dates, factor_values = [r[0] for r in factors], [r[1] for r in factors]
            last_close = last_factor = np.nan
            last_date = None
            panel = []
            ratio = .20 if code.startswith("30") else .10
            for day in self.dates:
                raw = quotes.get(day, {})
                values = {k: float(raw[k]) if raw.get(k) is not None else np.nan for k in ("open", "high", "low", "close", "volume")}
                original_volume = values["volume"]
                official_halt = (day, code) in halts
                if official_halt:
                    assert not positive(original_volume)
                    values["volume"] = 0.
                fi = bisect_right(factor_dates, day) - 1
                factor = float(factor_values[fi]) if fi >= 0 else np.nan
                reference = last_close * last_factor / factor if positive(factor) else np.nan
                known = positive(reference)
                lower = math.floor(reference * (1. - ratio) * 100 + .5 + 1e-9) / 100 if known else np.nan
                down = bool(values["close"] <= lower + .005 or not known)
                panel.append(dict(trade_date=day, **values, raw_volume_before_overlay=original_volume, factor=factor,
                    factor_observation_date=factor_dates[fi] if fi >= 0 else None,
                    previous_valid_close=last_close, previous_valid_factor=last_factor, previous_valid_date=last_date,
                    reference_raw=reference, lower_limit_raw=lower, reference_known=bool(known),
                    model_strict_down=down, official_halt=official_halt, source=raw.get("source"), quote_row_present=bool(raw)))
                if positive(values["close"]) and positive(values["volume"]):
                    last_close, last_factor, last_date = values["close"], factor, day
            self.panels[code] = panel

    def close(self):
        self.conn.close()


def window_facts(day, stop_economic, offset):
    out = {**day, "offset_after_entry": offset, "stop_economic": stop_economic,
           "stop_raw_on_day": stop_economic / day["factor"] if positive(day["factor"]) else np.nan,
           "stop_touched": None, "touch_evidence": "unknown", "ohlc_complete": False}
    v, low, factor = day["volume"], day["low"], day["factor"]
    if finite(v) and v == 0:
        out.update(stop_touched=False, touch_evidence="known_no_trading")
    elif positive(v) and positive(low) and positive(factor):
        out.update(stop_touched=bool(low * factor <= stop_economic), touch_evidence="known_positive_volume_low")
    if positive(low) and positive(factor):
        out["observed_low_at_or_below_stop"] = bool(low * factor <= stop_economic)
    else:
        out["observed_low_at_or_below_stop"] = None
    o, h, c = day["open"], day["high"], day["close"]
    valid = all(positive(x) for x in (o, h, low, c)) and h >= max(o, c) and low <= min(o, c)
    out["ohlc_complete"] = bool(valid)
    out["nonflat_high_above_low"] = bool(h > low) if valid else None
    out["open_at_or_below_stop"] = bool(o * factor <= stop_economic) if positive(o) and positive(factor) else None
    out["open_below_stop"] = bool(o * factor < stop_economic) if positive(o) and positive(factor) else None
    if not day["reference_known"]:
        out["mask_evidence"] = "unknown_reference"
    elif not positive(c):
        out["mask_evidence"] = "unknown_close"
    else:
        out["mask_evidence"] = "close_at_lower_masked" if day["model_strict_down"] else "not_masked"
    if positive(o) and day["reference_known"]:
        lower = day["lower_limit_raw"]
        out["open_relative_lower"] = "below_lower" if o < lower - .005 else "above_lower" if o > lower + .005 else "at_lower"
        out["high_above_lower"] = bool(h > lower + .005) if positive(h) else None
        out["low_below_lower"] = bool(low < lower - .005) if positive(low) else None
    else:
        out["open_relative_lower"] = "unknown"
        out["high_above_lower"] = out["low_below_lower"] = None
    if out["stop_touched"] is True and out["open_at_or_below_stop"] is True:
        out["stop_trigger_price_path"] = "open_at_or_below_stop_" + out["open_relative_lower"]
    elif out["stop_touched"] is True and out["open_at_or_below_stop"] is False:
        out["stop_trigger_price_path"] = "intraday_touch_with_open_above_stop"
    else:
        out["stop_trigger_price_path"] = "not_known_trigger_or_open_unknown"
    return out


def first_trigger(window):
    for i, row in enumerate(window):
        if row["stop_touched"] is True:
            if any(r["stop_touched"] is None for r in window[:i]):
                return "trigger_unknown_prior_path", None
            return "first_stop_trigger_known", row
    if any(r["stop_touched"] is None for r in window):
        return "trigger_unknown_incomplete_path", None
    return "no_stop_trigger_in_planned_window", None


def inspect_order(order, market):
    keep = ["group_id", "family", "segment", "policy", "db", "signal_date", "code", "source_label_status",
            "source_reason", "entry_date", "entry_price", "entry_factor", "source_exit_date", "source_exit_reason"]
    record = {k: order.get(k) for k in keep}
    record["source_unknown_preserved"] = order["source_label_status"] == "unresolved"
    if order["source_label_status"] == "cancelled":
        return {**record, "incidence_status": "known_cancelled_no_entry"}, []
    if not all(positive(order.get(k)) for k in ("entry_price", "entry_factor")) or order.get("entry_date") not in market.indices:
        return {**record, "incidence_status": "entry_unknown"}, []
    entry = market.indices[order["entry_date"]]
    panel = market.panels[order["code"]]
    direct = panel[entry]["factor"]
    assert np.isclose(direct, order["entry_factor"], atol=1e-12, rtol=0), "Frozen entry factor does not match direct snapshot factor"
    basis = order["entry_price"] * direct
    stop = basis * .94
    end = SPLITS[order["segment"]][1]
    record.update(entry_factor_direct=direct, entry_basis_economic=basis, stop_economic=stop,
                  planned_expiry_date=market.dates[entry + 3] if entry + 3 < len(market.dates) else None)
    window = []
    for offset in (1, 2, 3):
        idx = entry + offset
        if idx >= len(panel) or panel[idx]["trade_date"] > end:
            window.append(dict(trade_date=None, offset_after_entry=offset, stop_touched=None, touch_evidence="beyond_phase"))
        else:
            window.append(window_facts(panel[idx], stop, offset))
    status, trigger = first_trigger(window)
    record.update(incidence_status=status, unknown_stop_path_days=sum(r["stop_touched"] is None for r in window),
                  known_no_trade_days=sum(r["touch_evidence"] == "known_no_trading" for r in window))
    if trigger is not None:
        for key, value in trigger.items():
            record[f"trigger_{key}"] = value
        exit_day = order.get("source_exit_date")
        exit_known = isinstance(exit_day, str) and exit_day in market.indices
        record["source_exit_after_first_trigger"] = bool(exit_day > trigger["trade_date"]) if exit_known else None
        record["source_exit_delay_market_days"] = market.indices[exit_day] - market.indices[trigger["trade_date"]] if exit_known else None
    ledger = [{**{k: record[k] for k in ("group_id", "family", "segment", "policy", "db", "signal_date", "code", "entry_date")}, **row}
              for row in window]
    return record, ledger


def summarize(frame):
    known = frame[frame.incidence_status.eq("first_stop_trigger_known")]
    masked = known[known.trigger_mask_evidence.eq("close_at_lower_masked")]
    nonflat = masked[masked.trigger_nonflat_high_above_low.eq(True)]
    return dict(orders=len(frame), source_statuses=dict(Counter(frame.source_label_status)),
        incidence_statuses=dict(Counter(frame.incidence_status)), known_first_stop_triggers=len(known),
        first_trigger_model_strict_down=int(known.trigger_model_strict_down.eq(True).sum()),
        first_trigger_close_threshold_masked=len(masked), close_masked_nonflat=len(nonflat),
        close_masked_flat=int(masked.trigger_nonflat_high_above_low.eq(False).sum()),
        close_masked_ohlc_unknown=int(masked.trigger_nonflat_high_above_low.isna().sum()),
        first_trigger_unknown_mask_reference=int(known.trigger_mask_evidence.eq("unknown_reference").sum()),
        first_trigger_unknown_close=int(known.trigger_mask_evidence.eq("unknown_close").sum()),
        nonflat_masked_open_relative_lower=dict(Counter(nonflat.trigger_open_relative_lower)),
        nonflat_masked_open_at_or_below_stop=int(nonflat.trigger_open_at_or_below_stop.eq(True).sum()),
        nonflat_masked_open_above_stop=int(nonflat.trigger_open_at_or_below_stop.eq(False).sum()),
        nonflat_masked_stop_price_paths=dict(Counter(nonflat.trigger_stop_trigger_price_path)),
        nonflat_masked_open_at_or_below_stop_above_lower=int((nonflat.trigger_open_at_or_below_stop.eq(True)
            & nonflat.trigger_open_relative_lower.eq("above_lower")).sum()),
        nonflat_masked_intraday_touch_open_above_stop=int(nonflat.trigger_open_at_or_below_stop.eq(False).sum()),
        nonflat_masked_source_exit_later=int(nonflat.source_exit_after_first_trigger.eq(True).sum()),
        nonflat_masked_source_exit_unknown=int(nonflat.source_exit_after_first_trigger.isna().sum()))


def run(output):
    verify(output)
    if (output / "all-orders-incidence.csv").exists():
        raise FileExistsError("Preserve completed or interrupted incidence evidence")
    orders = pd.concat([load_orders(s) for s in SPECS], ignore_index=True)
    assert orders.group_id.nunique() == 11
    records, ledger = [], []
    for db, group in orders.groupby("db", sort=False):
        market = Market(db, set(group.code))
        try:
            for order in group.to_dict("records"):
                record, days = inspect_order(order, market)
                records.append(record)
                ledger.extend(days)
        finally:
            market.close()
    frame = pd.DataFrame(records).sort_values(["group_id", "signal_date", "code"])
    days = pd.DataFrame(ledger).sort_values(["group_id", "signal_date", "code", "offset_after_entry"])
    known = frame[frame.incidence_status.eq("first_stop_trigger_known")]
    nonflat = known[known.trigger_mask_evidence.eq("close_at_lower_masked") & known.trigger_nonflat_high_above_low.eq(True)]
    uncertain = frame[frame.source_unknown_preserved | frame.incidence_status.str.contains("unknown")]
    frame.to_csv(output / "all-orders-incidence.csv", index=False)
    days.to_csv(output / "stop-window-ledger.csv", index=False)
    known.to_csv(output / "all-first-stop-triggers.csv", index=False)
    nonflat.to_csv(output / "close-masked-nonflat-cases.csv", index=False)
    uncertain.to_csv(output / "unknown-orders-preserved.csv", index=False)
    summaries = {key: summarize(group) for key, group in frame.groupby("group_id", sort=True)}
    identity = ["db", "code", "entry_date", "entry_price", "entry_factor"]
    result = dict(created_at=now(), plan_sha256=sha(output / "PLAN.json"), groups=summaries,
        all_policy_order_rows=summarize(frame), unique_filled_basis_rows=int(frame.dropna(subset=["entry_price", "entry_factor"]).drop_duplicates(identity).shape[0]),
        unique_nonflat_masked_basis_rows=int(nonflat.drop_duplicates(identity).shape[0]),
        unique_nonflat_masked_code_dates=int(nonflat.drop_duplicates(["db", "code", "trigger_trade_date"]).shape[0]),
        occurrence_not_return_analysis=True, original_unknown_labels_preserved=True,
        price_facts_do_not_prove_order_execution=True,
        expiry_close_rule_not_redefined=True)
    verify(output)
    write_new(output / "summary.json", result)
    write_new(output / "completion-receipt.json", dict(completed_at=now(), plan_sha256=sha(output / "PLAN.json"),
        artifacts_sha256={p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name not in ("PLAN.md", "PLAN.json", "freeze-receipt.json")}))
    print(json.dumps(clean(result), ensure_ascii=False))


def self_check():
    template = dict(trade_date="2024-01-03", open=9.5, high=9.6, low=9., close=9., volume=100., factor=1.,
                    reference_known=True, lower_limit_raw=9., model_strict_down=True)
    blocked = window_facts(template, 9.4, 1)
    assert blocked["stop_touched"] is True and blocked["nonflat_high_above_low"] is True
    assert blocked["open_relative_lower"] == "above_lower" and blocked["open_at_or_below_stop"] is False
    gap = window_facts({**template, "open": 9.3}, 9.4, 1)
    assert gap["open_at_or_below_stop"] is True and gap["open_relative_lower"] == "above_lower"
    flat = window_facts({**template, "open": 9., "high": 9.}, 9.4, 1)
    assert flat["nonflat_high_above_low"] is False and flat["open_relative_lower"] == "at_lower"
    nohit = window_facts({**template, "low": 9.45, "close": 9.5, "model_strict_down": False}, 9.4, 1)
    missing = window_facts({**template, "volume": np.nan}, 9.4, 1)
    halted = window_facts({**template, "volume": 0.}, 9.4, 1)
    assert first_trigger([nohit, gap])[0] == "first_stop_trigger_known"
    assert first_trigger([missing, gap])[0] == "trigger_unknown_prior_path"
    assert first_trigger([halted, gap])[0] == "first_stop_trigger_known"
    assert first_trigger([nohit, nohit])[0] == "no_stop_trigger_in_planned_window"
    assert first_trigger([nohit, missing])[0] == "trigger_unknown_incomplete_path"
    unknown_ref = window_facts({**template, "reference_known": False, "lower_limit_raw": np.nan}, 9.4, 1)
    assert unknown_ref["mask_evidence"] == "unknown_reference" and unknown_ref["open_relative_lower"] == "unknown"
    return dict(passed=True, synthetic_only=True, cases=["nonflat_close_mask", "gap_above_lower", "flat_at_lower",
        "first_known_trigger", "unknown_before_trigger", "confirmed_no_trade_does_not_create_touch",
        "complete_no_trigger", "unknown_no_observed_trigger", "unknown_limit_reference_preserved"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("self-check", "freeze", "run"))
    args = parser.parse_args()
    if args.action == "self-check":
        print(json.dumps(self_check()))
    elif args.action == "freeze":
        freeze(OUTPUT)
    else:
        run(OUTPUT)


if __name__ == "__main__":
    main()
