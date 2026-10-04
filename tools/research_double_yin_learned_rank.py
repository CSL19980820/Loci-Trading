"""Finite learned net-return ranking adapter for the complete double-yin pool.

The source universe, causal inputs and order labels are independent of the old
Top2 selections. Only research artifacts may be written by this script.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.domain.models import Trade  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore, common_maturity_mask, sha256  # noqa: E402
from tools.research_double_yin_redesign import config, execute, execution_arrays, mask_keys, metrics  # noqa: E402
from tools.research_double_yin_regime import (  # noqa: E402
    DB, GROUPS, corrected_inputs, full_shape_score, load_environment, regime_features,
)
from tools.research_double_yin_scoring_proxy import prepare_proxy_context, rank_with_groups  # noqa: E402
from tools.research_impulse_scoring import paired_bootstrap  # noqa: E402
from tools.research_regularized_rank_core import feature_complete, fit_ridge, predict_ridge  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-double-yin-learned-rank"
ROOT_PLAN = ROOT / "docs/research/2026-10-04-learned-rank/PLAN.md"
ROOT_RECEIPT = ROOT / "docs/research/2026-10-04-learned-rank/freeze-receipt.json"
ROOT_PLAN_SHA = "8097c29ce9160a342026c244ca6907e9bc0b7b2291b1bf54a933749afc74c15d"
CORE_SHA = "aedd4b984d55d00e5a2b014aafd647f8e419d9720033a0add25bb5784bcefbe6"
FEATURES = {
    "impulse_return_pct": "100*(C[T-2]/C[T-3]-1)",
    "recent_gain_10_pct": "100*(C[T-2]/C[T-12]-1)",
    "yin_volume_ratio": "raw V[T-1]/raw V[T-2]",
    "yin_body_pct": "100*(C[T-1]/O[T-1]-1)",
    "yin_close_location": "(C[T-1]-L[T-1])/(H[T-1]-L[T-1])",
    "impulse_body_retained": "(C[T-1]-O[T-2])/(C[T-2]-O[T-2])",
    "opening_gap_pct": "100*(O[T]/C[T-1]-1)",
    "opening_position_60": "clip((O[T]-min L[T-60:T-1])/(max H[T-60:T-1]-min L[T-60:T-1]),0,1)",
    "nearest_ma_distance_pct": "100*min(abs(O[T]/MA_p[T-1]-1)),p in5,10,20",
    "index_return_20_pct": "100*(CSI300 C[T-1]/CSI300 C[T-21]-1)",
    "breadth_above_ma20": "All main-board STOCK breadth C>MA20 atT-1, prior20 valid-price/positive-volume sessions",
    "breadth_advancing": "Same eligible main-board denominator, fraction C[T-1]>C[T-2]",
}
POLICIES = ["rank_only", "positive_only"]
CONTROLS = ["full_shape", "feature_eligible_full_shape", "corrected_low_open"]
SPLITS = {"fit_2024": ("2024-01-01", "2024-12-31"),
          "inner_2025h1": ("2025-01-01", "2025-06-30"),
          "refit_full_train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sources() -> dict:
    paths = ["tools/research_double_yin_learned_rank.py", "tools/research_regularized_rank_core.py",
             "tools/research_double_yin_regime.py", "tools/research_double_yin_repair.py",
             "tools/research_double_yin_redesign.py", "tools/research_double_yin_scoring_proxy.py",
             "tools/research_chinext_payoff_exits.py", "tools/research_impulse_scoring.py",
             "src/strategy/application/double_yin_low_open.py", "src/backtest/application/engine.py",
             "src/backtest/application/execution_contract.py", "src/backtest/domain/models.py",
             "src/market/infrastructure/store_panel.py", "src/market/domain/universe.py"]
    return {path: sha256(ROOT / path) for path in paths}


def frozen_plan() -> dict:
    root_receipt = json.loads(ROOT_RECEIPT.read_text(encoding="utf-8"))
    if (sha256(ROOT_PLAN) != ROOT_PLAN_SHA or sha256(ROOT / "tools/research_regularized_rank_core.py") != CORE_SHA
            or root_receipt["plan_sha256"] != ROOT_PLAN_SHA or root_receipt["core_sha256"] != CORE_SHA):
        raise AssertionError("Root mathematical/acceptance contract is not the approved frozen version")
    return {**design(), "status": "frozen_before_any_new_candidate_returns", "created_at": now(),
            "training": "Use frozen root core lambda1,fit_start2024-01-01,date-normalized weights,fit-only scaler,z±5,constant scale1,unpenalized intercept,no target clipping. No fitting on oldTop2 or low-open subset.",
            "freeze_guard": "This adapter,rootPLAN/core,snapshot,groups and nomination hashes must remain unchanged.",
            "acceptance": {
                "training": {"min_labels": 100, "min_decision_days": 60, "min_months": 6},
                "inner": {"min_closed": 20, "min_active_months": 3, "net_mean": ">0", "PF": ">1",
                          "stress": "double_cost_largest_winner_removed mean>0",
                          "budget": "slot_mean strictly greater than ALL3 controls", "unresolved_selected": 0},
                "later_each": {"min_closed": 12, "min_active_months": 4, "net_mean": ">0", "PF": ">1",
                               "budget": "slot_mean strictly greater than ALL3 controls", "unresolved_selected": 0},
                "later_combined": {"min_closed": 40, "stress": "double_cost,largest_winner_removed,and both combined each mean>0"},
                "stop": "If no inner qualifier, stop without full-train refit or later evaluation; no fallback or retuning.",
                "confidence": "Paired month blocks for all3 controls; crossing zero is not statistically confirmed advantage.",
                "capital": "Only later qualifiers may enter root's separate fixed-total-capital verification."},
            "root_plan_sha256": ROOT_PLAN_SHA, "root_receipt_sha256": sha256(ROOT_RECEIPT),
            "sources": sources(), "snapshot_sha256": sha256(DB), "groups_sha256": sha256(GROUPS)}


def verify_frozen() -> dict:
    plan = json.loads((OUTPUT / "PLAN.json").read_text(encoding="utf-8"))
    if (sources() != plan["sources"] or sha256(DB) != plan["snapshot_sha256"] or sha256(GROUPS) != plan["groups_sha256"]
            or sha256(ROOT_PLAN) != plan["root_plan_sha256"] or sha256(ROOT_RECEIPT) != plan["root_receipt_sha256"]):
        raise AssertionError("Frozen adapter/core/plan/data/industry evidence changed")
    return plan


def design() -> dict:
    return {
        "status": "draft_waiting_root_core_and_acceptance_freeze",
        "features": FEATURES, "policies": POLICIES, "controls": CONTROLS, "splits": SPLITS,
        "universe": "Entire corrected strong-up then double-volume-yin shape with valid raw current open>6; low-open is not a learning gate. Original sector intersection Top2 rule remains. All candidates, not old Top2 or low-open subset, receive independent order labels.",
        "decision": "T daily-opening proxy: today's O and bars fully closed byT-1; noT H/L/C/V, turnover, execution outcome, or future factor to build a feature. CSI300/breadth T-1. Opening-based scoring and same-open fill remain a proxy, not proof of09:25availability.",
        "numeric": "Frozen regime direct SQL hfq factors<=stage cutoff, forward only; signal price geometry10significant digits; raw prices*direct factors for fills/returns. Sparse factor source and current catalog/industry remain retrospective/PIT limitations.",
        "labels": {
            "target": "Net percentage return of each predeclared current-opening order opportunity, not conditional-on-fill return. Same4sessions including entry,-6% stop,strictT+1,original strict limits/delays/cost0.21%.",
            "closed": "Actual finalized net_return_pct, label_available_date=actual exit_date; actual exit must be<=stage cutoff, irrespective of planned maturity.",
            "cancelled": "Exactly0 only for finite nonpositive observed volume proving no fill, or known upper-limit opening under frozen execution contract. Conservatively available at that day's close; slot consumed/no refill.",
            "unresolved": "Unknown limit reference, missing/nonfinite volume or quote, unclosed filled position, or other unknown execution: net_return_pct=null,label_available_date=null. Never coerce unknown to0.",
            "boundary": "Before execution every segment uses common T+3<=end origin maturity. Additionally2024 fit requires actual available date<=2024-12-31 and before2025H1. Labels unresolved after suspensions/limit delays remain excluded.",
            "selection_unknown": "Any selected unresolved order makes that policy's calendar result/nomination unavailable. Unselected unresolved full-pool labels do not become model training zeros.",
        },
        "training": "Await frozen root core: singlelambda1 ridge, date-total weight1 then allweights sum1,fit-only weighted mean/std,zclip±5,constant scale1,no target clipping. Missing/nonfinite feature rows excluded from fitting and policy eligibility; explicit same-feature-qualified score control isolates that effect.",
        "ranking": "Signed finite predicted net return rounded to10decimal percentage points, no0..100clip and no score imputation. rank_only ranks all feature-complete candidates;positive_only first requires prediction>0. Greedy max2 with every industry-group intersection excluded,code tie order. No refilling after unknown/cancelled execution.",
        "control_contract": "full_shape=old60/40 over complete shape;feature_eligible_full_shape=same rank recomputed after exact model feature-completeness gate;corrected_low_open=old behavior corrected for price coordinates. Policies must beat all3 perroot acceptance.",
        "budget": "Same all market days with T+3<=segment end,2slots every day including empty/filtered days. Actual opening entry date equals decision date. Confirmed unfilled=0;unresolved selected=null. No zero-labelled training samples are invented for no-candidate calendar days. Independent event opportunities, not a portfolio NAV.",
        "freeze_guard": "No freeze or new returns/model fit before root core and full acceptance rules are supplied and reviewed. No fallback thresholds,features,lambda or policies after inner outcomes.",
        "limitations": ["Current identity/industry and factor revisions, not historical PIT.",
                        "Daily open/intraday daily extremes do not establish09:25execution or liquidity capacity.",
                        "Later history already observed in earlier studies; no untouched OOS claim.",
                        "No2023H2trade outcomes;2023is warmup only."],
    }


def causal_features(economic: dict, benchmark: pd.Series, wide: dict) -> dict:
    o, h, low, c, volume = (economic[key] for key in ("open", "high", "low", "close", "volume"))
    previous_range = h.shift(1)-low.shift(1)
    body = c.shift(2)-o.shift(2)
    floor, ceiling = low.shift(1).rolling(60).min(), h.shift(1).rolling(60).max()
    nearest = pd.DataFrame(np.inf, index=c.index, columns=c.columns)
    for period in (5, 10, 20):
        ma = c.shift(1).rolling(period).mean()
        distance = (o/ma.where(ma.gt(0))-1).abs()
        nearest = nearest.where(~(np.isfinite(distance) & distance.lt(nearest)), distance)
    market, _ = regime_features(economic, benchmark, wide)
    features = {
        "impulse_return_pct": (c.shift(2)/c.shift(3)-1)*100,
        "recent_gain_10_pct": (c.shift(2)/c.shift(12)-1)*100,
        "yin_volume_ratio": volume.shift(1)/volume.shift(2).where(volume.shift(2).gt(0)),
        "yin_body_pct": (c.shift(1)/o.shift(1)-1)*100,
        "yin_close_location": (c.shift(1)-low.shift(1))/previous_range.where(previous_range.gt(0)),
        "impulse_body_retained": (c.shift(1)-o.shift(2))/body.where(body.gt(0)),
        "opening_gap_pct": (o/c.shift(1)-1)*100,
        "opening_position_60": ((o-floor)/(ceiling-floor).where(ceiling.gt(floor))).clip(0, 1),
        "nearest_ma_distance_pct": nearest*100,
        "index_return_20_pct": ((benchmark/benchmark.shift(20)-1)*100).shift(1).reindex(c.index),
        "breadth_above_ma20": market["breadth_above_ma20"],
        "breadth_advancing": market["breadth_advancing"],
    }
    assert list(features) == list(FEATURES)
    return features


def candidate_rows(candidates: pd.DataFrame, score: pd.DataFrame, features: dict) -> pd.DataFrame:
    rows = []
    for day, code in sorted(mask_keys(candidates)):
        row = {"decision_date": day, "code": code, "baseline_score": float(score.at[day, code])}
        for name, value in features.items():
            row[name] = float(value.at[day, code] if isinstance(value, pd.DataFrame) else value.at[day])
        row["feature_complete"] = bool(np.isfinite([row[name] for name in FEATURES]).all())
        row["missing_features"] = ",".join(name for name in FEATURES if not np.isfinite(row[name]))
        rows.append(row)
    return pd.DataFrame(rows, columns=["decision_date", "code", "baseline_score", *FEATURES,
                                       "feature_complete", "missing_features"])


def row_mask(rows: pd.DataFrame, reference: pd.DataFrame, field: str) -> pd.DataFrame:
    mask = pd.DataFrame(False, index=reference.index, columns=reference.columns)
    for row in rows[rows[field]].itertuples():
        mask.at[row.decision_date, row.code] = True
    return mask


def signed_rank(candidates: pd.DataFrame, predictions: pd.DataFrame, sector_groups: dict, *, positive_only: bool) -> pd.DataFrame:
    if not predictions.index.equals(candidates.index) or not predictions.columns.equals(candidates.columns):
        raise ValueError("Prediction and candidate axes must match exactly")
    predictions = predictions.round(10)
    selected = pd.DataFrame(False, index=candidates.index, columns=candidates.columns)
    for day in candidates.index:
        valid = candidates.loc[day] & np.isfinite(predictions.loc[day])
        if positive_only:
            valid &= predictions.loc[day].gt(0)
        codes = list(candidates.columns[valid])
        codes.sort(key=lambda code: (-float(predictions.at[day, code]), str(code)))
        used: set[str] = set()
        picked = 0
        for code in codes:
            groups = sector_groups.get(str(code))
            if not isinstance(groups, (list, tuple)) or not groups or not all(isinstance(g, str) and g.strip() for g in groups):
                continue
            own = {group.strip() for group in groups}
            if used.intersection(own):
                continue
            selected.at[day, code] = True
            used.update(own)
            picked += 1
            if picked == 2:
                break
    return selected


def order_labels(events: list[dict], data: dict, cutoff: str) -> pd.DataFrame:
    dates = {str(day): row for row, day in enumerate(data["dates"])}
    codes = {str(code): col for col, code in enumerate(data["codes"])}
    labels = []
    for event in events:
        day, code, reason = event["signal_date"], event["code"], event["status"]
        row, col = dates[day], codes[code]
        volume = float(data["volume"][row, col])
        label, available, net = "unresolved", None, None
        if reason == "closed":
            actual_exit = event.get("exit_date")
            value = event.get("opportunity_net_pct")
            if actual_exit and day < actual_exit <= cutoff and value is not None and math.isfinite(value):
                label, available, net = "closed", actual_exit, float(value)
        elif reason == "upper_limit_opening" or (reason == "suspended_entry" and math.isfinite(volume) and volume <= 0):
            if day <= cutoff:
                label, available, net = "cancelled", day, 0.
        labels.append({"decision_date": day, "code": code, "label_status": label,
                       "label_available_date": available, "label_available_at": f"{available}T15:00:00+08:00" if available else None,
                       "net_return_pct": net, "execution_reason": reason,
                       "entry_date": event.get("entry_date"), "exit_date": event.get("exit_date")})
    return pd.DataFrame(labels, columns=["decision_date", "code", "label_status", "label_available_date",
                                         "label_available_at", "net_return_pct", "execution_reason", "entry_date", "exit_date"])


def order_budget(labels: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    byday = {day: part for day, part in labels.groupby("decision_date")}
    if set(byday)-set(days):
        raise AssertionError("Selected order outside common decision calendar")
    rows = []
    for day in days:
        part = byday.get(day)
        unknown = int(part.label_status.eq("unresolved").sum()) if part is not None else 0
        count = len(part) if part is not None else 0
        if count > 2:
            raise AssertionError("Daily selected order quota exceeded")
        rows.append({"signal_date": day, "opportunities": 2, "selected_orders": count,
                     "unresolved_orders": unknown, "net_sum": None if unknown else (float(part.net_return_pct.sum()) if part is not None else 0.)})
    return pd.DataFrame(rows)


def prepare_stage(start: str, end: str) -> dict:
    store = CutoffMarketStore(DB, end)
    try:
        ctx, _, _, _, _, _ = prepare_proxy_context(store, start, end, config(end), GROUPS)
        if ctx["engine"].requires_realtime_inputs is not True:
            raise AssertionError("Live realtime guard must remain enabled")
        corrected = corrected_inputs(ctx, store)
        p, economic = ctx["panels"], corrected["economic"]
        shape = corrected["origins"] & np.isfinite(p["open"]) & p["open"].gt(6)
        score = full_shape_score(economic, shape)
        pd.testing.assert_frame_equal(score.where(corrected["candidates"]), corrected["score"])
        benchmark, wide, environment = load_environment(store, shape.index, end)
        features = causal_features(economic, benchmark, wide)
        prefix_end = str(shape.index[len(shape)*2//3])
        prefix_economic = {key: value.loc[:prefix_end] if isinstance(value, pd.DataFrame) else value for key, value in economic.items()}
        prefix = causal_features(prefix_economic, benchmark.loc[:prefix_end],
                                 {key: value.loc[:prefix_end] for key, value in wide.items()})
        for name, value in features.items():
            if isinstance(value, pd.DataFrame):
                pd.testing.assert_frame_equal(value.loc[:prefix_end], prefix[name])
            else:
                pd.testing.assert_series_equal(value.loc[:prefix_end], prefix[name])
        mature = common_maturity_mask(shape.index, start, end, entry_timing="open", max_hold=4)
        candidates = shape.where(mature, False, axis=0)
        rows = candidate_rows(candidates, score, features)
        pd.testing.assert_series_equal(rows.feature_complete, feature_complete(rows, list(FEATURES)), check_names=False)
        feature_mask = row_mask(rows, candidates, "feature_complete")
        groups = p["__sector_groups__"]
        controls = {"full_shape": rank_with_groups(candidates, score, groups)[0],
                    "feature_eligible_full_shape": rank_with_groups(candidates & feature_mask, score, groups)[0],
                    "corrected_low_open": corrected["baseline"].where(mature, False, axis=0)}
        return {"ctx": ctx, "data": execution_arrays(ctx), "candidates": candidates,
                "candidate_rows": rows, "features": features, "score": score, "controls": controls,
                "feature_complete": feature_mask, "groups": groups,
                "days": list(map(str, shape.index[mature])), "environment": environment}
    finally:
        store.close()


def label_candidates(stage: dict, cutoff: str) -> tuple[pd.DataFrame, list, list, dict]:
    trades, events, accounting = execute(stage["ctx"], stage["candidates"], {"entry": "open", "exit": "fixed"}, {}, stage["data"])
    labels = order_labels(events, stage["data"], cutoff)
    result = stage["candidate_rows"].merge(labels, on=["decision_date", "code"], how="left", validate="one_to_one")
    if len(result) != len(events) or result.label_status.isna().any():
        raise AssertionError("Every complete shape candidate needs one explicit label status")
    result["training_label_eligible"] = result.feature_complete & result.label_status.isin(["closed", "cancelled"]) & result.label_available_date.le(cutoff)
    audit = {"execution": accounting, "label_status": dict(Counter(result.label_status)),
             "feature_missing": int((~result.feature_complete).sum()),
             "eligible_rows": int(result.training_label_eligible.sum()),
             "eligible_dates": int(result.loc[result.training_label_eligible, "decision_date"].nunique())}
    return result, trades, events, audit


def fit_model(labelled: pd.DataFrame, fit_end: str, validation_start: str) -> dict:
    """The root core enforces known-label time and fit-only preprocessing."""
    return fit_ridge(labelled, list(FEATURES), fit_start="2024-01-01", fit_end=fit_end, validation_start=validation_start)


def policy_masks(stage: dict, model: dict, policies: list[str]) -> tuple[dict, pd.DataFrame]:
    """Preselection sees only causal feature rows, never labels or fills."""
    rows = stage["candidate_rows"].copy()
    if any(key in rows for key in ("label_status", "label_available_date", "net_return_pct")):
        raise AssertionError("Policy preselection must not receive execution labels")
    if not rows.decision_date.gt(model["fit_end"]).all():
        raise AssertionError("Evaluation decision must follow frozen model fit cutoff")
    rows["predicted_net_pct"] = predict_ridge(model, rows).round(10)
    grid = pd.DataFrame(np.nan, index=stage["candidates"].index, columns=stage["candidates"].columns)
    for row in rows.itertuples():
        grid.at[row.decision_date, row.code] = row.predicted_net_pct
    selected = dict(stage["controls"])
    for name in policies:
        if name not in POLICIES:
            raise ValueError("Only frozen rank_only/positive_only policies are supported")
        selected[name] = signed_rank(stage["candidates"] & stage["feature_complete"], grid,
                                     stage["groups"], positive_only=name == "positive_only")
    return selected, rows


def selection_space(stage: dict, selected: dict, predictions: pd.DataFrame, policies: list[str]) -> tuple[dict, pd.DataFrame]:
    """Describe existing choices/industry substitutions; never another policy."""
    counts = predictions.decision_date.value_counts().reindex(stage["days"], fill_value=0)
    histogram = {"0": int(counts.eq(0).sum()), "1": int(counts.eq(1).sum()),
                 "2": int(counts.eq(2).sum()), "more_than2": int(counts.gt(2).sum())}
    rows = []
    byday = {day: part for day, part in predictions.groupby("decision_date")}
    for day in stage["days"]:
        control = set(selected["feature_eligible_full_shape"].columns[selected["feature_eligible_full_shape"].loc[day]])
        for name in policies:
            picked = set(selected[name].columns[selected[name].loc[day]])
            part = byday.get(day, predictions.iloc[:0])
            ranked = part[part.feature_complete & np.isfinite(part.predicted_net_pct)]
            if name == "positive_only":
                ranked = ranked[ranked.predicted_net_pct.gt(0)]
            first_two = set(ranked.sort_values(["predicted_net_pct", "code"], ascending=[False, True]).head(2).code)
            added, removed = picked-control, control-picked
            rows.append({"decision_date": day, "policy": name, "full_candidates": int(counts.at[day]),
                         "feature_eligible_control": ",".join(sorted(control)), "policy_selected": ",".join(sorted(picked)),
                         "changed": picked != control, "added_codes": ",".join(sorted(added)),
                         "removed_codes": ",".join(sorted(removed)), "added_count": len(added),
                         "removed_count": len(removed), "replacement_pairs": min(len(added), len(removed)),
                         "preindustry_top2": ",".join(sorted(first_two)),
                         "industry_or_missing_group_displaced_count": len(first_two-picked),
                         "industry_or_missing_group_added_count": len(picked-first_two)})
    detail = pd.DataFrame(rows)
    swaps = {}
    for name, part in detail.groupby("policy"):
        swaps[name] = {"changed_days": int(part.changed.sum()), "added_names": int(part.added_count.sum()),
                       "removed_names": int(part.removed_count.sum()), "replacement_pairs": int(part.replacement_pairs.sum()),
                       "industry_or_missing_group_displacements": int(part.industry_or_missing_group_displaced_count.sum())}
    return {"full_candidate_days": histogram, "actual_selection_changes_vs_feature_control": swaps}, detail


def save_fit(segment: str, validation_start: str, model_name: str) -> tuple[dict, dict]:
    start, end = SPLITS[segment]
    print(f"Prepare full-pool labels {segment} cutoff={end}", flush=True)
    stage = prepare_stage(start, end)
    labelled, trades, events, audit = label_candidates(stage, end)
    labelled.to_csv(OUTPUT / f"{segment}-candidate-labels.csv", index=False)
    pd.DataFrame(events).to_csv(OUTPUT / f"{segment}-all-candidate-events.csv", index=False)
    pd.DataFrame([trade.to_dict(include_factors=True) for trade in trades], columns=list(Trade.__dataclass_fields__)).to_csv(
        OUTPUT / f"{segment}-all-candidate-trades.csv", index=False)
    audit.update(segment=segment, decision_start=start, label_cutoff=end,
                 common_mature_decision_days=len(stage["days"]), environment=stage["environment"],
                 candidate_rows_sha256=sha256(OUTPUT / f"{segment}-candidate-labels.csv"),
                 prefix_features="passed", source_score_parity="passed")
    write_json(OUTPUT / f"{segment}-label-audit.json", audit)
    # No ranking/selection outcome enters this call. Every complete, resolved
    # candidate label is supplied and the core independently enforces time.
    model = fit_model(labelled, end, validation_start)
    write_json(OUTPUT / model_name, model)
    audit["model_sha256"] = sha256(OUTPUT / model_name)
    return model, audit


def evaluate_model(segment: str, model: dict, model_name: str, policies: list[str]) -> dict:
    start, end = SPLITS[segment]
    print(f"Prepare held-time evaluation {segment} cutoff={end}", flush=True)
    stage = prepare_stage(start, end)
    selected, predictions = policy_masks(stage, model, policies)
    for name, mask in selected.items():
        predictions[f"selected_{name}"] = [bool(mask.at[d, c]) for d, c in zip(predictions.decision_date, predictions.code)]
    # Save every preselection before evaluating ANY order in this segment.
    predictions.to_csv(OUTPUT / f"{segment}-predictions-and-selection.csv", index=False)
    selection_hash = sha256(OUTPUT / f"{segment}-predictions-and-selection.csv")
    choice_audit, choice_rows = selection_space(stage, selected, predictions, policies)
    choice_rows.to_csv(OUTPUT / f"{segment}-selection-space.csv", index=False)
    runs, budgets = {}, {}
    for name, mask in selected.items():
        print(f"Execute {segment}/{name}", flush=True)
        trades, events, accounting = execute(stage["ctx"], mask, {"entry": "open", "exit": "fixed"}, {}, stage["data"])
        labels = order_labels(events, stage["data"], end)
        pd.DataFrame([trade.to_dict(include_factors=True) for trade in trades], columns=list(Trade.__dataclass_fields__)).to_csv(
            OUTPUT / f"{segment}-{name}-trades.csv", index=False)
        pd.DataFrame(events).to_csv(OUTPUT / f"{segment}-{name}-events.csv", index=False)
        labels.to_csv(OUTPUT / f"{segment}-{name}-labels.csv", index=False)
        budgets[name] = order_budget(labels, stage["days"])
        unresolved = int(labels.label_status.eq("unresolved").sum())
        runs[name] = {"metrics": metrics(trades), "closed": len(trades),
                      "active_months": len({trade.entry_date[:7] for trade in trades}),
                      "selected_orders": len(events), "execution_accounting": accounting,
                      "label_accounting": dict(Counter(labels.label_status)), "unresolved_selected": unresolved,
                      "slots": len(stage["days"])*2,
                      "slot_mean": None if unresolved else float(budgets[name].net_sum.sum()/(len(stage["days"])*2))}
    comparisons = []
    for name, budget in budgets.items():
        for control in CONTROLS:
            pair = budget.copy()
            pair["delta_net_sum"] = pair.net_sum-budgets[control].net_sum
            pair["variant"], pair["control"], pair["segment"] = name, control, segment
            comparisons.append(pair)
            runs[name][f"month_blocks_vs_{control}"] = None if pair.delta_net_sum.isna().any() else paired_bootstrap(pair)
    pd.concat(comparisons, ignore_index=True).to_csv(OUTPUT / f"{segment}-paired-calendar.csv", index=False)
    summary = {"segment": segment, "completed_at": now(), "model_sha256": sha256(OUTPUT / model_name),
               "preselection_sha256": selection_hash, "runs": runs,
               "audit": {"full_candidates": len(predictions), "feature_complete": int(predictions.feature_complete.sum()),
                         "missing_features": int((~predictions.feature_complete).sum()),
                         "common_mature_days": len(stage["days"]), "environment": stage["environment"],
                         "predictions_use_no_label_fields": True, "prefix_causality": "passed", **choice_audit}}
    write_json(OUTPUT / f"{segment}-summary.json", summary)
    return summary


def phase_failures(result: dict, runs: dict, *, min_closed: int, min_months: int, stress_required: bool) -> list[str]:
    base = result["metrics"]["base"]
    failures = []
    if result["unresolved_selected"]:
        failures.append("selected_unresolved")
    if base["trades"] < min_closed:
        failures.append("insufficient_closed")
    if result["active_months"] < min_months:
        failures.append("insufficient_active_months")
    if (base["avg_net_return"] or 0) <= 0:
        failures.append("net_mean_not_positive")
    if (base["profit_factor"] or 0) <= 1:
        failures.append("PF_not_above_one")
    if stress_required and (result["metrics"]["double_cost_largest_winner_removed"]["avg_net_return"] or 0) <= 0:
        failures.append("combined_stress_not_positive")
    for control in CONTROLS:
        reference = runs[control]["slot_mean"]
        if result["slot_mean"] is None or reference is None or result["slot_mean"] <= reference:
            failures.append(f"calendar_not_better_than_{control}")
    return failures


def run_inner() -> dict:
    verify_frozen()
    if (OUTPUT / "inner-shortlist.json").exists():
        raise FileExistsError("Preserve frozen inner nomination")
    model, fit_audit = save_fit("fit_2024", "2025-01-01", "model-2024.json")
    inner = evaluate_model("inner_2025h1", model, "model-2024.json", POLICIES)
    failures = {name: phase_failures(inner["runs"][name], inner["runs"], min_closed=20,
                                   min_months=3, stress_required=True) for name in POLICIES}
    chosen = [name for name in POLICIES if not failures[name]]
    short = {"created_at": now(), "selected": chosen, "failures": failures,
             "status": "qualified_inner_policies" if chosen else "stop_no_inner_qualifier",
             "plan_sha256": sha256(OUTPUT / "PLAN.json"), "model_sha256": sha256(OUTPUT / "model-2024.json"),
             "inner_summary_sha256": sha256(OUTPUT / "inner_2025h1-summary.json"),
             "fit_labels_sha256": fit_audit["candidate_rows_sha256"]}
    write_json(OUTPUT / "inner-shortlist.json", short)
    verify_frozen()
    write_json(OUTPUT / "summary.json", {"completed_phase": "inner", "shortlist": short, "fit_audit": fit_audit,
               "inner": inner, "later_evaluated": False, "status": short["status"],
               "source_snapshot_groups_unchanged": True})
    print(json.dumps(short), flush=True)
    return short


def run_later() -> None:
    verify_frozen()
    short = json.loads((OUTPUT / "inner-shortlist.json").read_text(encoding="utf-8"))
    if (short["plan_sha256"] != sha256(OUTPUT / "PLAN.json") or short["model_sha256"] != sha256(OUTPUT / "model-2024.json")
            or short["inner_summary_sha256"] != sha256(OUTPUT / "inner_2025h1-summary.json")
            or short["fit_labels_sha256"] != sha256(OUTPUT / "fit_2024-candidate-labels.csv")):
        raise AssertionError("Inner evidence/nomination changed")
    if not short["selected"]:
        raise ValueError("No inner qualifier: later evaluation is forbidden")
    if (OUTPUT / "model-full-train.json").exists():
        raise FileExistsError("Preserve full-train refit and later results")
    model, fit_audit = save_fit("refit_full_train", "2025-07-01", "model-full-train.json")
    stages = {segment: evaluate_model(segment, model, "model-full-train.json", short["selected"])
              for segment in ("validation_2025h2", "observed_2026")}
    pooled = {}
    calendars = pd.concat([pd.read_csv(OUTPUT / f"{segment}-paired-calendar.csv") for segment in stages], ignore_index=True)
    for name in CONTROLS+short["selected"]:
        trades = []
        for segment in stages:
            frame = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str})
            trades.extend(Trade(**row) for row in frame.to_dict("records"))
        measures = metrics(trades)
        failures = {}
        if name in short["selected"]:
            failures = {segment: phase_failures(stage["runs"][name], stage["runs"], min_closed=12,
                        min_months=4, stress_required=False) for segment, stage in stages.items()}
            combined = []
            if len(trades) < 40:
                combined.append("combined_closed_below40")
            for stress in ("double_cost", "largest_winner_removed", "double_cost_largest_winner_removed"):
                if (measures[stress]["avg_net_return"] or 0) <= 0:
                    combined.append(f"{stress}_not_positive")
            failures["combined"] = combined
        comparisons = {}
        for control in CONTROLS:
            pair = calendars[calendars.variant.eq(name) & calendars.control.eq(control)]
            comparisons[control] = None if pair.delta_net_sum.isna().any() else paired_bootstrap(pair)
        pooled[name] = {"metrics": measures, "failures": failures, "month_blocks_vs_controls": comparisons,
                        "later_qualified": name in short["selected"] and not any(failures.values())}
    verify_frozen()
    existing = json.loads((OUTPUT / "summary.json").read_text(encoding="utf-8"))
    write_json(OUTPUT / "summary.json", {**existing, "completed_phase": "later", "completed_at": now(),
               "refit_audit": fit_audit, "later": stages, "pooled_later": pooled, "later_evaluated": True,
               "status": "finite_family_complete", "capital_candidates": [name for name in short["selected"] if pooled[name]["later_qualified"]]})
    print(json.dumps({"completed": True, "later_selected": short["selected"],
                      "capital_candidates": [name for name in short["selected"] if pooled[name]["later_qualified"]]}), flush=True)


def self_check() -> dict:
    dates = pd.Index(pd.bdate_range("2024-01-01", periods=100).strftime("%Y-%m-%d"))
    close = pd.DataFrame({"600001": np.arange(100, dtype=float)+100}, index=dates)
    p = {"open": close-.5, "high": close+.5, "low": close-1., "close": close,
         "volume": pd.DataFrame(100., index=dates, columns=close.columns)}
    benchmark = pd.Series(np.arange(100, dtype=float)+100, index=dates)
    wide = {"close": close.copy(), "volume": p["volume"].copy()}
    before = causal_features(p, benchmark, wide)
    changed = {key: value.copy() for key, value in p.items()}
    for key in ("high", "low", "close", "volume"):
        changed[key].iloc[-1] *= 5
    altered_index = benchmark.copy()
    altered_index.iloc[-1] *= .1
    altered_wide = {key: value.copy() for key, value in wide.items()}
    for value in altered_wide.values():
        value.iloc[-1] *= .1
    after = causal_features(changed, altered_index, altered_wide)
    for name, value in before.items():
        if isinstance(value, pd.DataFrame):
            pd.testing.assert_series_equal(value.iloc[-1], after[name].iloc[-1])
        else:
            assert value.iloc[-1] == after[name].iloc[-1]
    prefix = causal_features({key: value.iloc[:-1] for key, value in p.items()}, benchmark.iloc[:-1],
                             {key: value.iloc[:-1] for key, value in wide.items()})
    for name, value in before.items():
        if isinstance(value, pd.DataFrame):
            pd.testing.assert_frame_equal(value.iloc[:-1], prefix[name])
        else:
            pd.testing.assert_series_equal(value.iloc[:-1], prefix[name])
    candidates = pd.DataFrame(True, index=["2024-12-20"], columns=["600001", "600002", "600003", "600004"])
    prediction = pd.DataFrame([[-2., -1., -3., np.nan]], index=candidates.index, columns=candidates.columns)
    groups = {code: [f"industry:{code}"] for code in candidates.columns}
    ranked = signed_rank(candidates, prediction, groups, positive_only=False)
    assert list(ranked.columns[ranked.iloc[0]]) == ["600001", "600002"]
    assert not signed_rank(candidates, prediction, groups, positive_only=True).to_numpy().any()
    prediction.iloc[0] = [0., .1, 2., 1.]
    groups["600003"] = groups["600002"]
    selected = signed_rank(candidates, prediction, groups, positive_only=True)
    assert list(selected.columns[selected.iloc[0]]) == ["600003", "600004"]
    data = {"dates": ["2024-12-20"], "codes": ["600001", "600002", "600003", "600004"],
            "volume": np.array([[0., np.nan, 100., 100.]])}
    events = [{"signal_date": "2024-12-20", "code": code, "status": status} for code, status in
              zip(data["codes"], ["suspended_entry", "suspended_entry", "upper_limit_opening", "unknown_limit_reference"])]
    labels = order_labels(events, data, "2024-12-31")
    assert list(labels.label_status) == ["cancelled", "unresolved", "cancelled", "unresolved"]
    assert labels.loc[0, "net_return_pct"] == labels.loc[2, "net_return_pct"] == 0.
    assert pd.isna(labels.loc[1, "net_return_pct"]) and pd.isna(labels.loc[3, "label_available_date"])
    labels = order_labels([{"signal_date": "2024-12-20", "code": "600001", "status": "closed",
                            "exit_date": "2025-01-02", "opportunity_net_pct": 5.}], data, "2024-12-31")
    assert labels.label_status.iloc[0] == "unresolved" and pd.isna(labels.net_return_pct.iloc[0])
    budget = order_budget(labels, ["2024-12-20", "2024-12-23"])
    assert pd.isna(budget.net_sum.iloc[0]) and budget.net_sum.iloc[1] == 0. and budget.opportunities.sum() == 4
    return {"status": "passed", "checks": ["all12_features_ignore_today_HLCV", "feature_prefix_causality",
            "negative_predictions_not_clipped", "positive_policy_requires_strict_positive", "industry_intersection_rerank",
            "finite_zero_volume_known_cancel", "missing_volume_not_zero", "unknown_limit_not_zero",
            "actual_exit_after_fit_cutoff_excluded", "selected_unknown_null_budget", "empty_days_in_budget_not_labels"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["draft", "self-check", "freeze", "inner", "later", "run"])
    args = parser.parse_args()
    if args.phase == "self-check":
        print(json.dumps(self_check()), flush=True)
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.phase == "draft":
        write_json(OUTPUT / "DESIGN-DRAFT.json", design())
        write_json(OUTPUT / "adapter-self-check.json", self_check())
        print(json.dumps({"draft_only": True, "new_returns_computed": False, "model_fit": False}), flush=True)
    elif args.phase == "freeze":
        if (OUTPUT / "PLAN.json").exists():
            raise FileExistsError("Adapter plan already frozen")
        check = self_check()
        write_json(OUTPUT / "PLAN.json", frozen_plan())
        write_json(OUTPUT / "adapter-self-check.json", check)
        print(json.dumps({"frozen": True, "plan_sha256": sha256(OUTPUT / "PLAN.json")}), flush=True)
    elif args.phase == "inner":
        run_inner()
    elif args.phase == "later":
        run_later()
    else:
        short = run_inner()
        if short["selected"]:
            run_later()


if __name__ == "__main__":
    main()
