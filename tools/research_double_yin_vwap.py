"""Two frozen daily-VWAP filters for the complete double-yin shape pool.

No live strategy mutation. A day's aggregate VWAP describes a price position,
not the time order of trading or proof of active absorption.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.domain.models import Trade  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore, common_maturity_mask, sha256  # noqa: E402
from tools.research_double_yin_learned_rank import order_budget, order_labels  # noqa: E402
from tools.research_double_yin_redesign import config, execute, execution_arrays, mask_keys, metrics  # noqa: E402
from tools.research_double_yin_regime import DB, GROUPS, corrected_inputs, full_shape_score, price_precision  # noqa: E402
from tools.research_double_yin_scoring_proxy import prepare_proxy_context, rank_with_groups  # noqa: E402
from tools.research_impulse_scoring import paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-double-yin-vwap"
ROOT_PLAN = ROOT / "docs/research/2026-10-04-vwap-study/PLAN.md"
ROOT_PLAN_SHA = "5b12aa558234e2904b412a3ddefd96bae5e56ad6d2e93da27fe221d699763034"
READINESS = ROOT / "docs/research/2026-10-04-learned-rank/data-readiness.md"
SPLITS = {"train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}
CONTROLS = ["corrected_low_open", "full_shape", "vwap_eligible_full_shape"]
POLICIES = ["yin_close_above_vwap", "yin_close_and_open_above_vwap"]


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sources() -> dict:
    names = ["tools/research_double_yin_vwap.py", "tools/research_double_yin_learned_rank.py",
             "tools/research_double_yin_regime.py", "tools/research_double_yin_repair.py",
             "tools/research_double_yin_redesign.py", "tools/research_double_yin_scoring_proxy.py",
             "tools/research_chinext_payoff_exits.py", "tools/research_impulse_scoring.py",
             "src/strategy/application/double_yin_low_open.py", "src/backtest/application/engine.py",
             "src/backtest/application/execution_contract.py", "src/backtest/domain/models.py",
             "src/market/infrastructure/store_panel.py", "src/market/infrastructure/tdx_daily.py"]
    return {name: sha256(ROOT / name) for name in names}


def plan() -> dict:
    if sha256(ROOT_PLAN) != ROOT_PLAN_SHA:
        raise AssertionError("Root VWAP hypothesis/acceptance freeze changed")
    return {"created_at": now(), "controls": CONTROLS, "policies": POLICIES, "splits": SPLITS,
            "origin": "Original complete corrected strong-up then double-volume-yin shape, not low-open subset. Raw T opening must be finite and>6. Same main/nonST/name/history/recent-gain identity and full original60/40 score; filter full pool before industry-intersection Top2.",
            "vwap_definition": "Raw A_yin yuan/raw V_yin shares; warehouse TDX V has already converted lots to shares, no extra100. Neither amount nor shares are multiplied by HFQ. VWAP itself is a price and is multiplied by direct factor only for cross-date price comparison.",
            "eligibility": "Only T-1 requires row source exactlytdx, finite positive raw amount,volume,low,high with high>=low, and L-.01-1e-10<=A/V<=H+.01+1e-10. Invalid/unknown prior VWAP excludes the candidate with a reason, no close*volume substitution or clamping. NoT amount,volume,source,HLC completeness restriction for preselection.",
            "A": "At T open, normalized economic C[T-1]>=normalized(A[T-1]/V[T-1]*factor[T-1]). Describes the yin close relative to daily VWAP, not an intraday temporal sequence.",
            "B": "A AND normalized rawO[T]*factor[T]>=normalized(A[T-1]/V[T-1]*factor[T-1]); equivalent to comparing rawO[T] with prior rawVWAP*factor[T-1]/factor[T]. No separate low-open gate and no VWAP distance threshold.",
            "numeric": "Direct sparse SQL factor dated<=phase cutoff,ffill only; quoted price without prior known factor fails. Existing10significant-digit signal geometry; actual fills,entry basis,stops and returns use unrounded raw*direct factor.",
            "controls_contract": "corrected_low_open retains old low-open behavior;full_shape has no VWAP eligibility gate;vwap_eligible_full_shape shares exactly the prior-day known-VWAP gate withA/B and keeps old score. All industry rules and execution identical. Eligibility removal is not credited to the VWAP relation.",
            "execution": "Original daily-opening proxy and4market sessions including entry,-6% stop,T+1,gap worse open,limit/suspension sell delays,cost0.21%. Select first;cancelled orders consume quota without refill. No new exit,cooldown,overlap or size parameter.",
            "unknown_contract": "Shared learned-rank order_labels plus this adapter's holding-path guard: finite nonpositiveT volume or known upper-limit open is confirmed cancelled0. MissingT volume/quote,unknown limit reference or unclosed fill is unresolved/null, never0. Claimed closed trades with nonfinite volume or an invalid positive-volume OHLC/factor/limit-reference anywhere from entry through exit become unresolved and leave closed-trade metrics; finite nonpositive-volume suspension days retain existing legal exit delays. T daily volume is used only to label execution after preselection; T amount/source/VWAP may be saved in a separately named postdecision QC file and never gate opening eligibility.",
            "budget": "For all5 arms,all market decision days with T+3<=segment end,2slots each including empty/filtered/cancelled days. Selected unresolved means whole-period slot mean and paired comparison unavailable. No-candidate days retained; no portfolioNAV claim.",
            "selection": {"train": ">=20closed,>=6entry months,net mean>0,PF>1(double-yin helper's nullPF with positive gains and no losses counts as unbounded positive PF),double-cost0.42and removal of original largest net winner leaves positive mean,slot_mean>ALL3 controls,no selected unknown;onlyA/B at most2,no fallback.",
                          "later": "Only frozen train qualifiers plus3controls in2025H2 and2026;each>=12closed,>=4months,mean>0,PF>1,slotmean>ALL3controls,no unknown. Combined>=40 and double-cost+largest-winner-removed mean>0. Only passes may enter rootcapitaloverlay.",
                          "stop": "No train qualifier stops family without later candidate returns;no new threshold,window,feature,model,ranking or exit rescue."},
            "limitations": ["Daily aggregate VWAP is neither holding-owner cost nor signed capital flow. C>=VWAP does not establish absorption,late recovery,or event timing.",
                            "B can buy a higher opening and exclude a later profitable below-VWAP opening;these are hypotheses,not a direction guaranteed by the statistic.",
                            "TDX row source plus source contract/unit/range audit supports aggregate evidence but is not tick reconstruction or field-levelPIT.",
                            "Current catalog/industry/revised factors and daily-open execution proxy remain;all periods previously observed,no freshOOS claim.",
                            "2023H2warmup only,no trade outcomes;turnover/outstanding shares not used."],
            "root_plan_sha256": ROOT_PLAN_SHA, "readiness_sha256": sha256(READINESS),
            "sources": sources(), "snapshot_sha256": sha256(DB), "groups_sha256": sha256(GROUPS)}


def verify_frozen() -> dict:
    frozen = json.loads((OUTPUT / "PLAN.json").read_text(encoding="utf-8"))
    if (sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"]
            or sha256(GROUPS) != frozen["groups_sha256"] or sha256(ROOT_PLAN) != frozen["root_plan_sha256"]):
        raise AssertionError("Frozen source/root hypothesis/data/groups changed")
    return frozen


def vwap_inputs(raw: dict, economic: dict, factors: pd.DataFrame, amount: pd.DataFrame, source: pd.DataFrame) -> dict:
    volume, low, high = raw["volume"], raw["low"], raw["high"]
    numeric = np.isfinite(amount) & amount.gt(0) & np.isfinite(volume) & volume.gt(0)
    bars = np.isfinite(low) & low.gt(0) & np.isfinite(high) & high.ge(low)
    value = amount/volume.where(volume.gt(0))
    in_range = np.isfinite(value) & value.ge(low-.01-1e-10) & value.le(high+.01+1e-10)
    known = source.eq("tdx") & numeric & bars & in_range
    reason = pd.DataFrame("known", index=amount.index, columns=amount.columns)
    reason = reason.mask(~in_range, "vwap_outside_raw_range")
    reason = reason.mask(~bars, "invalid_prior_price_range")
    reason = reason.mask(~numeric, "missing_or_nonpositive_prior_amount_volume")
    reason = reason.mask(~source.eq("tdx"), "prior_source_not_verified_tdx")
    raw_vwap = value.where(known)
    economic_vwap = price_precision(raw_vwap*factors)
    previous = economic_vwap.shift(1)
    available = known.shift(1).fillna(False).astype(bool)
    a = (available & economic["close"].shift(1).ge(previous)).fillna(False).astype(bool)
    b = (a & economic["open"].ge(previous)).fillna(False).astype(bool)
    return {"known": available, "reason": reason.shift(1).fillna("missing_prior_session"),
            "previous_raw_vwap": raw_vwap.shift(1), "previous_economic_vwap": previous,
            "previous_amount": amount.shift(1), "previous_volume": volume.shift(1), "previous_source": source.shift(1),
            "yin_close_above_vwap": a, "yin_close_and_open_above_vwap": b,
            "postdecision_qc_current_raw_vwap": raw_vwap, "postdecision_qc_current_known": known}


def prepare(start: str, end: str) -> dict:
    store = CutoffMarketStore(DB, end)
    try:
        ctx, _, _, _, _, _ = prepare_proxy_context(store, start, end, config(end), GROUPS)
        corrected = corrected_inputs(ctx, store)
        raw, economic = ctx["panels"], corrected["economic"]
        reference = raw["close"]
        amount = store.load_panel(fields=("amount",), codes=list(reference.columns), start="2023-01-01",
                                  end=end, adjust="none", min_bars=0)["amount"].reindex_like(reference)
        placeholders = ",".join("?" for _ in reference.columns)
        records = store.conn.execute(f"SELECT trade_date,code,source FROM quotes_daily WHERE code IN ({placeholders}) "
                                     "AND trade_date>=? AND trade_date<=?", [*map(str, reference.columns), "2023-01-01", end]).fetchall()
        source = pd.DataFrame([tuple(r) for r in records], columns=["trade_date", "code", "source"]).pivot(
            index="trade_date", columns="code", values="source").reindex_like(reference)
        factors = ctx["execution_panels"]["__adjust_factor"]
        vwap = vwap_inputs(raw, economic, factors, amount, source)
        cutoff = str(reference.index[len(reference)*2//3])
        prefix_raw = {key: val.loc[:cutoff] if isinstance(val, pd.DataFrame) else val for key, val in raw.items()}
        prefix_econ = {key: val.loc[:cutoff] if isinstance(val, pd.DataFrame) else val for key, val in economic.items()}
        prefix = vwap_inputs(prefix_raw, prefix_econ, factors.loc[:cutoff], amount.loc[:cutoff], source.loc[:cutoff])
        for key in ("known", "reason", "previous_raw_vwap", "previous_economic_vwap", *POLICIES):
            pd.testing.assert_frame_equal(vwap[key].loc[:cutoff], prefix[key])
        full = corrected["origins"] & np.isfinite(raw["open"]) & raw["open"].gt(6)
        score = full_shape_score(economic, full)
        pd.testing.assert_frame_equal(score.where(corrected["candidates"]), corrected["score"])
        mature = common_maturity_mask(full.index, start, end, entry_timing="open", max_hold=4)
        candidates = full.where(mature, False, axis=0)
        groups = raw["__sector_groups__"]
        controls = {"corrected_low_open": corrected["baseline"].where(mature, False, axis=0),
                    "full_shape": rank_with_groups(candidates, score, groups)[0],
                    "vwap_eligible_full_shape": rank_with_groups(candidates & vwap["known"], score, groups)[0]}
        return {"ctx": ctx, "data": execution_arrays(ctx), "candidates": candidates, "score": score,
                "vwap": vwap, "economic": economic, "factors": factors, "groups": groups, "controls": controls,
                "days": list(map(str, full.index[mature])), "current_amount_for_qc_only": amount,
                "current_source_for_qc_only": source}
    finally:
        store.close()


def guard_holding_paths(trades: list[Trade], events: list[dict], data: dict) -> tuple[list[Trade], list[dict], dict]:
    """An absent intermediate bar is unknown, not proof no stop was hit."""
    dates = {str(day): row for row, day in enumerate(data["dates"])}
    codes = {str(code): col for col, code in enumerate(data["codes"])}
    unknown, guarded = set(), []
    for original in events:
        event = dict(original)
        if event["status"] == "closed":
            col = codes[event["code"]]
            for row in range(dates[event["entry_date"]], dates[event["exit_date"]]+1):
                volume = data["volume"][row, col]
                reason = None
                if not np.isfinite(volume):
                    reason = "nonfinite_volume"
                elif volume > 0:
                    prices = [data[key][row, col] for key in ("open", "high", "low", "close")]
                    factor = data["factors"][row, col]
                    if (not all(np.isfinite(value) and value > 0 for value in prices) or prices[1] < prices[2]
                            or prices[1] < max(prices[0], prices[3]) or prices[2] > min(prices[0], prices[3])):
                        reason = "invalid_traded_ohlc"
                    elif not np.isfinite(factor) or factor <= 0:
                        reason = "invalid_traded_factor"
                    elif not data["known"][row, col]:
                        reason = "unknown_traded_limit_reference"
                if reason is not None:
                    unknown.add((event["signal_date"], event["code"]))
                    event.update(status="unresolved_holding_path", opportunity_net_pct=None,
                                 first_unknown_path_date=str(data["dates"][row]), holding_path_reason=reason,
                                 unverified_exit_date=event.get("exit_date"), unverified_exit_price=event.get("exit_price"),
                                 unverified_exit_reason=event.get("exit_reason"), exit_date=None, exit_price=None, exit_reason=None)
                    break
        guarded.append(event)
    closed = [trade for trade in trades if (trade.signal_date, trade.code) not in unknown]
    counts = dict(Counter(event["status"] for event in guarded))
    if counts.get("closed", 0) != len(closed) or sum(counts.values()) != len(events):
        raise AssertionError("Guarded selected-order accounting does not balance")
    return closed, guarded, counts


def profit_factor_above_one(measure: dict) -> bool:
    value = measure["profit_factor"]
    if value is not None:
        return value > 1
    # The existing helper serializes a zero-loss denominator as null. Only a
    # positive numerator has unbounded PF; an empty/all-zero sample does not.
    return (measure["avg_win"] or 0) > 0 and (measure["avg_loss"] is None or measure["avg_loss"] == 0)


def evaluate(segment: str, policies: list[str]) -> dict:
    start, end = SPLITS[segment]
    print(f"Prepare VWAP {segment} cutoff={end}", flush=True)
    stage = prepare(start, end)
    selected = dict(stage["controls"])
    for name in policies:
        selected[name] = rank_with_groups(stage["candidates"] & stage["vwap"][name], stage["score"], stage["groups"])[0]
    rows, qc_rows = [], []
    for day, code in sorted(mask_keys(stage["candidates"])):
        i = stage["candidates"].index.get_loc(day)
        record = {"decision_date": day, "code": code, "score": float(stage["score"].at[day, code]),
                  "known_vwap": bool(stage["vwap"]["known"].at[day, code]),
                  "vwap_eligibility_reason": stage["vwap"]["reason"].at[day, code],
                  "economic_yin_close": float(stage["economic"]["close"].iloc[i-1][code]),
                  "economic_open": float(stage["economic"]["open"].at[day, code]),
                  "yin_factor": float(stage["factors"].iloc[i-1][code]), "opening_factor": float(stage["factors"].at[day, code])}
        record.update({key: stage["vwap"][key].at[day, code] for key in ("previous_amount", "previous_volume", "previous_source",
                      "previous_raw_vwap", "previous_economic_vwap", *POLICIES)})
        record.update({f"selected_{name}": bool(mask.at[day, code]) for name, mask in selected.items()})
        rows.append(record)
        # These T-day diagnostics are kept outside the opening input table and
        # are never referenced by eligibility, ranking or nomination.
        qc_rows.append({"decision_date": day, "code": code,
                        "postdecision_current_amount": stage["current_amount_for_qc_only"].at[day, code],
                        "postdecision_current_volume": stage["ctx"]["panels"]["volume"].at[day, code],
                        "postdecision_current_source": stage["current_source_for_qc_only"].at[day, code],
                        "postdecision_current_vwap_known": stage["vwap"]["postdecision_qc_current_known"].at[day, code]})
    candidates = pd.DataFrame(rows)
    candidates.to_csv(OUTPUT / f"{segment}-full-candidates-and-selection.csv", index=False)
    pd.DataFrame(qc_rows).to_csv(OUTPUT / f"{segment}-postdecision-qc-not-eligibility.csv", index=False)
    selection_hash = sha256(OUTPUT / f"{segment}-full-candidates-and-selection.csv")
    runs, budgets = {}, {}
    for name, mask in selected.items():
        print(f"Execute VWAP {segment}/{name}", flush=True)
        trades, events, counts = execute(stage["ctx"], mask, {"entry": "open", "exit": "fixed"}, {}, stage["data"])
        trades, events, counts = guard_holding_paths(trades, events, stage["data"])
        labels = order_labels(events, stage["data"], end)
        pd.DataFrame([trade.to_dict(include_factors=True) for trade in trades], columns=list(Trade.__dataclass_fields__)).to_csv(
            OUTPUT / f"{segment}-{name}-trades.csv", index=False)
        pd.DataFrame(events).to_csv(OUTPUT / f"{segment}-{name}-events.csv", index=False)
        labels.to_csv(OUTPUT / f"{segment}-{name}-labels.csv", index=False)
        budgets[name] = order_budget(labels, stage["days"])
        unknown = int(labels.label_status.eq("unresolved").sum())
        runs[name] = {"metrics": metrics(trades), "active_months": len({trade.entry_date[:7] for trade in trades}),
                      "selected_orders": len(events), "execution_accounting": counts,
                      "label_accounting": dict(Counter(labels.label_status)), "unresolved_selected": unknown,
                      "slots": len(stage["days"])*2,
                      "slot_mean": None if unknown else float(budgets[name].net_sum.sum()/(len(stage["days"])*2))}
    pairs = []
    for name, budget in budgets.items():
        for control in CONTROLS:
            pair = budget.copy()
            pair["delta_net_sum"] = pair.net_sum-budgets[control].net_sum
            pair["variant"], pair["control"], pair["segment"] = name, control, segment
            pairs.append(pair)
            runs[name][f"month_blocks_vs_{control}"] = None if pair.delta_net_sum.isna().any() else paired_bootstrap(pair)
    pd.concat(pairs, ignore_index=True).to_csv(OUTPUT / f"{segment}-paired-calendar.csv", index=False)
    counts = candidates.decision_date.value_counts().reindex(stage["days"], fill_value=0)
    summary = {"segment": segment, "completed_at": now(), "preselection_sha256": selection_hash, "runs": runs,
               "audit": {"full_candidates": len(candidates), "known_prior_vwap": int(candidates.known_vwap.sum()),
                         "eligibility_reasons": dict(Counter(candidates.vwap_eligibility_reason)),
                         "common_days": len(stage["days"]), "current_vwap_never_gates": True,
                         "prefix_causality": "passed", "full_score_parity": "passed",
                         "candidate_days": {"0": int(counts.eq(0).sum()), "1": int(counts.eq(1).sum()),
                                            "2": int(counts.eq(2).sum()), "more_than2": int(counts.gt(2).sum())}}}
    write_json(OUTPUT / f"{segment}-summary.json", summary)
    return summary


def failures(result: dict, runs: dict, min_closed: int, min_months: int, stress: bool) -> list[str]:
    base = result["metrics"]["base"]
    failed = []
    for condition, reason in [
        (result["unresolved_selected"] > 0, "selected_unknown"),
        (base["trades"] < min_closed, "insufficient_closed"),
        (result["active_months"] < min_months, "insufficient_months"),
        ((base["avg_net_return"] or 0) <= 0, "nonpositive_mean"),
        (not profit_factor_above_one(base), "PF_not_above_one"),
        (stress and (result["metrics"]["double_cost_largest_winner_removed"]["avg_net_return"] or 0) <= 0, "combined_stress_nonpositive"),
    ]:
        if condition:
            failed.append(reason)
    for control in CONTROLS:
        ref = runs[control]["slot_mean"]
        if result["slot_mean"] is None or ref is None or result["slot_mean"] <= ref:
            failed.append(f"calendar_not_above_{control}")
    return failed


def train() -> dict:
    verify_frozen()
    if (OUTPUT / "training-shortlist.json").exists():
        raise FileExistsError("Training evidence already frozen")
    result = evaluate("train", POLICIES)
    reasons = {name: failures(result["runs"][name], result["runs"], 20, 6, True) for name in POLICIES}
    selected = [name for name in POLICIES if not reasons[name]]
    short = {"created_at": now(), "selected": selected, "failures": reasons,
             "status": "qualified_train" if selected else "stop_no_train_qualifier",
             "train_sha256": sha256(OUTPUT / "train-summary.json"), "plan_sha256": sha256(OUTPUT / "PLAN.json")}
    write_json(OUTPUT / "training-shortlist.json", short)
    verify_frozen()
    write_json(OUTPUT / "summary.json", {"status": short["status"], "shortlist": short, "train": result,
               "later_evaluated": False, "source_snapshot_groups_unchanged": True})
    print(json.dumps(short), flush=True)
    return short


def later() -> None:
    verify_frozen()
    short = json.loads((OUTPUT / "training-shortlist.json").read_text(encoding="utf-8"))
    if short["train_sha256"] != sha256(OUTPUT / "train-summary.json") or short["plan_sha256"] != sha256(OUTPUT / "PLAN.json"):
        raise AssertionError("Training shortlist or results changed")
    if not short["selected"]:
        raise ValueError("No train qualifier: later returns prohibited")
    stages = {}
    for segment in ("validation_2025h2", "observed_2026"):
        if (OUTPUT / f"{segment}-summary.json").exists():
            raise FileExistsError("Later results already exist")
        stages[segment] = evaluate(segment, short["selected"])
    calendars = pd.concat([pd.read_csv(OUTPUT / f"{segment}-paired-calendar.csv") for segment in stages], ignore_index=True)
    pooled = {}
    for name in CONTROLS+short["selected"]:
        trades = []
        for segment in stages:
            frame = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str})
            trades.extend(Trade(**row) for row in frame.to_dict("records"))
        measures = metrics(trades)
        failed = {}
        if name in short["selected"]:
            failed = {segment: failures(stage["runs"][name], stage["runs"], 12, 4, False) for segment, stage in stages.items()}
            failed["combined"] = []
            if len(trades) < 40:
                failed["combined"].append("closed_below40")
            if (measures["double_cost_largest_winner_removed"]["avg_net_return"] or 0) <= 0:
                failed["combined"].append("combined_stress_nonpositive")
        pair_stats = {}
        for control in CONTROLS:
            pair = calendars[calendars.variant.eq(name) & calendars.control.eq(control)]
            pair_stats[control] = None if pair.delta_net_sum.isna().any() else paired_bootstrap(pair)
        pooled[name] = {"metrics": measures, "failures": failed, "month_blocks_vs_controls": pair_stats,
                        "later_qualified": name in short["selected"] and not any(failed.values())}
    verify_frozen()
    summary = json.loads((OUTPUT / "summary.json").read_text(encoding="utf-8"))
    write_json(OUTPUT / "summary.json", {**summary, "status": "finite_family_complete", "completed_at": now(),
               "later_evaluated": True, "later": stages, "pooled_later": pooled,
               "capital_candidates": [name for name in short["selected"] if pooled[name]["later_qualified"]]})
    print(json.dumps({"completed": True, "capital_candidates": [name for name in short["selected"] if pooled[name]["later_qualified"]]}), flush=True)


def self_check() -> dict:
    dates = pd.Index(["2025-01-02", "2025-01-03", "2025-01-06"])
    raw = {key: pd.DataFrame(value, index=dates, columns=["600001"]) for key, value in
           {"open": [20., 21., 9.8], "high": [21., 21., 10.], "low": [19., 19., 9.],
            "close": [20., 20., 9.8], "volume": [50., 100., 100.]}.items()}
    factors = pd.DataFrame([2., 2., 4.], index=dates, columns=["600001"])
    economic = {**raw, **{key: price_precision(raw[key]*factors) for key in ("open", "high", "low", "close")}}
    amount = pd.DataFrame([1000., 1950., 980.], index=dates, columns=["600001"])
    source = pd.DataFrame("tdx", index=dates, columns=["600001"])
    check = vwap_inputs(raw, economic, factors, amount, source)
    assert check["known"].iloc[-1, 0] and check[POLICIES[0]].iloc[-1, 0] and check[POLICIES[1]].iloc[-1, 0]
    assert check["previous_raw_vwap"].iloc[-1, 0] == 19.5  # warehousevolume shares,notlots
    changed_raw = {key: value.copy() for key, value in raw.items()}
    changed_economic = {key: value.copy() for key, value in economic.items()}
    for key in ("high", "low", "close", "volume"):
        changed_raw[key].iloc[-1, 0] = np.nan
        changed_economic[key].iloc[-1, 0] = np.nan
    changed_amount, changed_source = amount.copy(), source.copy()
    changed_amount.iloc[-1, 0], changed_source.iloc[-1, 0] = np.nan, "tencent"
    altered = vwap_inputs(changed_raw, changed_economic, factors, changed_amount, changed_source)
    for key in ("known", "reason", "previous_economic_vwap", *POLICIES):
        pd.testing.assert_frame_equal(check[key], altered[key])
    changed_economic["open"].iloc[-1, 0] = 9.7*4
    crossed = vwap_inputs(changed_raw, changed_economic, factors, changed_amount, changed_source)
    assert crossed[POLICIES[0]].iloc[-1, 0] and not crossed[POLICIES[1]].iloc[-1, 0]
    different_amount = amount.copy()
    different_amount.iloc[-2, 0] = 2050.  # same OHLCV,distinct actual turnover center
    shifted_center = vwap_inputs(raw, economic, factors, different_amount, source)
    assert shifted_center["known"].iloc[-1, 0] and not shifted_center[POLICIES[0]].iloc[-1, 0]
    different_amount.iloc[-2, 0] = 20000.
    assert not vwap_inputs(raw, economic, factors, different_amount, source)["known"].iloc[-1, 0]
    different_source = source.copy()
    different_source.iloc[-2, 0] = "tencent"
    assert not vwap_inputs(raw, economic, factors, amount, different_source)["known"].iloc[-1, 0]
    equal_amount = amount.copy()
    equal_amount.iloc[-2, 0] = 2000.
    assert vwap_inputs(raw, economic, factors, equal_amount, source)[POLICIES[0]].iloc[-1, 0]
    prefix = vwap_inputs({k: v.iloc[:-1] for k, v in raw.items()}, {k: v.iloc[:-1] for k, v in economic.items()},
                         factors.iloc[:-1], amount.iloc[:-1], source.iloc[:-1])
    for key in ("known", "reason", *POLICIES):
        pd.testing.assert_frame_equal(check[key].iloc[:-1], prefix[key])
    path_dates = ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    data = {key: np.full((5, 1), value) for key, value in
            {"open": 10., "high": 10.1, "low": 9.9, "close": 10., "volume": 100., "factors": 1.}.items()}
    data.update(dates=path_dates, codes=["600001"], known=np.ones((5, 1), dtype=bool),
                strict_entry=np.zeros((5, 1), dtype=bool), strict_down=np.zeros((5, 1), dtype=bool))
    selected = pd.DataFrame([False, True, False, False, False], index=path_dates, columns=["600001"])
    for change, field, value in (("missing_low", "low", np.nan), ("inconsistent_ohlc", "high", 9.95), ("missing_volume", "volume", np.nan),
                                ("known_suspension", "volume", 0.), ("unknown_limit", "known", False)):
        altered = {key: val.copy() if isinstance(val, np.ndarray) else val for key, val in data.items()}
        altered[field][2, 0] = value
        if change == "known_suspension":
            for key in ("open", "high", "low", "close"):
                altered[key][2, 0] = np.nan
        for key in ("open", "high", "low", "close"):
            altered[f"economic_{key}"] = altered[key]*altered["factors"]
        legacy_trades, legacy_events, _ = execute({"config": config(path_dates[-1])}, selected,
                                                 {"entry": "open", "exit": "fixed"}, {}, altered)
        assert len(legacy_trades) == 1
        checked_trades, checked_events, checked_counts = guard_holding_paths(legacy_trades, legacy_events, altered)
        checked_labels = order_labels(checked_events, altered, path_dates[-1])
        if change == "known_suspension":
            assert len(checked_trades) == 1 and checked_labels.label_status.eq("closed").all()
        else:
            assert not checked_trades and checked_counts == {"unresolved_holding_path": 1}
            assert checked_labels.label_status.eq("unresolved").all() and checked_labels.net_return_pct.isna().all()
            assert order_budget(checked_labels, [path_dates[1]]).net_sum.isna().all()
    assert profit_factor_above_one({"profit_factor": None, "avg_win": 1., "avg_loss": None})
    assert profit_factor_above_one({"profit_factor": None, "avg_win": 1., "avg_loss": 0.})
    assert not profit_factor_above_one({"profit_factor": None, "avg_win": None, "avg_loss": 0.})
    assert not profit_factor_above_one({"profit_factor": 0., "avg_win": None, "avg_loss": -1.})
    return {"status": "passed", "checks": ["warehouse_amount_div_shares_no_extra100", "cross_factor_common_coordinate",
            "today_amount_volume_source_HLC_cannot_gate", "A_and_B_have_distinct_opening_condition", "amount_adds_information_beyond_OHLCV",
            "out_of_range_vwap_unknown_not_clamped", "unverified_source_unknown", "close_equal_vwap_allowed", "prefix_causality",
            "missing_holding_low_unresolved", "inconsistent_holding_ohlc_unresolved", "missing_holding_volume_unresolved", "known_zero_volume_suspension_preserved",
            "unknown_holding_limit_reference_unresolved", "zero_loss_PF_positive_numerator_only"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["draft", "self-check", "freeze", "train", "later", "run"])
    args = parser.parse_args()
    if args.phase == "self-check":
        print(json.dumps(self_check()), flush=True)
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.phase in {"draft", "freeze"}:
        path = OUTPUT / ("PLAN-DRAFT.json" if args.phase == "draft" else "PLAN.json")
        if args.phase == "freeze" and path.exists():
            raise FileExistsError("VWAP adapter already frozen")
        checked = self_check()
        write_json(path, plan())
        write_json(OUTPUT / "self-check.json", checked)
        print(json.dumps({"phase": args.phase, "plan_sha256": sha256(path), "new_returns_observed": False}), flush=True)
    elif args.phase == "train":
        train()
    elif args.phase == "later":
        later()
    else:
        short = train()
        if short["selected"]:
            later()


if __name__ == "__main__":
    main()
