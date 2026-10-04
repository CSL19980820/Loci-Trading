"""Numeric correction wrapper for frozen repair rules; no new strategy search.

Reuse direct snapshot factors and signal precision from the frozen regime study.
Preserve original repair source/rules, its original later shortlist and evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import research_double_yin_regime as numeric  # noqa: E402
from tools import research_double_yin_repair as original  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore, sha256  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

PRIOR = original.OUTPUT
OUTPUT = ROOT/"docs/research/2026-10-04-double-yin-repair-precision"
SELECTED = ["one_dry_fixed", "one_dry_structural"]
FLAT_CASES = [("2024-09-25", "002868"), ("2025-04-03", "600851"), ("2025-06-11", "601956")]
CASES = []


def sources():
    return {**original.sources(), **numeric.sources(), "tools/research_double_yin_repair_precision.py": sha256(Path(__file__))}


def coordinate_inputs(ctx):
    # Independent read-only connection uses both phase and actual prefix cutoff.
    cutoff = min(ctx["end"], str(ctx["panels"]["close"].index[-1]))
    store = CutoffMarketStore(original.DB, cutoff)
    try:
        corrected = numeric.corrected_inputs(ctx, store)
    finally:
        store.close()
    # corrected_inputs updates ONLY ctx's factors and signal geometry. The
    # unchanged execution_arrays still uses unquantized raw * direct factor.
    p, economic = ctx["panels"], corrected["economic"]
    factors = ctx["execution_panels"]["__adjust_factor"]
    for day, code in FLAT_CASES:
        if day not in p["close"].index or code not in p["close"].columns:
            continue
        row = p["close"].index.get_loc(day)
        if row == 0:
            continue
        raw_open, raw_previous = float(p["open"].at[day, code]), float(p["close"].iloc[row-1][code])
        factor, previous_factor = float(factors.at[day, code]), float(factors.iloc[row-1][code])
        current, previous = float(economic["open"].at[day, code]), float(economic["close"].iloc[row-1][code])
        if raw_open != raw_previous or factor != previous_factor or current != previous:
            raise AssertionError(f"Known equal-price/equal-factor case changed: {day}/{code}")
        if bool(corrected["candidates"].at[day, code]) or bool(corrected["baseline"].at[day, code]):
            raise AssertionError(f"Flat opening misclassified as low-open: {day}/{code}")
        CASES.append(dict(day=day, code=code, cutoff=cutoff, raw_open=raw_open, raw_previous_close=raw_previous,
            direct_factor=factor, previous_direct_factor=previous_factor, economic_open=current,
            previous_economic_close=previous, corrected_low_open=False, corrected_selected=False))
    return corrected


def freeze():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT/"PLAN.json").exists():
        raise FileExistsError("Preserve numeric correction freeze")
    oldplan = json.loads((PRIOR/"PLAN.json").read_text(encoding="utf-8"))
    regimeplan = json.loads((numeric.OUTPUT/"PLAN.json").read_text(encoding="utf-8"))
    oldshort = json.loads((PRIOR/"training-shortlist.json").read_text(encoding="utf-8"))
    if original.sources() != oldplan["sources"] or numeric.sources() != regimeplan["sources"]:
        raise AssertionError("Frozen predecessor source mismatch")
    if oldshort["selected"] != SELECTED:
        raise AssertionError("Preserve exact old shortlist")
    files = [*sorted(PRIOR.glob("*.csv")), *sorted(PRIOR.glob("*.json"))]
    oldhashes = {str(p.relative_to(ROOT)): sha256(p) for p in files}
    snapshot, groups = sha256(original.DB), sha256(original.GROUPS)
    if snapshot != oldplan["snapshot_sha256"] or groups != oldplan["groups_sha256"]:
        raise AssertionError("Old snapshot/groups changed")
    test = pd.Series([12.48*1.378677629031, 12.48*1.3786776290309999])
    precise = numeric.price_precision(test)
    assert precise.iloc[0] == precise.iloc[1]
    plan = dict(created_at=original.now(), sources=sources(), snapshot_sha256=snapshot, groups_sha256=groups,
        original_frozen_artifacts=oldhashes, prior_plan_sha256=sha256(PRIOR/"PLAN.json"),
        regime_plan_sha256=sha256(numeric.OUTPUT/"PLAN.json"), old_shortlist_sha256=sha256(PRIOR/"training-shortlist.json"),
        purpose="Numerical correction only; reuse exact four frozen repair rules and old two controls. No search, no new nomination, no changed parameters or state transitions.",
        numeric_contract="Use frozen regime.corrected_inputs(ctx, readonly_store): direct stored hfq_factor <=actual panel/phase cutoff, forward alignment only, no quotient reconstruction. Normalize only signal OHLC to10 significant decimal digits. Synchronize ctx.execution_panels factors; unchanged execution_arrays uses exact unquantized raw*direct factor for entry basis, state comparisons, stops, exits and PnL. Same raw price with same stored factor is naturally equal; original stable-factor cancellation remains.",
        runs={"train": [*original.CONTROLS, *original.VARIANTS], "validation_2025h2": [*original.CONTROLS, *SELECTED], "observed_2026": [*original.CONTROLS, *SELECTED]},
        variants=original.VARIANTS, old_selected=SELECTED, old_selection_status=oldshort["status"],
        no_reselection="Training results may change; do not call shortlist or add nominees. Later runs retain old one_dry_fixed/one_dry_structural diagnostic-only status regardless of revised training statistics.",
        unchanged="Exact original repair origin/formation/first-break consumption/quota/industry/dedup/cooldown/entry/exit/maturity/budget rules and control raw shapes. Existing real industry receipt only; no new metadata or production requests.",
        audit="Compare every formal trade and selected order against old artifacts; distinguish numerical-only factor drift from entry/exit/price/return/terminal-state changes. Reconcile all origins so previously unfilled paths may legitimately create new orders. Verify all3 flat-open false candidates disappear, but only002868/2024-09-25 was previously an actual corrected-control fill; other2 were unselected.",
        flat_cases=FLAT_CASES, no_2023h2_outcomes=True, prior_repair_trade_records=250,
        limitations=["All outcomes are already-observed history; this is a same-rule numeric correction, not another validation sample.", "Current factor revisions and real industry receipt are not historical PIT; daily-open proxy is not09:25queue proof.", "Independent event slots remain distinct from fixed-total-capital NAV."])
    write_json(OUTPUT/"PLAN.json", plan)
    write_json(OUTPUT/"freeze-receipt.json", dict(created_at=original.now(), plan_sha256=sha256(OUTPUT/"PLAN.json")))
    print(json.dumps(dict(frozen=True, plan_sha256=sha256(OUTPUT/"PLAN.json"))), flush=True)


def verify_inputs(plan):
    if sources() != plan["sources"] or sha256(original.DB) != plan["snapshot_sha256"] or sha256(original.GROUPS) != plan["groups_sha256"]:
        raise AssertionError("Numeric correction inputs changed")
    if any(sha256(ROOT/p) != h for p, h in plan["original_frozen_artifacts"].items()):
        raise AssertionError("Original frozen evidence changed")


def changed_fields(left, right, fields):
    changes = []
    for key in fields:
        a, b = left.get(key), right.get(key)
        if pd.isna(a) and pd.isna(b):
            continue
        if isinstance(a, (float, int, np.number)) and isinstance(b, (float, int, np.number)):
            equal = np.isclose(a, b, atol=1e-9, rtol=0, equal_nan=True)
        else:
            equal = a == b
        if not equal:
            changes.append(key)
    return changes


def compare():
    summary, differences = {}, []
    old_repairs, new_repairs = 0, 0
    trade_fields = ["entry_date", "exit_date", "entry_price", "exit_price", "hold_days", "exit_reason", "gross_return_pct", "net_return_pct"]
    event_fields = ["status", "last_date", "base_date", "confirm_date", "entry_date", "exit_date", "exit_reason"]
    for segment in original.SPLITS:
        variants = [*original.CONTROLS, *(list(original.VARIANTS) if segment == "train" else SELECTED)]
        for variant in variants:
            result = {}
            for kind, fields in (("trades", trade_fields), ("events", event_fields)):
                old = pd.read_csv(PRIOR/f"{segment}-{variant}-{kind}.csv", dtype={"code": str})
                new = pd.read_csv(OUTPUT/f"{segment}-{variant}-{kind}.csv", dtype={"code": str})
                oldrows = {(r["signal_date"], r["code"]): r for r in old.to_dict("records")}
                newrows = {(r["signal_date"], r["code"]): r for r in new.to_dict("records")}
                if len(oldrows) != len(old) or len(newrows) != len(new):
                    raise AssertionError("Duplicate origin/code records")
                removed, added = sorted(oldrows.keys()-newrows.keys()), sorted(newrows.keys()-oldrows.keys())
                altered = []
                for key in sorted(oldrows.keys() & newrows.keys()):
                    changed = changed_fields(oldrows[key], newrows[key], fields)
                    if changed:
                        altered.append(key)
                        differences.append(dict(segment=segment, variant=variant, kind=kind, change="changed", signal_date=key[0], code=key[1],
                            fields=",".join(changed), old=json.dumps(oldrows[key], ensure_ascii=False), new=json.dumps(newrows[key], ensure_ascii=False)))
                for label, keys, records in (("removed", removed, oldrows), ("added", added, newrows)):
                    for key in keys:
                        differences.append(dict(segment=segment, variant=variant, kind=kind, change=label, signal_date=key[0], code=key[1],
                            fields="", old=json.dumps(records[key], ensure_ascii=False) if label=="removed" else "", new=json.dumps(records[key], ensure_ascii=False) if label=="added" else ""))
                result[kind] = dict(old=len(old), new=len(new), removed=len(removed), added=len(added), changed=len(altered))
                if kind == "trades" and variant not in original.CONTROLS:
                    old_repairs += len(old)
                    new_repairs += len(new)
                if kind == "events" and variant not in original.CONTROLS:
                    a = old[old.get("confirm_rank", pd.Series(np.nan, index=old.index)).notna() & old.get("entry_idx", pd.Series(np.nan, index=old.index)).notna()]
                    b = new[new.get("confirm_rank", pd.Series(np.nan, index=new.index)).notna() & new.get("entry_idx", pd.Series(np.nan, index=new.index)).notna()]
                    oldorders, neworders = set(zip(a.signal_date, a.code)), set(zip(b.signal_date, b.code))
                    result["selected_orders"] = dict(old=len(oldorders), new=len(neworders), removed=len(oldorders-neworders), added=len(neworders-oldorders))
            summary[f"{segment}/{variant}"] = result
    if old_repairs != 250:
        raise AssertionError("Old repair trade count differs from audited250 records")
    pd.DataFrame(differences).to_csv(OUTPUT/"old-new-differences.csv", index=False)
    write_json(OUTPUT/"diff-summary.json", dict(created_at=original.now(), old_repair_trades=old_repairs,
        new_repair_trades=new_repairs, numeric_material_tolerance=1e-9, runs=summary))


def run():
    plan = json.loads((OUTPUT/"PLAN.json").read_text(encoding="utf-8"))
    verify_inputs(plan)
    if (OUTPUT/"train-summary.json").exists():
        raise FileExistsError("Preserve numeric correction run")
    oldoutput, oldcoordinate = original.OUTPUT, original.coordinate_inputs
    original.OUTPUT, original.coordinate_inputs = OUTPUT, coordinate_inputs
    try:
        stages = {}
        for segment in original.SPLITS:
            verify_inputs(plan)
            stages[segment] = original.evaluate(segment, list(original.VARIANTS) if segment == "train" else SELECTED)
        oldshort = json.loads((PRIOR/"training-shortlist.json").read_text(encoding="utf-8"))
        short = {**oldshort, "selected": SELECTED, "selection_reused_not_recomputed": True,
                 "original_shortlist_sha256": plan["old_shortlist_sha256"], "train_sha256": sha256(OUTPUT/"train-summary.json"), "plan_sha256": sha256(OUTPUT/"PLAN.json")}
        write_json(OUTPUT/"training-shortlist.json", short)
        pooled = original.pooled_summary(short, stages)
        verify_inputs(plan)
        write_json(OUTPUT/"summary.json", dict(completed_at=original.now(), shortlist=short, segments=stages,
            pooled=pooled, plan_sha256=sha256(OUTPUT/"PLAN.json"), source_snapshot_groups_unchanged=True,
            original_frozen_evidence_unchanged=True, no_reselection=True, no_2023h2_outcomes=True))
        write_json(OUTPUT/"flat-open-case-checks.json", dict(all_passed=True, observations=CASES))
        compare()
    finally:
        original.OUTPUT, original.coordinate_inputs = oldoutput, oldcoordinate
    print(json.dumps(dict(completed=True, output=str(OUTPUT), old_shortlist_retained=SELECTED)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["freeze", "run"])
    args = parser.parse_args()
    (freeze if args.phase == "freeze" else run)()


if __name__ == "__main__":
    main()
