"""Training-only, frozen-shape opening-risk allocation diagnostic; offline only.

Compare six finite variants without the previous eight-percent platform-distance
admission gate. Structural exits scale capital; fixed six-percent exits do not.
No later-period candidate returns or withheld 2023H2 outcomes are evaluated.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _resolve_exit  # noqa: E402
from src.backtest.domain.models import Trade  # noqa: E402
from tools import research_contraction_structure as frozen  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE,
    common_maturity_mask,
    context_evidence,
    sha256,
)
from tools.research_chinext_payoff_filters import (  # noqa: E402
    SPLITS,
    independent_metrics,
)
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-contraction-risk-budget"
PRIOR = ROOT / "docs/research/2026-10-04-contraction-structure"
CONTROLS = frozen.CONTROLS
VARIANTS = {**{v: frozen.VARIANTS[v] for v in CONTROLS},
    **{f"{family}_{mode}_{'risk_budget' if mode == 'structure10' else 'unrestricted'}":
       dict(family=family, exit=mode, deduplicate=True)
       for family in frozen.SHAPES for mode in ("fixed4", "structure10")}}


def sources():
    return {**frozen.sources(), "tools/research_contraction_risk_budget.py": sha256(Path(__file__))}


def allocation(risk_pct: float | None, mode: str, is_structure: bool) -> float:
    """Relative to one original 10%-capital slot; risk_pct uses e.g. 8.0, not .08."""
    if not is_structure or mode == "fixed4":
        return 1.0
    if risk_pct is None or not np.isfinite(risk_pct) or risk_pct <= 0:
        raise ValueError("A structural allocation needs a finite positive opening risk")
    return min(1.0, 6.0 / risk_pct)


class Executor(frozen.Executor):
    def one(self, event: dict, mode: str, is_structure: bool):
        row, col = event["row"], event["col"]
        entry = row + 1
        if entry >= len(self.dates): return None, "entry_beyond_data", None
        raw_open = float(self.values["open"][entry, col])
        if not self.values["volume"][entry, col] > 0: return None, "entry_without_positive_volume", None
        if not self.known[entry, col]: return None, "unknown_limit_reference", None
        if self.blocked[entry, col]: return None, "limit_up_open", None
        if not np.isfinite(raw_open) or raw_open <= 0: return None, "invalid_open", None
        basis = raw_open * self.factor[entry, col]
        stop = event.get("stop_economic")
        risk = (1 - stop / basis) * 100 if is_structure else None
        if is_structure and (not np.isfinite(risk) or risk <= 0): return None, "open_below_structure_stop", risk
        # Admission keeps the frozen structure cancellation but removes only its
        # mismatched upper-distance gate. Capital is calculated separately.
        cfg = replace(BASELINE.config(self.end), hold_days=9 if mode == "structure10" else 3,
                      stop_loss_pct=-risk if mode == "structure10" else -6.)
        exit_row, price, reason = _resolve_exit(col=col, entry_idx=entry, entry_price=basis,
            planned_exit=entry + cfg.hold_days, cfg=cfg, high_a=self.ec["high"], low_a=self.ec["low"],
            close_a=self.ec["close"], open_a=self.ec["open"], one_word_down=self.down,
            volume_a=self.values["volume"], last_index=len(self.dates) - 1)
        if exit_row is None or reason == "data_end" or not np.isfinite(price) or price <= 0:
            return None, "unresolved_exit_not_zero", risk
        if self.dates[exit_row] > self.end: raise AssertionError("Execution exceeded training cutoff")
        factor = float(self.factor[exit_row, col])
        raw_exit = float(price / factor)
        for field in ("close", "open"):
            if price == self.ec[field][exit_row, col]:
                raw_exit = float(self.values[field][exit_row, col])
                break
        window = slice(entry, exit_row + 1)
        good = self.values["volume"][window, col] > 0
        highs, lows = self.ec["high"][window, col][good], self.ec["low"][window, col][good]
        gross = (price / basis - 1) * 100
        trade = Trade(code=self.codes[col], signal_date=str(self.dates[row]), entry_date=str(self.dates[entry]),
            entry_price=raw_open, exit_date=str(self.dates[exit_row]), exit_price=raw_exit, hold_days=exit_row-entry,
            gross_return_pct=float(gross), net_return_pct=float(gross-.21),
            mae_pct=float((np.nanmin(lows)/basis-1)*100), mfe_pct=float((np.nanmax(highs)/basis-1)*100),
            exit_reason=reason, entry_factor=float(self.factor[entry, col]), exit_factor=factor)
        return trade, "filled", risk


def metrics(rows: list[dict], budget: int, cost: float):
    values = np.asarray([r["capital_weight"] * (r["gross_return_pct"] - cost) for r in rows], dtype=float)
    weights = np.asarray([r["capital_weight"] for r in rows], dtype=float)
    positive, negative = values[values > 0], values[values <= 0]
    pf = float(positive.sum() / -negative.sum()) if len(negative) and negative.sum() < 0 else None
    return dict(trades=len(rows), weight_sum=float(weights.sum()), weighted_net_sum=float(values.sum()),
        weighted_common_slot_mean=float(values.sum()/budget) if budget else None,
        weighted_notional_mean=float(values.sum()/weights.sum()) if weights.sum() else None,
        weighted_profit_factor=pf, weighted_win_rate_pct=float(weights[values > 0].sum()/weights.sum()*100) if weights.sum() else None,
        weighted_avg_contribution=float(values.mean()) if len(values) else None,
        unused_slot_weight=float(budget-weights.sum()), original_slots=budget)


def bundle(rows: list[dict], budget: int):
    winner = max(rows, key=lambda r: r["weighted_net_pct"]) if rows else None
    without = [r for r in rows if r is not winner]
    result = {name: metrics(items, budget, cost) for name, items, cost in (
        ("base", rows, .21), ("double_cost", rows, .42), ("winner_removed", without, .21),
        ("double_cost_winner_removed", without, .42))}
    result["largest_weighted_winner"] = winner
    result["raw_per_trade_secondary"] = independent_metrics([Trade(**{k: r[k] for k in Trade.__dataclass_fields__ if k in r}) for r in rows])
    return result


def old_gate_group(risk):
    return "original_control" if risk is None else "previously_rejected_above8" if risk > 8 else "previously_admitted_le8"


def trade_row(trade, risk, spec):
    weight = allocation(risk, spec["exit"], spec["family"] != "original")
    return {**trade.to_dict(include_factors=True), "opening_structure_risk_pct": risk,
        "capital_weight": weight, "capital_fraction": .1 * weight,
        "weighted_net_pct": weight * trade.net_return_pct,
        "weighted_double_cost_net_pct": weight * (trade.gross_return_pct-.42),
        "old_gate_group": old_gate_group(risk)}


def execute(events, variant, allowed, executor, output):
    spec = VARIANTS[variant]
    byday = defaultdict(list)
    allowed_set = set(allowed)
    for event in events:
        if event["signal_date"] in allowed_set: byday[event["signal_date"]].append(event)
    held_until, selected, rows, skips = {}, [], [], Counter()
    date_index = {str(d): i for i, d in enumerate(executor.dates)}
    held_exclusions = 0
    for date in allowed:
        row = date_index[date]
        ranked = sorted(byday[date], key=lambda e: (-e["score"], e["code"]))
        free = []
        for event in ranked:
            if spec["deduplicate"] and held_until.get(event["code"], -1) > row: held_exclusions += 1
            else: free.append(event)
        for event in free[:2]:
            trade, status, risk = executor.one(event, spec["exit"], spec["family"] != "original")
            if status == "unresolved_exit_not_zero": raise AssertionError("Unknown execution cannot become zero")
            item = trade_row(trade, risk, spec) if trade else None
            if item:
                rows.append(item)
                held_until[event["code"]] = date_index[trade.exit_date]
            else: skips[status] += 1
            selected.append({**event, "entry_date": str(executor.dates[event["row"]+1]),
                "entry_open_raw": float(executor.values["open"][event["row"]+1, event["col"]]),
                "entry_factor": float(executor.factor[event["row"]+1, event["col"]]),
                "opening_structure_risk_pct": risk, "old_gate_group": old_gate_group(risk), "status": status,
                "capital_weight": item["capital_weight"] if item else 0., "weighted_net_pct": item["weighted_net_pct"] if item else 0.})
    if len(selected) != len(rows) + sum(skips.values()): raise AssertionError("Order accounting mismatch")
    if spec["deduplicate"]:
        for code in {t["code"] for t in rows}:
            ordered = sorted([t for t in rows if t["code"] == code], key=lambda t: t["entry_date"])
            if any(b["entry_date"] <= a["exit_date"] for a, b in zip(ordered, ordered[1:])):
                raise AssertionError("Same-code holdings overlap")
    pd.DataFrame(selected).to_csv(output/f"train-{variant}-orders.csv", index=False)
    pd.DataFrame(rows).to_csv(output/f"train-{variant}-trades.csv", index=False)
    totals = Counter()
    for trade in rows: totals[trade["signal_date"]] += trade["weighted_net_pct"]
    daily = pd.DataFrame([dict(segment="train", variant=variant, signal_date=d, opportunities=2, net_sum=totals[d]) for d in allowed])
    occupancy = [sum(t["entry_date"] <= str(d) <= t["exit_date"] for t in rows) for d in executor.dates]
    capital = [sum(t["capital_fraction"] for t in rows if t["entry_date"] <= str(d) <= t["exit_date"]) for d in executor.dates]
    return dict(metrics=bundle(rows, 2*len(allowed)), planned_orders=len(selected), closed=len(rows), skipped=dict(skips),
        held_candidate_exclusions=held_exclusions, closed_months=len({t["signal_date"][:7] for t in rows}),
        max_concurrent_positions=max(occupancy, default=0), max_nominal_capital_fraction_sum=max(capital, default=0),
        gate_groups={g: bundle([t for t in rows if t["old_gate_group"] == g], 2*len(allowed)) for g in sorted({t["old_gate_group"] for t in rows})}), rows, daily


def replay_old_orders(variant, executor, output, budget):
    """Hold old selections fixed to isolate gate removal from pathwise dedup."""
    spec = VARIANTS[variant]
    old_variant = f"{spec['family']}_{spec['exit']}"
    frame = pd.read_csv(PRIOR/f"train-{old_variant}-orders.csv", dtype={"code": str})
    results = []
    for event in frame.to_dict("records"):
        event["row"], event["col"] = int(event["row"]), int(event["col"])
        trade, status, risk = executor.one(event, spec["exit"], True)
        if status == "unresolved_exit_not_zero": raise AssertionError("Unknown matched-order exit")
        if trade:
            results.append({**trade_row(trade, risk, spec), "old_order_status": event["status"]})
    pd.DataFrame(results).to_csv(output/f"train-{variant}-old-orders-replayed.csv", index=False)
    return dict(old_planned=len(frame), old_status_counts=frame.status.value_counts().to_dict(), new_filled=len(results),
        note="Diagnostic only: old order list fixed, potentially overlapping; never used for nomination.",
        groups={status: bundle([r for r in results if r["old_order_status"] == status], budget) for status in sorted({r["old_order_status"] for r in results})})


def run(db: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    if (output/"PLAN.json").exists(): raise FileExistsError("Preserve frozen training study")
    previous = json.loads((PRIOR/"PLAN.json").read_text(encoding="utf-8"))
    if frozen.sources() != previous["sources"]: raise AssertionError("Frozen predecessor source changed")
    dbhash, before = sha256(db), sources()
    if dbhash != previous["snapshot_sha256"]: raise AssertionError("Snapshot is not frozen predecessor input")
    input_paths = [PRIOR/"PLAN.json", PRIOR/"train-summary.json", *sorted(PRIOR.glob("train-*-orders.csv"))]
    prior_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in input_paths}
    plan = dict(created_at=now(), scope="Train only 2024-01-01..2025-06-30; 2023 state warmup; no later candidate returns or 2023H2 outcomes",
        snapshot_sha256=dbhash, sources=before, previous_frozen_inputs=prior_hashes, variants=VARIANTS, shapes=frozen.SHAPES,
        unchanged="Exact frozen shape, state consumption, economic-reference limits, raw-volume comparability, score, Top2, original-code dedup and T+1 execution.",
        change="Remove only the eight-percent actual-opening-to-platform-stop distance rejection. Still cancel opening at/below platform stop, including fixed4. Fixed4 uses -6% stop/4 sessions; structure10 retains frozen platform stop/10 sessions.",
        allocation="risk_pct=(1-frozen_stop_economic/actual_open_economic)*100, e.g.8.0. fixed4/control w=1. structure10 w=min(1,6/risk_pct). Capital fraction=.1*w=min(.1,.6/risk_pct). Weight is determined by opening price and previously frozen stop only.",
        costs="Round-trip .21 percentage points of actual notional; stress .42. Weighted contribution=w*(gross-cost). Largest winner is max weighted base-net contribution; delete same winner for combined stress.",
        accounting="Same 20-session maturity, every common market day x2, unfilled slots and resizing unused capital stay zero. Primary weighted slot mean/PF and weighted notional mean; unweighted pertrade result secondary. Independent event accounting; not fixed-capital NAV and no cash recycling claim.",
        diagnostics="For all six candidates, report <=8 and >8 actual-opening groups. Replay previous frozen order list with no new risk cap to isolate gate effect; this matched list is diagnostic only because its holdings may overlap. New pathwise selected trades remain code-deduplicated.",
        selection="No nominations or later candidate runs in this phase. Freeze training evidence for parent review before separate finite nomination.",
        limitations=previous["limitations"]+["Removal of a diagnosed risk admission mismatch is another retrospective development round, not unseen validation.", "Capital risk budget is nominal; T+1, opening gaps, suspension and lower-limit queues can exceed planned loss."])
    write_json(output/"PLAN.json", plan)
    write_json(output/"freeze-receipt.json", dict(created_at=now(), plan_sha256=sha256(output/"PLAN.json")))
    start, end = SPLITS["train"]
    store, ctx, computed, econ, signal_ok = frozen.prepare(db, start, end)
    try:
        index = econ["close"].index
        mask = common_maturity_mask(index, start, end, max_hold=frozen.COMMON_MATURITY)
        allowed = [str(d) for d in index[mask]]
        allowed_set = set(allowed)
        executor = Executor(ctx, end)
        cache = {}
        for family in frozen.SHAPES:
            events, setups = frozen.shape_events(econ, signal_ok, family)
            cache[family] = events
            pd.DataFrame([e for e in events if e["signal_date"] in allowed_set]).to_csv(output/f"train-{family}-events.csv", index=False)
            pd.DataFrame([s for s in setups if s["arm_date"] >= start]).to_csv(output/f"train-{family}-setups.csv", index=False)
        oldevents = frozen.events_for_original(computed, signal_ok, index, False)
        flatevents = frozen.events_for_original(computed, signal_ok, index, True)
        oldkeys = {(e["signal_date"], e["code"]) for e in oldevents if e["signal_date"] in allowed_set}
        runs, dailies = {}, []
        for variant, spec in VARIANTS.items():
            events = oldevents if variant == "legacy_original4" else flatevents if spec["family"] == "original" else cache[spec["family"]]
            result, rows, daily = execute(events, variant, allowed, executor, output)
            outcomes = {(r["signal_date"], r["code"]): r for r in rows}
            pd.DataFrame([dict(signal_date=d, code=c, new_selected=(d, c) in outcomes,
                new_weighted_net_pct=outcomes[(d, c)]["weighted_net_pct"] if (d, c) in outcomes else 0.) for d, c in sorted(oldkeys)]).to_csv(output/f"train-{variant}-legacy-opportunities.csv", index=False)
            additions = [r for key, r in outcomes.items() if key not in oldkeys]
            result.update(legacy_opportunities=len(oldkeys), legacy_overlap_trades=len(rows)-len(additions),
                new_opportunity_trades=len(additions), new_opportunity_weighted_net_sum=sum(r["weighted_net_pct"] for r in additions))
            if variant not in CONTROLS:
                result["matched_old_order_diagnostic"] = replay_old_orders(variant, executor, output, 2*len(allowed))
            else:
                prior = pd.read_csv(PRIOR/f"train-{variant}-trades.csv", dtype={"code": str}).set_index(["signal_date", "code"])
                for r in rows:
                    old = prior.loc[(r["signal_date"], r["code"])]
                    if (old.entry_date, old.exit_date, old.exit_reason) != (r["entry_date"], r["exit_date"], r["exit_reason"]) or not np.isclose(old.net_return_pct, r["net_return_pct"], atol=1e-9, rtol=0): raise AssertionError("Unchanged control changed")
                if len(prior) != len(rows): raise AssertionError("Unchanged control count changed")
            runs[variant] = result
            dailies.append(daily)
            m = result["metrics"]["base"]
            print(f"{variant}: n={len(rows)} w={m['weight_sum']:.3f} weightedMean={m['weighted_notional_mean']} PF={m['weighted_profit_factor']} slot={m['weighted_common_slot_mean']}", flush=True)
        base = next(d for d in dailies if d.variant.iloc[0] == "baseline_flat4").set_index("signal_date").net_sum
        for daily in dailies:
            daily["base_net_sum"] = daily.signal_date.map(base)
            daily["delta_net_sum"] = daily.net_sum-daily.base_net_sum
            runs[str(daily.variant.iloc[0])]["paired_bootstrap"] = paired_bootstrap(daily)
        pd.concat(dailies, ignore_index=True).to_csv(output/"train-paired-daily-results.csv", index=False)
        if sources() != before or sha256(db) != dbhash: raise AssertionError("Frozen research input changed")
        if any(sha256(ROOT/p) != h for p, h in prior_hashes.items()): raise AssertionError("Predecessor evidence changed")
        result = dict(completed_at=now(), plan_sha256=sha256(output/"PLAN.json"), context=context_evidence(ctx),
            common_market_days=len(allowed), common_daily_slots=2*len(allowed), first_signal_day=allowed[0], last_signal_day=allowed[-1],
            source_and_snapshot_unchanged=True, no_later_candidate_returns=True, withheld_2023h2_not_evaluated=True, training_nominees_not_selected=True, runs=runs)
        write_json(output/"train-summary.json", result)
        pd.DataFrame([dict(variant=v, **r["metrics"]["base"], combined_stress_slot_mean=r["metrics"]["double_cost_winner_removed"]["weighted_common_slot_mean"],
            closed_months=r["closed_months"], max_concurrent=r["max_concurrent_positions"], max_nominal_fraction=r["max_nominal_capital_fraction_sum"]) for v, r in runs.items()]).to_csv(output/"metrics.csv", index=False)
    finally:
        store.close()


def self_check():
    assert allocation(12., "structure10", True) == .5
    assert allocation(8., "structure10", True) == .75
    assert allocation(3., "structure10", True) == 1.
    assert allocation(12., "fixed4", True) == 1.
    rows = [dict(capital_weight=.1, gross_return_pct=50.21, weighted_net_pct=5.),
            dict(capital_weight=1., gross_return_pct=10.21, weighted_net_pct=10.),
            dict(capital_weight=.5, gross_return_pct=-1.79, weighted_net_pct=-1.)]
    assert max(rows, key=lambda r: r["weighted_net_pct"]) is rows[1]
    base, stress = metrics(rows, 10, .21), metrics(rows, 10, .42)
    assert np.isclose(base["weighted_profit_factor"], 15.)
    assert np.isclose(base["weighted_common_slot_mean"], 1.4)
    assert np.isclose(base["weighted_net_sum"]-stress["weighted_net_sum"], .21*1.6)
    assert np.isclose(base["unused_slot_weight"], 8.4)
    dates = pd.bdate_range("2024-01-01", periods=20).strftime("%Y-%m-%d")
    raw = {k: pd.DataFrame(v, index=dates, columns=["300001"]) for k, v in {"open": 100., "high": 101., "low": 99., "close": 100., "volume": 100., "__adjust_factor": 1.}.items()}
    ex = Executor({"execution_panels": raw}, str(dates[-1]))
    event = dict(row=2, col=0, stop_economic=85.)
    assert ex.one(event, "fixed4", True)[1] == "filled"
    assert ex.one(event, "structure10", True)[1] == "filled"
    assert ex.one({**event, "stop_economic": 101.}, "fixed4", True)[1] == "open_below_structure_stop"
    print("Passed: allocation units, weighted PF/slots/costs/winner, >8% admitted, below-platform cancellation", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["self-check", "train"])
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.phase == "self-check": self_check(); return
    if args.db is None: parser.error("--db required")
    run(args.db.resolve(strict=True), args.output.resolve())


if __name__ == "__main__":
    main()
