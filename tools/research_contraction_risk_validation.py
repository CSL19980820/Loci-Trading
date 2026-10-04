"""Frozen later-period validation of the sole training-selected base8/fixed4 variant."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import research_contraction_risk_budget as training  # noqa: E402
from tools import research_contraction_structure as shape  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    common_maturity_mask,
    context_evidence,
    sha256,
)
from tools.research_chinext_payoff_filters import SPLITS  # noqa: E402
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

CANDIDATE = "base8_fixed4_unrestricted"
VARIANTS = [*training.CONTROLS, CANDIDATE]
SEGMENTS = ("validation_2025h2", "observed_2026")


def sources():
    return {**training.sources(), "tools/research_contraction_risk_validation.py": sha256(Path(__file__))}


def evaluate(db, output, segment):
    destination = output/segment
    if destination.exists(): raise FileExistsError("Do not overwrite a frozen validation phase")
    destination.mkdir()
    start, end = SPLITS[segment]
    store, ctx, computed, econ, signal_ok = shape.prepare(db, start, end)
    try:
        index = econ["close"].index
        mask = common_maturity_mask(index, start, end, max_hold=shape.COMMON_MATURITY)
        allowed = [str(d) for d in index[mask]]
        allowed_set = set(allowed)
        executor = training.Executor(ctx, end)
        events, setups = shape.shape_events(econ, signal_ok, "base8")
        pd.DataFrame([e for e in events if e["signal_date"] in allowed_set]).to_csv(destination/f"{segment}-base8-events.csv", index=False)
        pd.DataFrame([s for s in setups if s["arm_date"] >= start]).to_csv(destination/f"{segment}-base8-setups.csv", index=False)
        original = shape.events_for_original(computed, signal_ok, index, False)
        corrected = shape.events_for_original(computed, signal_ok, index, True)
        oldkeys = {(e["signal_date"], e["code"]) for e in original if e["signal_date"] in allowed_set}
        old_dates = {d for d, c in oldkeys}
        runs, allrows, alldaily = {}, {}, []
        for variant in VARIANTS:
            selected_events = original if variant == "legacy_original4" else corrected if variant == "baseline_flat4" else events
            result, rows, daily = training.execute(selected_events, variant, allowed, executor, destination)
            # The frozen training helper emits two train-prefixed CSVs only.
            # Move just those newly created files within this phase directory.
            for suffix in ("orders", "trades"):
                source = destination/f"train-{variant}-{suffix}.csv"
                target = destination/f"{segment}-{variant}-{suffix}.csv"
                if source.parent.resolve() != destination.resolve() or target.exists(): raise AssertionError("Unexpected validation output collision")
                source.rename(target)
            daily["segment"] = segment
            outcomes = {(r["signal_date"], r["code"]): r for r in rows}
            pd.DataFrame([dict(signal_date=d, code=c, new_selected=(d, c) in outcomes,
                new_weighted_net_pct=outcomes[(d, c)]["weighted_net_pct"] if (d, c) in outcomes else 0.) for d, c in sorted(oldkeys)]).to_csv(destination/f"{segment}-{variant}-legacy-opportunities.csv", index=False)
            additions = [r for key, r in outcomes.items() if key not in oldkeys]
            result.update(legacy_opportunities=len(oldkeys), legacy_overlap_trades=len(rows)-len(additions),
                new_opportunity_trades=len(additions), new_opportunity_weighted_net_sum=sum(r["weighted_net_pct"] for r in additions),
                trades_on_previously_inactive_dates=sum(r["signal_date"] not in old_dates for r in rows))
            if variant in training.CONTROLS:
                prior = pd.read_csv(training.PRIOR/f"{segment}-{variant}-trades.csv", dtype={"code": str}).set_index(["signal_date", "code"])
                if len(prior) != len(rows): raise AssertionError("Control count changed")
                for r in rows:
                    old = prior.loc[(r["signal_date"], r["code"])]
                    if (old.entry_date, old.exit_date, old.exit_reason) != (r["entry_date"], r["exit_date"], r["exit_reason"]) or not np.isclose(old.net_return_pct, r["net_return_pct"], atol=1e-9, rtol=0): raise AssertionError("Control changed")
            runs[variant], allrows[variant] = result, rows
            alldaily.append(daily)
            print(f"{segment}/{variant}: {json.dumps(result['metrics']['base'])}", flush=True)
        baseline = next(d for d in alldaily if d.variant.iloc[0] == "baseline_flat4").set_index("signal_date").net_sum
        for daily in alldaily:
            daily["base_net_sum"] = daily.signal_date.map(baseline)
            daily["delta_net_sum"] = daily.net_sum-daily.base_net_sum
            runs[str(daily.variant.iloc[0])]["paired_bootstrap"] = paired_bootstrap(daily)
        frame = pd.concat(alldaily, ignore_index=True)
        frame.to_csv(destination/f"{segment}-paired-daily-results.csv", index=False)
        result = dict(context=context_evidence(ctx), common_market_days=len(allowed), common_daily_slots=2*len(allowed),
            first_signal_day=allowed[0], last_signal_day=allowed[-1], runs=runs)
        write_json(destination/f"{segment}-summary.json", result)
        return result, allrows, frame
    finally:
        store.close()


def run(db, output):
    if (output/"validation-plan.json").exists(): raise FileExistsError("Preserve frozen validation plan")
    train = json.loads((output/"train-summary.json").read_text(encoding="utf-8"))
    original_plan = json.loads((output/"PLAN.json").read_text(encoding="utf-8"))
    if training.sources() != original_plan["sources"]: raise AssertionError("Frozen training source changed")
    if sha256(db) != original_plan["snapshot_sha256"]: raise AssertionError("Frozen snapshot changed")
    before = sources()
    nomination = dict(created_at=now(), nominees=[CANDIDATE], chosen_from_training_only=True,
        candidate_later_returns_not_previously_read=True, training_plan_sha256=train["plan_sha256"], train_summary_sha256=sha256(output/"train-summary.json"),
        rationale="Only base8/fixed4 is positive with PF>1 and combined double-cost/winner-removal positive. It improves training trade-quality mean/PF versus the control with 96 trades across14months. Its 678-slot contribution is LOWER than the control; selection is solely as a trade-quality representative, not budget superiority.",
        candidate_training_metrics=train["runs"][CANDIDATE]["metrics"], baseline_training_metrics=train["runs"]["baseline_flat4"]["metrics"],
        other_five_variants_excluded=True, no_2023h2_outcomes=True)
    write_json(output/"training-nomination.json", nomination)
    plan = dict(created_at=now(), sources=before, snapshot_sha256=original_plan["snapshot_sha256"],
        train_plan_sha256=train["plan_sha256"], train_summary_sha256=sha256(output/"train-summary.json"), nomination_sha256=sha256(output/"training-nomination.json"),
        variants=VARIANTS, segments={s: SPLITS[s] for s in SEGMENTS}, common_maturity_sessions=shape.COMMON_MATURITY,
        contracts="Exactly frozen base8 first-breakout events, Top2/code-dedup, retained opening-below-platform cancellation; no maximum platform-risk rejection; fixed-6%/4 sessions; w=1. Costs .21/.42; 20-session maturity. Same two unchanged controls.",
        acceptance="Candidate nonempty and mean>0/PF>1 in EACH later segment; pooled later double-cost, largest-weighted-winner removed, and combined double-cost+same-winner-removed net contribution all>0. Publish common-slot opportunity cost vs baseline and paired month-bootstrap CI regardless. If passed, separate fixed-total-capital validation remains mandatory.",
        no_rescue="No new candidates, cutoffs, score/entry/exit/allocation choices after later results; no2023H2 outcomes.",
        limitations=original_plan["limitations"]+["Training-only nomination is new, but years2024-2026 and related strategies have been repeatedly observed; later outputs remain retrospective, not pristine out-of-sample proof."])
    write_json(output/"validation-plan.json", plan)
    write_json(output/"validation-freeze-receipt.json", dict(created_at=now(), validation_plan_sha256=sha256(output/"validation-plan.json")))
    summary = dict(validation_plan_sha256=sha256(output/"validation-plan.json"), segments={})
    pooled, dailies = {v: [] for v in VARIANTS}, []
    for segment in SEGMENTS:
        if sources() != before: raise AssertionError("Validation source changed")
        result, rows, daily = evaluate(db, output, segment)
        summary["segments"][segment] = result
        for variant in VARIANTS: pooled[variant].extend(rows[variant])
        dailies.append(daily)
    combined = pd.concat(dailies, ignore_index=True)
    combined.to_csv(output/"validation-paired-daily-results.csv", index=False)
    summary["pooled_post_train"] = {}
    for variant in VARIANTS:
        daily = combined[combined.variant.eq(variant)]
        summary["pooled_post_train"][variant] = dict(metrics=training.bundle(pooled[variant], int(daily.opportunities.sum())), paired_bootstrap=paired_bootstrap(daily))
    m = summary["pooled_post_train"][CANDIDATE]["metrics"]
    passes = all(summary["segments"][seg]["runs"][CANDIDATE]["metrics"]["base"]["trades"] > 0
        and summary["segments"][seg]["runs"][CANDIDATE]["metrics"]["base"]["weighted_notional_mean"] > 0
        and (summary["segments"][seg]["runs"][CANDIDATE]["metrics"]["base"]["weighted_profit_factor"] or 0) > 1 for seg in SEGMENTS)
    passes = passes and all(m[k]["weighted_net_sum"] > 0 for k in ("double_cost", "winner_removed", "double_cost_winner_removed"))
    if sources() != before or sha256(db) != original_plan["snapshot_sha256"] or sha256(output/"train-summary.json") != plan["train_summary_sha256"]: raise AssertionError("Frozen source or input changed")
    summary.update(completed_at=now(), candidate=CANDIDATE, passes_statistical_stage=bool(passes), source_and_snapshot_unchanged=True,
        withheld_2023h2_not_evaluated=True, fixed_capital_portfolio_not_evaluated=True)
    write_json(output/"validation-summary.json", summary)
    print(json.dumps(dict(candidate=CANDIDATE, passes_statistical_stage=bool(passes))), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=training.OUTPUT)
    args = parser.parse_args()
    run(args.db.resolve(strict=True), args.output.resolve(strict=True))


if __name__ == "__main__":
    main()
