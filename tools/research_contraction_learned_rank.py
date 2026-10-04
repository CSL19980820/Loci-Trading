"""Original contraction-pool adapter for one finite learned net-return ranking.

Shared frozen regularized-rank math and protocol govern the finite experiment.
Production selectors and all previous studies stay unchanged.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.execution_contract import strict_price_masks  # noqa: E402
from src.backtest.application.runner import prepare_backtest_context  # noqa: E402
from src.market import is_st_name  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from src.strategy.application.contraction_rebreakout import (
    DEPENDENCY_BARS,  # noqa: E402
)
from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE,
    CutoffMarketStore,
    common_maturity_mask,
    context_evidence,
    sha256,
)
from tools.research_contraction_structure import Executor  # noqa: E402
from tools.research_double_yin_regime import (  # noqa: E402
    normalized_economic,
    price_precision,
    snapshot_factors,
)
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.research_regularized_rank_core import (  # noqa: E402
    feature_complete,
    fit_ridge,
    predict_ridge,
)
from tools.strategy_chinext_review import write_json  # noqa: E402

SLUG = "contraction-rebreakout-v1"
DB = ROOT/".local/chinext-payoff-20261004/market.db"
OUTPUT = ROOT/"docs/research/2026-10-04-contraction-learned-rank"
FEATURES = (
    "momentum10_pct", "csi300_return20_pct", "recent_impulse_age",
    "pullback_depth_pct", "contraction_volume_ratio", "breakout_volume_ratio",
    "breakout_extension_pct", "chinext_above_ma20_breadth", "close_location",
    "body_fraction", "range_over_prior_atr14", "pullback_support_distance_pct",
)
CONTROLS = ("legacy_original", "corrected_original", "eligible_original")
POLICIES = ("rank_only", "positive_only")
ROOT_PLAN = ROOT/"docs/research/2026-10-04-learned-rank/PLAN.md"
ROOT_PLAN_SHA = "8097c29ce9160a342026c244ca6907e9bc0b7b2291b1bf54a933749afc74c15d"
CORE_SHA = "aedd4b984d55d00e5a2b014aafd647f8e419d9720033a0add25bb5784bcefbe6"
PHASES = {"inner_fit": ("2024-01-01", "2024-12-31"), "inner_validation": ("2025-01-01", "2025-06-30"),
    "full_refit": ("2024-01-01", "2025-06-30"), "validation_2025h2": ("2025-07-01", "2025-12-31"),
    "observed_2026": ("2026-01-01", "2026-09-30")}


def sources() -> dict[str, str]:
    paths = ["tools/research_contraction_learned_rank.py", "tools/research_contraction_structure.py",
        "tools/research_double_yin_regime.py", "tools/research_chinext_payoff_exits.py",
        "tools/research_regularized_rank_core.py", "tools/research_impulse_scoring.py",
        "src/strategy/application/contraction_rebreakout.py", "src/backtest/application/runner.py",
        "src/backtest/application/engine.py", "src/backtest/application/execution_contract.py",
        "src/market/infrastructure/store_panel.py"]
    return {p: sha256(ROOT/p) for p in paths}


def original_rank(candidates: pd.DataFrame, score: pd.DataFrame) -> pd.DataFrame:
    ranked = score.where(candidates).reindex(columns=sorted(score.columns, key=str)).rank(
        axis=1, ascending=False, method="first").reindex(columns=score.columns)
    return (candidates & ranked.le(2)).fillna(False).astype(bool)


def corrected_shape(ctx: dict, economic: dict, factors: pd.DataFrame) -> dict:
    """Exactly the old shape, rebuilt before its inconsistent raw-limit gate.

    Rebuilding the old basis is necessary to restore as well as exclude cases;
    intersecting only old qualified candidates cannot recover false exclusions.
    Six shape booleans and original score components come from unchanged code.
    """
    raw = ctx["execution_panels"]
    signal_input = {**economic, "__raw_close": raw["close"],
                    "__instrument_names__": ctx["panels"]["__instrument_names__"]}
    result = ctx["engine"].compute(signal_input, ctx["resolved_params"])
    f = result.factors
    c, o, h, low, volume = (economic[k] for k in ("close", "open", "high", "low", "volume"))
    growth = c/c.shift(1)
    valid = (np.isfinite(c) & np.isfinite(o) & np.isfinite(h) & np.isfinite(low)
        & np.isfinite(volume) & volume.gt(0) & c.gt(0) & o.gt(0) & low.gt(0)
        & h.ge(c) & h.ge(o) & low.le(c) & low.le(o)).rolling(DEPENDENCY_BARS).sum().eq(DEPENDENCY_BARS)
    names = signal_input["__instrument_names__"]
    clean = pd.Series({code: len(str(code)) == 6 and str(code).isascii() and str(code).isdigit()
        and str(code).startswith(("300", "301")) and isinstance(names.get(str(code)), str)
        and bool(str(names.get(str(code)) or "").strip()) and not is_st_name(str(names.get(str(code)) or ""))
        and "退" not in str(names.get(str(code)) or "") for code in c.columns})
    finite = (np.isfinite(growth).astype(float).rolling(10).sum().shift(3).eq(10)
        & np.isfinite(growth) & np.isfinite(f["突破量比"]) & np.isfinite(f["回调均量比"])
        & np.isfinite(f["回调深度(%)"]) & np.isfinite(f["10日动量(%)"]))
    blocked, _, known = strict_price_masks(raw["close"].to_numpy(), raw["close"].to_numpy(),
        factors.to_numpy(), list(c.columns), raw["volume"].to_numpy())
    below = pd.DataFrame(known & ~blocked, index=c.index, columns=c.columns)
    base = valid & clean & f["有效日K根数"].gt(30) & finite & below
    candidate = base.copy()
    for field in ("前期强阳", "两日回调", "回调缩量", "收盘突破前五日高点", "当日放量", "阳线涨幅确认"):
        candidate &= f[field]
    candidate = candidate.fillna(False).astype(bool)
    components = [f[k] for k in ("10日动量分(40)", "回调缩量分(15)", "回调深度分(15)", "再突破放量分(10)", "收盘位置分(20)")]
    score = sum(components).where(candidate)
    score = score.where(np.isfinite(score)).clip(0, 100).round(4)
    candidate &= score.notna()
    return dict(candidates=candidate, original_score=score, original_selected=original_rank(candidate, score),
                formula_factors=f, normalized_raw_limit_candidates=result.factors["条件候选"], corrected_below_limit=below)


def market_features(store: CutoffMarketStore, index: pd.Index, end: str) -> tuple[dict, dict]:
    """Full stored ChiNext stock breadth, using only complete past20 sessions."""
    rows = store.conn.execute("SELECT code FROM instruments WHERE instrument_type='STOCK'").fetchall()
    codes = sorted(str(r[0]) for r in rows if len(str(r[0])) == 6 and str(r[0]).isascii()
                   and str(r[0]).isdigit() and str(r[0]).startswith(("300", "301")))
    if not codes:
        raise ValueError("No stored ChiNext STOCK breadth universe")
    wide = store.load_panel(fields=("close", "volume"), codes=codes, start=str(index[0]), end=end,
                            adjust="none", min_bars=20)
    wide = {key: value.reindex(index=index) for key, value in wide.items()}
    wide = normalized_economic(wide, snapshot_factors(store, wide["close"]))
    c, v = wide["close"], wide["volume"]
    quoted = np.isfinite(c) & c.gt(0) & np.isfinite(v) & v.gt(0)
    eligible = quoted.rolling(20).sum().eq(20)
    denominator = eligible.sum(axis=1)
    above = (c.gt(price_precision(c.rolling(20).mean())) & eligible).sum(axis=1)
    breadth = above/denominator.where(denominator.gt(0))
    index_close = store.load_panel(fields=("close",), codes=["000300"], start=str(index[0]), end=end,
                                   adjust="none", min_bars=20)["close"].reindex(index=index)["000300"]
    valid_index = np.isfinite(index_close) & index_close.gt(0)
    index_return = ((index_close/index_close.shift(20)-1)*100).where(
        valid_index.rolling(21).sum().eq(21))
    return {"csi300_return20_pct": index_return, "chinext_above_ma20_breadth": breadth}, dict(
        breadth_catalog_stock_codes=len(codes), breadth_columns=len(c.columns), breadth_denominator=denominator,
        benchmark_complete_sessions=int(valid_index.sum()), no_benchmark_forward_fill=True,
        contract="T-close features;20 consecutive positive economicC/positive rawV for breadth,21 finite positive index endpoints/history for20return; STOCK300/301 regardless of present name/ST/candidate membership.")


def shape_features(economic: dict, corrected: dict, market: dict) -> dict[str, pd.DataFrame | pd.Series]:
    c, o, h, low = (economic[k] for k in ("close", "open", "high", "low"))
    f = corrected["formula_factors"]
    impulse = (c/c.shift(1)).ge(1.05) & c.gt(o)
    age = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
    for sessions in range(3, 13):
        age = age.mask(age.isna() & impulse.shift(sessions).fillna(False), float(sessions))
    true_range = pd.DataFrame(np.maximum.reduce([(h-low).to_numpy(),
        (h-c.shift(1)).abs().to_numpy(), (low-c.shift(1)).abs().to_numpy()]), index=c.index, columns=c.columns)
    span = (h-low).where(h.gt(low))
    return {
        "momentum10_pct": f["10日动量(%)"], "csi300_return20_pct": market["csi300_return20_pct"],
        "recent_impulse_age": age, "pullback_depth_pct": f["回调深度(%)"],
        "contraction_volume_ratio": f["回调均量比"], "breakout_volume_ratio": f["突破量比"],
        "breakout_extension_pct": f["突破幅度(%)"], "chinext_above_ma20_breadth": market["chinext_above_ma20_breadth"],
        "close_location": (c-low)/span, "body_fraction": (c-o)/span,
        "range_over_prior_atr14": (h-low)/true_range.rolling(14).mean().shift(1),
        "pullback_support_distance_pct": (c/low.shift(1).rolling(2).min()-1)*100,
    }


def prepare_phase(start: str, end: str, db: Path = DB) -> dict[str, Any]:
    """Read one bounded phase; this prepares causal features, never labels."""
    store = CutoffMarketStore(db, end)
    try:
        engine = copy.copy(get(SLUG))
        engine.requires_full_history = True
        ctx = prepare_backtest_context(store, engine, start=start, end=end, config=BASELINE.config(end), source_evidence_mode="compact")
        legacy = engine.compute(ctx["panels"], ctx["resolved_params"])
        raw = ctx["execution_panels"]
        factor = snapshot_factors(store, raw["close"])
        ctx["execution_panels"] = {**raw, "__adjust_factor": factor}
        economic = normalized_economic(raw, factor)
        corrected = corrected_shape(ctx, economic, factor)
        market, evidence = market_features(store, raw["close"].index, end)
        features = shape_features(economic, corrected, market)
        return dict(ctx=ctx, start=start, end=end, features=features, corrected=corrected, legacy=legacy,
                    economic=economic, market_evidence=evidence, context_evidence=context_evidence(ctx))
    finally:
        store.close()


def candidate_frame(prepared: dict) -> pd.DataFrame:
    """Union preserves legacy-only technical exclusions for an honest control.

    Only corrected_candidate & feature_eligible rows belong to the model pool;
    all other rows remain auditable and can belong to the explicit controls.
    """
    corrected, legacy, features = prepared["corrected"], prepared["legacy"], prepared["features"]
    old = legacy.factors["条件候选"].fillna(False).astype(bool) & legacy.factors["score"].notna()
    candidate = corrected["candidates"]
    window = pd.Series((candidate.index >= prepared["start"]) & (candidate.index <= prepared["end"]), index=candidate.index)
    union = (candidate | old).where(window, False, axis=0)
    rows, cols = np.nonzero(union.to_numpy())
    records = []
    for row, col in zip(rows, cols):
        day, code = str(candidate.index[row]), str(candidate.columns[col])
        values = {name: float(value.at[day, code] if isinstance(value, pd.DataFrame) else value.at[day]) for name, value in features.items()}
        missing = [name for name, value in values.items() if not np.isfinite(value)]
        records.append(dict(decision_date=day, signal_date=day, code=code, row=int(row), col=int(col),
            corrected_candidate=bool(candidate.iat[row, col]), legacy_candidate=bool(old.iat[row, col]),
            legacy_selected=bool(legacy.signals.iat[row, col]),
            original_score=float(corrected["original_score"].iat[row, col]), legacy_score=float(legacy.factors["score"].iat[row, col]),
            feature_eligible=not missing, missing_features=";".join(missing), **values))
    columns = ["decision_date", "signal_date", "code", "row", "col", "corrected_candidate", "legacy_candidate", "legacy_selected",
               "original_score", "legacy_score", "feature_eligible", "missing_features", *FEATURES]
    return pd.DataFrame(records, columns=columns)


def label_candidates(prepared: dict, candidates: pd.DataFrame) -> pd.DataFrame:
    """Attach all-candidate labels using the unchanged original next-open exit.

    Closed labels mature on actual exit, not planned exit. Only positively
    known suspension or an upper-limit opening is a cancelled0 label. Unknown
    quotes/references or censored holdings stay unresolved with missing target.
    This deliberately performs no ranking or holding/cash-dependent exclusion.
    """
    executor = Executor(prepared["ctx"], prepared["end"])
    results = []
    for source in candidates.to_dict("records"):
        row, col = int(source["row"]), int(source["col"])
        entry = row+1
        status, reason, available, target, trade = "unresolved", "entry_beyond_data", None, np.nan, None
        if entry < len(executor.dates):
            day = str(executor.dates[entry])
            volume, opening = executor.values["volume"][entry, col], executor.values["open"][entry, col]
            if np.isfinite(volume) and volume <= 0:
                status, reason, available, target = "cancelled", "known_nonpositive_volume", day, 0.
            elif not np.isfinite(volume):
                reason = "unknown_volume"
            elif not np.isfinite(opening) or opening <= 0:
                reason = "unknown_or_invalid_open"
            elif not executor.known[entry, col]:
                reason = "unknown_limit_reference"
            elif executor.blocked[entry, col]:
                status, reason, available, target = "cancelled", "known_limit_up_open", day, 0.
            else:
                trade, reason, _ = executor.one(dict(row=row, col=col), "fixed4", False)
                if trade is not None:
                    status, available, target = "closed", trade.exit_date, trade.net_return_pct
        record = {**source, "label_status": status, "label_available_date": available,
                  "net_return_pct": target, "label_reason": reason}
        if trade is not None:
            record.update(trade.to_dict(include_factors=True))
        else:
            record["entry_date"] = str(executor.dates[entry]) if entry < len(executor.dates) else None
        if available is not None and (available <= source["decision_date"] or available > prepared["end"]):
            raise AssertionError("Label maturity violates the next-open phase contract")
        results.append(record)
    return pd.DataFrame(results)


def eligible_model_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame.corrected_candidate & frame.feature_eligible].copy()


def select_policy(frame: pd.DataFrame, policy: str, prediction: pd.Series | None = None) -> pd.DataFrame:
    """Select at T close before reading attached label/next-open information."""
    if policy not in (*CONTROLS, *POLICIES):
        raise ValueError(f"Unknown learned-rank arm: {policy}")
    if policy == "legacy_original":
        selected = frame[frame.legacy_selected].copy()
        selected["selection_score"] = selected.legacy_score
        return selected.sort_values(["decision_date", "selection_score", "code"], ascending=[True, False, True])
    pool = frame[frame.corrected_candidate].copy()
    if policy != "corrected_original":
        pool = pool[pool.feature_eligible]
    if policy in POLICIES:
        if prediction is None or not pool.index.isin(prediction.index).all():
            raise ValueError("Predictions must cover every eligible causal candidate")
        pool["selection_score"] = prediction.reindex(pool.index).round(10)
        if not np.isfinite(pool.selection_score).all():
            raise ValueError("Non-finite prediction is not a candidate filter")
        if policy == "positive_only":
            pool = pool[pool.selection_score > 0]
    else:
        pool["selection_score"] = pool.original_score
    return pool.sort_values(["decision_date", "selection_score", "code"], ascending=[True, False, True]).groupby("decision_date", sort=False).head(2)


def common_decision_dates(prepared: dict) -> list[str]:
    index = prepared["ctx"]["execution_panels"]["close"].index
    mature = common_maturity_mask(index, prepared["start"], prepared["end"], entry_timing="next_open", max_hold=4)
    return list(map(str, index[mature]))


def save_features(prepared: dict, phase: str, output: Path) -> pd.DataFrame:
    frame = candidate_frame(prepared)
    if not feature_complete(frame, list(FEATURES)).equals(frame.feature_eligible):
        raise AssertionError("Adapter/core feature eligibility differs")
    frame.to_csv(output/f"{phase}-candidates.csv", index=False)
    evidence = dict(prepared["market_evidence"])
    denominator = evidence.pop("breadth_denominator")
    pd.DataFrame({"decision_date": denominator.index, "breadth_denominator": denominator.to_numpy(),
        "breadth": prepared["features"]["chinext_above_ma20_breadth"].to_numpy(),
        "csi300_return20_pct": prepared["features"]["csi300_return20_pct"].to_numpy()}).to_csv(output/f"{phase}-market-features.csv", index=False)
    write_json(output/f"{phase}-data-receipt.json", dict(context=prepared["context_evidence"], market=evidence,
        old_candidates=int(frame.legacy_candidate.sum()), corrected_candidates=int(frame.corrected_candidate.sum()),
        old_only=int((frame.legacy_candidate & ~frame.corrected_candidate).sum()),
        corrected_only=int((frame.corrected_candidate & ~frame.legacy_candidate).sum()),
        corrected_missing_features=int((frame.corrected_candidate & ~frame.feature_eligible).sum()),
        eligible_model_candidates=int((frame.corrected_candidate & frame.feature_eligible).sum())))
    return frame


def check_past_feature_prefix(prepared: dict, historical_frame: pd.DataFrame) -> None:
    candidates = prepared["corrected"]["candidates"]
    for row in historical_frame.to_dict("records"):
        day, code = row["decision_date"], row["code"]
        if day not in candidates.index or code not in candidates.columns:
            raise AssertionError("Historical candidate disappeared from later context")
        if bool(candidates.at[day, code]) != bool(row["corrected_candidate"]):
            raise AssertionError("Future phase changed a historical corrected candidate")
        for name in FEATURES:
            f = prepared["features"][name]
            value = f.at[day, code] if isinstance(f, pd.DataFrame) else f.at[day]
            if not np.isclose(value, row[name], atol=1e-8, rtol=1e-10, equal_nan=True):
                raise AssertionError(f"Future phase changed historical feature: {name}")


def trade_metrics(orders: pd.DataFrame, budget: int, cost: float, winner_key: tuple | None = None) -> dict:
    closed = orders[orders.label_status.eq("closed")]
    if winner_key is not None:
        closed = closed[~(closed.decision_date.eq(winner_key[0]) & closed.code.eq(winner_key[1]))]
    values = closed.gross_return_pct.to_numpy(dtype=float)-cost if len(closed) else np.array([], dtype=float)
    wins, losses = values[values > 0], values[values <= 0]
    unknown = int(orders.label_status.eq("unresolved").sum())
    return dict(trades=len(values), wins=len(wins), losses=len(losses),
        positive_net_sum=float(wins.sum()), negative_net_sum=float(losses.sum()), zero_net_trades=int((values == 0).sum()),
        avg_net_return=float(values.mean()) if len(values) else None,
        profit_factor=float(wins.sum()/-losses.sum()) if len(losses) and losses.sum() < 0 else None,
        win_rate=float(len(wins)/len(values)*100) if len(values) else None,
        net_sum=None if unknown else float(values.sum()), common_slot_mean=None if unknown else float(values.sum()/budget),
        unresolved=unknown, cancelled=int(orders.label_status.eq("cancelled").sum()), selected_orders=len(orders), common_slots=budget)


def metrics_bundle(orders: pd.DataFrame, budget: int) -> dict:
    closed = orders[orders.label_status.eq("closed")]
    winner = closed.loc[closed.net_return_pct.idxmax()] if len(closed) else None
    key = (winner.decision_date, winner.code) if winner is not None else None
    return {**{name: trade_metrics(orders, budget, cost, removed) for name, cost, removed in (
        ("base", .21, None), ("double_cost", .42, None), ("winner_removed", .21, key), ("double_cost_winner_removed", .42, key))},
        "largest_winner": winner.to_dict() if winner is not None else None}


def phase_pass(run: dict, controls: dict, minimum_trades: int, minimum_months: int, require_combined_stress: bool) -> bool:
    m = run["metrics"]["base"]
    pf_good = (m["profit_factor"] is not None and m["profit_factor"] > 1) or (m["positive_net_sum"] > 0 and m["negative_net_sum"] == 0)
    controls_good = m["common_slot_mean"] is not None and all(c["metrics"]["base"]["common_slot_mean"] is not None
        and m["common_slot_mean"] > c["metrics"]["base"]["common_slot_mean"] for c in controls.values())
    stress = run["metrics"]["double_cost_winner_removed"]["avg_net_return"]
    return bool(m["unresolved"] == 0 and m["trades"] >= minimum_trades and run["active_entry_months"] >= minimum_months
        and m["avg_net_return"] is not None and m["avg_net_return"] > 0 and pf_good and controls_good
        and (not require_combined_stress or (stress is not None and stress > 0)))


def evaluate_phase(phase: str, model: dict, policies: list[str], output: Path, previous_features: pd.DataFrame) -> tuple[dict, dict, pd.DataFrame]:
    prepared = prepare_phase(*PHASES[phase])
    check_past_feature_prefix(prepared, previous_features)
    frame = save_features(prepared, phase, output)
    allowed = common_decision_dates(prepared)
    evaluation = frame[frame.decision_date.isin(allowed)].copy()
    predictions = predict_ridge(model, eligible_model_rows(evaluation)).round(10)
    predictions.rename("predicted_net_pct").to_frame().join(evaluation[["decision_date", "code"]]).to_csv(output/f"{phase}-predictions.csv", index=False)
    # All names are committed before reading the phase's future trade labels.
    selections = {arm: select_policy(evaluation, arm, predictions) for arm in (*CONTROLS, *policies)}
    for arm, selected in selections.items():
        selected.to_csv(output/f"{phase}-{arm}-preselected.csv", index=False)
    write_json(output/f"{phase}-selection-receipt.json", dict(created_at=now(),
        model_sha256=sha256(output/("inner-model.json" if phase == "inner_validation" else "full-model.json")),
        preselected_sha256={arm: sha256(output/f"{phase}-{arm}-preselected.csv") for arm in selections},
        labels_not_yet_evaluated_for_phase=True, common_market_days=len(allowed), common_slots=2*len(allowed)))
    labels = label_candidates(prepared, frame)
    labels.to_csv(output/f"{phase}-all-candidate-labels.csv", index=False)
    runs, orders_by, dailies = {}, {}, []
    for arm, selected in selections.items():
        orders = selected[["decision_date", "code", "selection_score"]].merge(labels, on=["decision_date", "code"], how="left", validate="one_to_one")
        if len(orders) != len(selected) or orders.label_status.isna().any():
            raise AssertionError("Preselected order has no explicit label state")
        orders.to_csv(output/f"{phase}-{arm}-orders.csv", index=False)
        closed = orders[orders.label_status.eq("closed")]
        closed.to_csv(output/f"{phase}-{arm}-trades.csv", index=False)
        totals = closed.groupby("decision_date").net_return_pct.sum()
        unknown = set(orders.loc[orders.label_status.eq("unresolved"), "decision_date"])
        daily = pd.DataFrame([dict(segment=phase, variant=arm, signal_date=d, opportunities=2,
            net_sum=np.nan if d in unknown else float(totals.get(d, 0.))) for d in allowed])
        m = metrics_bundle(orders, 2*len(allowed))
        runs[arm] = dict(metrics=m, active_entry_months=int(closed.entry_date.str[:7].nunique()) if len(closed) else 0,
            selected_order_dates=int(orders.decision_date.nunique()), closed_on_new_vs_legacy=int((~closed.legacy_selected).sum()),
            original_common_slots=2*len(allowed))
        orders_by[arm] = orders
        dailies.append(daily)
        print(f"{phase}/{arm}: {json.dumps(m['base'])}", flush=True)
    baselines = {str(d.variant.iloc[0]): d.set_index("signal_date").net_sum for d in dailies if d.variant.iloc[0] in CONTROLS}
    for daily in dailies:
        arm = str(daily.variant.iloc[0])
        runs[arm]["paired_vs_controls"] = {}
        for control, base in baselines.items():
            pair = daily.assign(base_net_sum=daily.signal_date.map(base))
            pair["delta_net_sum"] = pair.net_sum-pair.base_net_sum
            runs[arm]["paired_vs_controls"][control] = None if pair.delta_net_sum.isna().any() else paired_bootstrap(pair)
    density = {}
    for label, mask in (("corrected_full", evaluation.corrected_candidate), ("feature_eligible", evaluation.corrected_candidate & evaluation.feature_eligible)):
        counts = evaluation.loc[mask].groupby("decision_date").size().reindex(allowed, fill_value=0)
        density[label] = {"zero": int(counts.eq(0).sum()), "one": int(counts.eq(1).sum()), "two": int(counts.eq(2).sum()), "over_two": int(counts.gt(2).sum())}
    original_keys = set(zip(selections["eligible_original"].decision_date, selections["eligible_original"].code))
    replacements = {}
    for arm in policies:
        keys = set(zip(selections[arm].decision_date, selections[arm].code))
        replacements[arm] = dict(added_names=len(keys-original_keys), removed_names=len(original_keys-keys),
            changed_dates=len({d for d, _ in keys.symmetric_difference(original_keys)}))
    daily = pd.concat(dailies, ignore_index=True)
    daily.to_csv(output/f"{phase}-daily-budget.csv", index=False)
    result = dict(start=PHASES[phase][0], end=PHASES[phase][1], common_market_days=len(allowed), common_slots=2*len(allowed),
        first_signal_day=allowed[0], last_signal_day=allowed[-1], runs=runs, candidate_density=density,
        replacements_vs_eligible_original=replacements, historical_feature_prefix_passed=True,
        candidate_label_status_counts=labels.label_status.value_counts().to_dict())
    write_json(output/f"{phase}-summary.json", result)
    return result, orders_by, daily


def fit_phase(phase: str, output: Path) -> tuple[dict, pd.DataFrame]:
    prepared = prepare_phase(*PHASES[phase])
    frame = save_features(prepared, phase, output)
    labels = label_candidates(prepared, frame)
    labels.to_csv(output/f"{phase}-all-candidate-labels.csv", index=False)
    training = labels[labels.corrected_candidate].copy()
    model = fit_ridge(training, list(FEATURES), fit_start=PHASES[phase][0], fit_end=PHASES[phase][1],
                      validation_start="2025-01-01" if phase == "inner_fit" else "2025-07-01")
    write_json(output/("inner-model.json" if phase == "inner_fit" else "full-model.json"), model)
    write_json(output/f"{phase}-label-receipt.json", dict(candidate_rows=len(labels), corrected_rows=len(training),
        label_status_counts=training.label_status.value_counts().to_dict(), model_training_rows=model["training_rows"],
        actual_maturity_not_planned_maturity=True, maximum_used_label_date=model["max_label_available_date"]))
    print(f"Fitted {phase}: {model['training_rows']} labels/{model['training_dates']}dates", flush=True)
    return model, frame


def freeze(output: Path = OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    if (output/"PLAN.json").exists():
        raise FileExistsError("Preserve frozen learned-rank study")
    if sha256(ROOT_PLAN) != ROOT_PLAN_SHA or sha256(ROOT/"tools/research_regularized_rank_core.py") != CORE_SHA:
        raise AssertionError("Shared frozen plan/core mismatch")
    plan = dict(created_at=now(), root_plan_sha256=ROOT_PLAN_SHA, core_sha256=CORE_SHA, sources=sources(),
        snapshot_sha256=sha256(DB), feature_names=list(FEATURES), phases=PHASES, controls=CONTROLS, policies=POLICIES,
        adapter_contract_sha256=sha256(output/"draft-contract.md"),
        exact_feature_formulas="draft-contract.md feature table, bound by SHA; all12 fixed before returns.",
        numeric="DirectSQL hfq_factor asof each date, forward-only. Signal10significant digits; exact raw*factor execution. Rebuild old basis/6shape booleans before shared economic-reference close-limit gate; original5score components unchanged.",
        labels="All corrected candidates,notTop2. closed=gross-.21,available actualexit; knownlimitup or finiteV<=0 cancelled0 atentryday; unknownquote/volume/reference/unresolvedexit staysnull. Actual2024maturity,never2023outcomes.",
        evaluation="Uniform4-session planned-maturity calendar ALLarms,2slots/day includingempty. Freeze preselection beforelabels;cancel norefill;selectedunknown disablesnomination. Independent events original4/-6;no cash/dedup/cooldown change.",
        nomination="SharedPLAN exact gates:2024fit100labels/60dates/6months;inner20closed/3months,positive mean/PF,combinedcost-winnerpositive,slot>ALL3controls;noqualifierSTOP. Later each12/4months+positive/PF+slot>allcontrols;pooled40+all3stresspositive.",
        limitations=["Previously observed history; chronological inner validation does not erase retrospective selection bias.",
            "Current catalog/names/factor revisions notPIT; daily-next-open proxy not auction queue proof.", "Independent event slots not shared-capital NAV."])
    prior = output/"preflight-failure"
    if prior.exists():
        plan["preflight_failure"] = dict(original_plan_sha256=sha256(prior/"PLAN.json"), original_source_sha256=sha256(prior/"source.py.txt"),
            reason="Candidate-frame date mask was a bare ndarray rejected by pandas.where. Converted to same-indexSeries only; failure occurred before any labels/model/returns were computed.")
    write_json(output/"PLAN.json", plan)
    write_json(output/"freeze-receipt.json", dict(created_at=now(), plan_sha256=sha256(output/"PLAN.json"), shared_root_plan_sha256=ROOT_PLAN_SHA, core_sha256=CORE_SHA))
    print(json.dumps(dict(frozen=True, plan_sha256=sha256(output/"PLAN.json"))), flush=True)


def verify_frozen(plan: dict, output: Path):
    if (sources() != plan["sources"] or sha256(DB) != plan["snapshot_sha256"] or sha256(ROOT_PLAN) != ROOT_PLAN_SHA
        or sha256(output/"draft-contract.md") != plan["adapter_contract_sha256"]):
        raise AssertionError("Frozen learned-rank inputs changed")


def run(output: Path = OUTPUT):
    plan = json.loads((output/"PLAN.json").read_text(encoding="utf-8"))
    verify_frozen(plan, output)
    if (output/"inner-model.json").exists() or (output/"summary.json").exists():
        raise FileExistsError("Preserve previous learned-rank results")
    try:
        model, past = fit_phase("inner_fit", output)
    except ValueError as error:
        if "Insufficient training information" not in str(error):
            raise
        verify_frozen(plan, output)
        write_json(output/"summary.json", dict(completed_at=now(), status="insufficient_training_information", reason=str(error),
            nominees=[], later_not_read=True, source_snapshot_unchanged=True, plan_sha256=sha256(output/"PLAN.json")))
        return
    verify_frozen(plan, output)
    inner, _, _ = evaluate_phase("inner_validation", model, list(POLICIES), output, past)
    controls = {c: inner["runs"][c] for c in CONTROLS}
    nominees = [p for p in POLICIES if phase_pass(inner["runs"][p], controls, 20, 3, True)]
    write_json(output/"inner-nomination.json", dict(created_at=now(), nominees=nominees,
        inner_summary_sha256=sha256(output/"inner_validation-summary.json"), inner_model_sha256=sha256(output/"inner-model.json"),
        plan_sha256=sha256(output/"PLAN.json"), selection_uses_only_inner_validation=True, later_not_yet_read=True))
    result = dict(plan_sha256=sha256(output/"PLAN.json"), inner=inner, nominees=nominees, later={}, passes_later={})
    if nominees:
        verify_frozen(plan, output)
        full, fullpast = fit_phase("full_refit", output)
        write_json(output/"full-refit-receipt.json", dict(created_at=now(), model_sha256=sha256(output/"full-model.json"),
            nomination_sha256=sha256(output/"inner-nomination.json"), unchanged_nominees=nominees))
        pooled, all_daily = {a: [] for a in (*CONTROLS, *nominees)}, []
        for phase in ("validation_2025h2", "observed_2026"):
            verify_frozen(plan, output)
            summary, orders, daily = evaluate_phase(phase, full, nominees, output, fullpast)
            result["later"][phase] = summary
            for arm, frame in orders.items():
                pooled[arm].append(frame)
            all_daily.append(daily)
        combined = pd.concat(all_daily, ignore_index=True)
        result["pooled_post_train"] = {arm: metrics_bundle(pd.concat(frames, ignore_index=True), int(combined.loc[combined.variant.eq(arm), "opportunities"].sum())) for arm, frames in pooled.items()}
        for policy in nominees:
            passes = [phase_pass(stage["runs"][policy], {c: stage["runs"][c] for c in CONTROLS}, 12, 4, False) for stage in result["later"].values()]
            m = result["pooled_post_train"][policy]
            result["passes_later"][policy] = all(passes) and m["base"]["trades"] >= 40 and all(m[k]["avg_net_return"] is not None and m[k]["avg_net_return"] > 0 for k in ("double_cost", "winner_removed", "double_cost_winner_removed"))
        combined.to_csv(output/"post-train-daily-budget.csv", index=False)
    verify_frozen(plan, output)
    result.update(completed_at=now(), status="later_evaluated" if nominees else "stopped_no_inner_qualifier", later_not_read=not nominees,
        no_2023h2_outcomes=True, source_snapshot_unchanged=True)
    write_json(output/"summary.json", result)
    print(json.dumps(dict(status=result["status"], nominees=nominees, passes_later=result["passes_later"])), flush=True)


def self_check() -> dict:
    dates = pd.bdate_range("2024-01-01", periods=15).strftime("%Y-%m-%d")
    code = "300001"
    raw = {k: pd.DataFrame(value, index=dates, columns=[code]) for k, value in {
        "open": 100., "high": 101., "low": 99., "close": 100., "volume": 100., "__adjust_factor": 1.}.items()}
    frame = pd.DataFrame([dict(decision_date=str(dates[2]), signal_date=str(dates[2]), code=code, row=2, col=0)])
    prepared = {"ctx": {"execution_panels": raw}, "end": str(dates[-1])}
    base = label_candidates(prepared, frame).iloc[0]
    assert base.label_status == "closed" and base.label_available_date == dates[6]
    raw["volume"].iloc[3, 0] = 0.
    assert label_candidates(prepared, frame).iloc[0].label_status == "cancelled"
    raw["volume"].iloc[3, 0] = np.nan
    assert label_candidates(prepared, frame).iloc[0].label_status == "unresolved"
    raw["volume"].iloc[3, 0] = 100.
    raw["open"].iloc[3, 0] = 120.
    assert label_candidates(prepared, frame).iloc[0].label_status == "cancelled"
    raw["open"].iloc[3, 0] = np.nan
    assert label_candidates(prepared, frame).iloc[0].label_status == "unresolved"
    choices = pd.DataFrame(dict(decision_date=[str(dates[2])]*3, code=["300003", "300002", "300001"],
        corrected_candidate=True, feature_eligible=True, original_score=[3., 2., 1.],
        label_status=["closed", "unresolved", "closed"]))
    prediction = pd.Series([1., 2., 2.], index=choices.index)
    selected = select_policy(choices, "rank_only", prediction)
    assert selected.code.tolist() == ["300001", "300002"]
    assert "unresolved" in selected.label_status.tolist()
    assert select_policy(choices, "positive_only", pd.Series([0., -1., 1e-12])).empty
    # A complete synthetic original shape; constant factors must not change
    # the underlying candidate contract, and a shorter prefix must match.
    shape_dates = pd.bdate_range("2024-01-01", periods=65).strftime("%Y-%m-%d")
    shape_raw = {k: pd.DataFrame(value, index=shape_dates, columns=[code]) for k, value in {
        "open": 100., "high": 101., "low": 99., "close": 100., "volume": 1000.}.items()}
    for i in range(42, 48):
        for k, value in dict(open=100. if i == 42 else 108., high=109., low=99. if i == 42 else 107., close=108.).items():
            shape_raw[k].iloc[i, 0] = value
    for i, values in ((48, dict(open=108., high=108.5, low=106.5, close=107., volume=400.)),
                      (49, dict(open=107., high=107.5, low=105.5, close=106., volume=300.)),
                      (50, dict(open=106., high=112.5, low=105.7, close=112., volume=1000.))):
        for k, value in values.items():
            shape_raw[k].iloc[i, 0] = value
    shape_factor = pd.DataFrame(1., index=shape_dates, columns=[code])
    shape_ctx = dict(engine=get(SLUG), resolved_params={}, execution_panels=shape_raw,
                     panels={"__instrument_names__": {code: "synthetic"}})
    fixed = corrected_shape(shape_ctx, shape_raw, shape_factor)
    assert fixed["candidates"].at[shape_dates[50], code]
    pd.testing.assert_frame_equal(fixed["candidates"], fixed["normalized_raw_limit_candidates"])
    prefix_raw = {k: v.iloc[:51] for k, v in shape_raw.items()}
    prefix = corrected_shape({**shape_ctx, "execution_panels": prefix_raw}, prefix_raw, shape_factor.iloc[:51])
    pd.testing.assert_frame_equal(prefix["candidates"], fixed["candidates"].iloc[:51])
    market = {name: pd.Series(0.5, index=shape_dates) for name in ("csi300_return20_pct", "chinext_above_ma20_breadth")}
    full_features = shape_features(shape_raw, fixed, market)
    prefix_features = shape_features(prefix_raw, prefix, {k: v.iloc[:51] for k, v in market.items()})
    assert list(full_features) == list(FEATURES)
    for name in FEATURES:
        check = pd.testing.assert_frame_equal if isinstance(full_features[name], pd.DataFrame) else pd.testing.assert_series_equal
        check(prefix_features[name], full_features[name].iloc[:51])
    return dict(passed=True, checks=["Actual exit maturity", "Known suspension/limit-up cancelled0", "Missing quote/volume unresolved",
        "Selection cannot exclude future unresolved status", "Rounded predicted return, code tie and strictpositive",
        "Original constant-factor shape contract", "Signal and feature prefix causality"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["freeze", "run"])
    args = parser.parse_args()
    (freeze if args.phase == "freeze" else run)()
