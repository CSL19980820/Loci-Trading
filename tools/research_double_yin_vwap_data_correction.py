"""Replay frozen VWAP policies with two officially confirmed suspension intervals.

The quote snapshot, candidate selection and original evidence remain immutable.
Only copied execution-volume arrays receive the confirmed zero-volume status.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import research_double_yin_vwap as base  # noqa: E402

ORIGINAL = base.OUTPUT
OUTPUT = ORIGINAL / "data-correction"
PREPARE = base.prepare
SUSPENSIONS = {
    "605389": ["2025-07-04", "2025-07-07", "2025-07-08", "2025-07-09", "2025-07-10"],
    "002036": ["2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29"],
}
ANNOUNCEMENTS = [
    ("605389", "suspension", "2025-07-04", "1224071231"),
    ("605389", "resumption", "2025-07-11", "1224131661"),
    ("002036", "suspension", "2026-07-23", "1225437970"),
    ("002036", "resumption", "2026-07-30", "1225447271"),
]


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def original_hashes() -> dict:
    return {path.name: base.sha256(path) for path in sorted(ORIGINAL.iterdir()) if path.is_file()}


def training_identity() -> dict:
    start, end = base.SPLITS["train"]
    assert all(day > end for days in SUSPENSIONS.values() for day in days)
    for policy in base.CONTROLS+base.POLICIES:
        labels = pd.read_csv(ORIGINAL / f"train-{policy}-labels.csv")
        assert labels.decision_date.between(start, end).all()
        assert labels.exit_date.dropna().le(end).all()
    return {"status": "identical_by_disjoint_execution_dates", "training_end": end,
            "first_corrected_date": min(day for days in SUSPENSIONS.values() for day in days),
            "original_training_evidence_reused": True, "no_renomination": True,
            "original_shortlist_sha256": base.sha256(ORIGINAL / "training-shortlist.json")}


def plan() -> dict:
    base.verify_frozen()
    sources = []
    for code, event, date, identifier in ANNOUNCEMENTS:
        path = OUTPUT / "announcements" / f"{code}-{event}-{date}.pdf"
        if not path.read_bytes().startswith(b"%PDF-"):
            raise AssertionError("Announcement must be a PDF")
        sources.append({"code": code, "event": event, "effective_date": date, "effective_session": "opening",
                        "url": f"https://static.cninfo.com.cn/finalpage/{date}/{identifier}.PDF",
                        "file": str(path.relative_to(OUTPUT)).replace("\\", "/"), "sha256": base.sha256(path)})
    conn = sqlite3.connect(f"file:{base.DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    observed = []
    try:
        for code, days in SUSPENSIONS.items():
            for day in days:
                rows = conn.execute("SELECT code,trade_date,volume,source FROM quotes_daily WHERE code=? AND trade_date=?",
                                    (code, day)).fetchall()
                observed.append({"code": code, "date": day, "snapshot_rows": [dict(row) for row in rows]})
                if any(row["volume"] is not None and np.isfinite(row["volume"]) and row["volume"] > 0 for row in rows):
                    raise AssertionError("Positive-volume snapshot row conflicts with official suspension")
    finally:
        conn.close()
    selected = read(ORIGINAL / "training-shortlist.json")["selected"]
    assert selected == ["yin_close_and_open_above_vwap"]
    return {"created_at": base.now(), "kind": "official_suspension_execution_evidence_correction",
            "policy_contract": "Original frozen A/B, thresholds, score, group Top2, costs, exits, splits and acceptance unchanged. Reuse original training identity and original B-only shortlist. Replay only B plus all three controls in the two later periods; no A later.",
            "overlay_contract": "Only the ten named confirmed suspension market dates, restricted to each execution period. Copy data['volume'] before assigning0; no original ndarray/pandas/database writes. All other execution arrays and raw QC stay identical. Stop date inclusive, resumption date excluded. Retain original preselection and do not refill cancelled slots.",
            "interpretation": "Official announcements resolve execution status retrospectively; this is not a new opening predictor. Missing raw quotes remain missing in original data/QC. 002036 opening order is already selected then confirmed cancelled0;605389 remains held through known suspension under the unchanged delayed-exit contract.",
            "sources": sources, "suspension_dates": SUSPENSIONS, "snapshot_rows": observed,
            "training_identity": training_identity(), "selected": selected, "controls": base.CONTROLS,
            "original_plan_sha256": base.sha256(ORIGINAL / "PLAN.json"),
            "original_files_sha256": original_hashes(), "wrapper_sha256": base.sha256(Path(__file__)),
            "source_snapshot_sha256": base.sha256(base.DB), "groups_sha256": base.sha256(base.GROUPS),
            "limits": "No inferred zero for other missing quotes. No new policy nomination or capital acceptance; report complete restored evidence and unchanged failures. All periods previously observed."}


def verify() -> dict:
    frozen = read(OUTPUT / "PLAN.json")
    base.verify_frozen()
    assert original_hashes() == frozen["original_files_sha256"]
    assert base.sha256(Path(__file__)) == frozen["wrapper_sha256"]
    assert base.sha256(base.DB) == frozen["source_snapshot_sha256"]
    assert base.sha256(base.GROUPS) == frozen["groups_sha256"]
    for source in frozen["sources"]:
        assert base.sha256(OUTPUT / source["file"]) == source["sha256"]
    return frozen


def overlay_volume(data: dict, start: str, end: str) -> tuple[dict, list[dict]]:
    corrected = dict(data)
    corrected["volume"] = data["volume"].copy()
    dates = {str(day): row for row, day in enumerate(data["dates"])}
    codes = {str(code): col for col, code in enumerate(data["codes"])}
    ledger = []
    for code, days in SUSPENSIONS.items():
        for day in days:
            if not start <= day <= end:
                continue
            if day not in dates or code not in codes:
                raise AssertionError("Confirmed suspension cell absent from execution panel")
            row, col = dates[day], codes[code]
            value = data["volume"][row, col]
            if np.isfinite(value) and value > 0:
                raise AssertionError("Positive execution volume conflicts with official suspension")
            corrected["volume"][row, col] = 0.
            ledger.append({"date": day, "code": code, "original_volume": float(value) if np.isfinite(value) else None,
                           "corrected_execution_volume": 0., "reason": "officially_confirmed_suspension"})
    changed = ~(np.equal(data["volume"], corrected["volume"]) | (np.isnan(data["volume"]) & np.isnan(corrected["volume"])))
    allowed = np.zeros_like(changed)
    for row in ledger:
        allowed[dates[row["date"]], codes[row["code"]]] = True
    assert not (changed & ~allowed).any()
    assert all(corrected[key] is value for key, value in data.items() if key != "volume")
    assert not np.shares_memory(corrected["volume"], data["volume"])
    return corrected, ledger


def prepare(start: str, end: str) -> dict:
    stage = PREPARE(start, end)
    raw_volume = stage["ctx"]["panels"]["volume"].copy()
    original_volume = stage["data"]["volume"].copy()
    stage["data"], ledger = overlay_volume(stage["data"], start, end)
    pd.testing.assert_frame_equal(stage["ctx"]["panels"]["volume"], raw_volume)
    np.testing.assert_array_equal(stage["ctx"]["execution_panels"]["volume"].to_numpy(), original_volume)
    base.write_json(OUTPUT / f"execution-overlay-{start}-{end}.json", ledger)
    return stage


def delta(segment: str, result: dict) -> dict:
    # The original opening candidate CSV and raw postdecision QC must remain
    # byte-identical even though the copied execution-volume evidence changed.
    for suffix in ("full-candidates-and-selection.csv", "postdecision-qc-not-eligibility.csv"):
        assert base.sha256(OUTPUT / f"{segment}-{suffix}") == base.sha256(ORIGINAL / f"{segment}-{suffix}")
    differences = []
    for name in result["runs"]:
        old = pd.read_csv(ORIGINAL / f"{segment}-{name}-labels.csv", dtype={"code": str}).set_index(["decision_date", "code"])
        new = pd.read_csv(OUTPUT / f"{segment}-{name}-labels.csv", dtype={"code": str}).set_index(["decision_date", "code"])
        pd.testing.assert_index_equal(old.index, new.index)
        for key in old.index:
            before = {k: None if pd.isna(v) else v for k, v in old.loc[key].to_dict().items()}
            after = {k: None if pd.isna(v) else v for k, v in new.loc[key].to_dict().items()}
            if before != after:
                assert (segment, key) in {
                    ("validation_2025h2", ("2025-07-02", "605389")),
                    ("observed_2026", ("2026-07-23", "002036")),
                }
                differences.append({"policy": name, "decision_date": key[0], "code": key[1], "before": before, "after": after})
        old_trades = pd.read_csv(ORIGINAL / f"{segment}-{name}-trades.csv", dtype={"code": str}).set_index(["signal_date", "code"])
        new_trades = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str}).set_index(["signal_date", "code"])
        assert set(old_trades.index) <= set(new_trades.index)
        pd.testing.assert_frame_equal(old_trades, new_trades.loc[old_trades.index])
    value = {"segment": segment, "candidate_and_raw_qc_identity": "byte_identical", "existing_closed_trades": "unchanged",
             "changed_labels": differences, "changed_label_count": len(differences)}
    base.write_json(OUTPUT / f"{segment}-delta.json", value)
    return value


def run() -> None:
    frozen = verify()
    if (OUTPUT / "summary.json").exists():
        raise FileExistsError("Correction already completed")
    stages, deltas = {}, {}
    for segment in ("validation_2025h2", "observed_2026"):
        if (OUTPUT / f"{segment}-summary.json").exists():
            raise FileExistsError("Correction stage already exists")
        try:
            base.OUTPUT, base.prepare = OUTPUT, prepare
            stages[segment] = base.evaluate(segment, frozen["selected"])
        finally:
            base.OUTPUT, base.prepare = ORIGINAL, PREPARE
        deltas[segment] = delta(segment, stages[segment])
        verify()
    calendars = pd.concat([pd.read_csv(OUTPUT / f"{segment}-paired-calendar.csv") for segment in stages], ignore_index=True)
    pooled = {}
    for name in base.CONTROLS+frozen["selected"]:
        trades = []
        for segment in stages:
            frame = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str})
            trades.extend(base.Trade(**row) for row in frame.to_dict("records"))
        measures = base.metrics(trades)
        failures = {}
        if name in frozen["selected"]:
            failures = {segment: base.failures(stage["runs"][name], stage["runs"], 12, 4, False) for segment, stage in stages.items()}
            failures["combined"] = []
            if len(trades) < 40:
                failures["combined"].append("closed_below40")
            if (measures["double_cost_largest_winner_removed"]["avg_net_return"] or 0) <= 0:
                failures["combined"].append("combined_stress_nonpositive")
        pair_stats = {}
        for control in base.CONTROLS:
            part = calendars[calendars.variant.eq(name) & calendars.control.eq(control)]
            pair_stats[control] = None if part.delta_net_sum.isna().any() else base.paired_bootstrap(part)
        pooled[name] = {"metrics": measures, "failures": failures, "month_blocks_vs_controls": pair_stats,
                        "later_qualified": name in frozen["selected"] and not any(failures.values())}
    capital = [name for name in frozen["selected"] if pooled[name]["later_qualified"]]
    verify()
    base.write_json(OUTPUT / "summary.json", {"status": "official_evidence_correction_complete", "completed_at": base.now(),
                    "plan_sha256": base.sha256(OUTPUT / "PLAN.json"), "training_identity": training_identity(),
                    "original_shortlist_reused": frozen["selected"], "later": stages, "pooled_later": pooled,
                    "delta": deltas, "capital_candidates": capital, "original_evidence_unchanged": True})
    print(json.dumps({"completed": True, "capital_candidates": capital,
                      "label_changes": {name: value["changed_label_count"] for name, value in deltas.items()}}), flush=True)


def self_check() -> dict:
    dates = ["2026-07-22", *SUSPENSIONS["002036"], "2026-07-30"]
    volume = np.array([[1., 5.], *[[np.nan, 5.] for _ in SUSPENSIONS["002036"]], [2., 5.]])
    original = {"dates": dates, "codes": ["002036", "600000"], "volume": volume, "open": np.ones_like(volume)}
    revised, ledger = overlay_volume(original, "2026-01-01", "2026-09-30")
    assert len(ledger) == 5 and np.isnan(volume[1:6, 0]).all()
    assert (revised["volume"][1:6, 0] == 0).all()
    np.testing.assert_array_equal(revised["volume"][[0, 6]], volume[[0, 6]])
    np.testing.assert_array_equal(revised["volume"][:, 1], volume[:, 1])
    unchanged, ledger = overlay_volume(original, "2024-01-01", "2025-06-30")
    np.testing.assert_array_equal(unchanged["volume"], volume)
    assert not ledger
    return {"status": "passed", "checks": ["copied_volume_no_raw_view_mutation", "only_confirmed_code_dates", "resumption_day_excluded",
                                            "other_arrays_same_identity", "training_date_disjoint_identity"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["self-check", "freeze", "run"])
    phase = parser.parse_args().phase
    if phase == "self-check":
        print(json.dumps(self_check()), flush=True)
    elif phase == "freeze":
        if (OUTPUT / "PLAN.json").exists():
            raise FileExistsError("Correction plan already frozen")
        base.write_json(OUTPUT / "self-check.json", self_check())
        base.write_json(OUTPUT / "PLAN.json", plan())
        print(json.dumps({"frozen": True, "plan_sha256": base.sha256(OUTPUT / "PLAN.json"), "correction_returns_observed": False}), flush=True)
    else:
        run()


if __name__ == "__main__":
    main()
