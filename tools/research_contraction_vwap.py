"""Finite T-close daily-VWAP experiment; isolated train-first research only.

No production selector, market data or previously frozen study is modified.
``self-check`` uses synthetic fixtures only; ``freeze`` and ``run`` are separate.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _resolve_exit  # noqa: E402
from src.backtest.application.runner import prepare_backtest_context  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE, CutoffMarketStore, common_maturity_mask, context_evidence, sha256,
)
from tools.research_contraction_learned_rank import (  # noqa: E402
    corrected_shape, metrics_bundle, phase_pass,
)
from tools.research_contraction_structure import Executor  # noqa: E402
from tools.research_double_yin_regime import (  # noqa: E402
    normalized_economic, price_precision, snapshot_factors,
)
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

DB = ROOT/".local/chinext-payoff-20261004/market.db"
OUTPUT = ROOT/"docs/research/2026-10-04-contraction-vwap"
ROOT_PLAN = ROOT/"docs/research/2026-10-04-vwap-study/PLAN.md"
SPLITS = {"train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}
CONTROLS = ("legacy_original", "corrected_original", "vwap_eligible_original")
POLICIES = ("vwap_gate_open", "vwap_gate_limit")
STRESS = "vwap_gate_limit_one_tick"
COMPARATORS = ("corrected_original", "vwap_eligible_original")


def sources() -> dict:
    paths = ["tools/research_contraction_vwap.py", "tools/research_contraction_learned_rank.py",
             "tools/research_contraction_structure.py", "tools/research_double_yin_regime.py",
             "tools/research_chinext_payoff_exits.py", "tools/research_impulse_scoring.py",
             "tools/strategy_chinext_review.py", "src/strategy/application/contraction_rebreakout.py",
             "src/backtest/application/runner.py", "src/backtest/application/engine.py",
             "src/backtest/application/execution_contract.py", "src/market/infrastructure/store_panel.py"]
    return {p: sha256(ROOT/p) for p in paths}


def vwap_quality(quote: dict | None) -> dict:
    """Use one stored TDX quote row, in yuan/share, never synthesized amount."""
    missing = dict(vwap_known=False, vwap_raw=np.nan, limit_cents=None)
    if quote is None:
        return {**missing, "vwap_reason": "missing_quote"}
    if quote["source"] != "tdx":
        return {**missing, "vwap_reason": "unverified_provider_units"}
    values = [quote.get(k) for k in ("amount", "volume", "low", "high")]
    if any(value is None for value in values) or not np.isfinite(values).all():
        return {**missing, "vwap_reason": "missing_amount_volume_range"}
    amount, volume, low, high = map(float, values)
    if min(amount, volume, low) <= 0 or high < low:
        return {**missing, "vwap_reason": "invalid_amount_volume_range"}
    value = amount/volume
    if not low-.01 <= value <= high+.01:
        return {**missing, "vwap_reason": "vwap_outside_raw_range"}
    # Decimal quotient of stored numbers avoids float*100 crossing a cent.
    cents = int((Decimal(str(amount))/Decimal(str(volume))*100).to_integral_value(rounding=ROUND_FLOOR))
    return dict(vwap_known=True, vwap_reason="known_tdx_yuan_per_share", vwap_raw=value, limit_cents=cents)


def prepare(start: str, end: str, db: Path = DB) -> dict:
    """T-close shapes and qualifications only; this function never labels returns."""
    store = CutoffMarketStore(db, end)
    try:
        engine = copy.copy(get("contraction-rebreakout-v1"))
        engine.requires_full_history = True
        ctx = prepare_backtest_context(store, engine, start=start, end=end,
            config=BASELINE.config(end), source_evidence_mode="compact")
        legacy = engine.compute(ctx["panels"], ctx["resolved_params"])
        raw = ctx["execution_panels"]
        factor = snapshot_factors(store, raw["close"])
        ctx["execution_panels"] = {**raw, "__adjust_factor": factor}
        economic = normalized_economic(raw, factor)
        corrected = corrected_shape(ctx, economic, factor)
        old = legacy.factors["条件候选"].fillna(False) & legacy.factors["score"].notna()
        candidate = corrected["candidates"]
        window = pd.Series((candidate.index >= start) & (candidate.index <= end), index=candidate.index)
        union = (candidate | old).where(window, False, axis=0)
        h5 = economic["high"].shift(1).rolling(5).max()
        records = []
        for row, col in zip(*np.nonzero(union.to_numpy())):
            date, code = str(candidate.index[row]), str(candidate.columns[col])
            quote = store.conn.execute("SELECT open,high,low,close,amount,volume,source FROM quotes_daily WHERE trade_date=? AND code=?", (date, code)).fetchone()
            quote = dict(quote) if quote else None
            q = vwap_quality(quote)
            if quote:
                for field in ("open", "high", "low", "close", "volume"):
                    actual = np.nan if quote[field] is None else float(quote[field])
                    if not np.isclose(actual, float(raw[field].iat[row, col]), atol=0, rtol=0, equal_nan=True):
                        raise AssertionError("Qualification quote differs from signal raw quote")
            vwap_economic = float(price_precision(pd.Series([q["vwap_raw"]*factor.iat[row, col]])).iloc[0])
            previous_high, close = float(h5.iat[row, col]), float(economic["close"].iat[row, col])
            gate = bool(q["vwap_known"] and previous_high < vwap_economic <= close)
            records.append(dict(signal_date=date, decision_date=date, code=code, row=int(row), col=int(col),
                corrected_candidate=bool(candidate.iat[row, col]), legacy_candidate=bool(old.iat[row, col]),
                legacy_selected=bool(legacy.signals.iat[row, col]), original_score=float(corrected["original_score"].iat[row, col]),
                legacy_score=float(legacy.factors["score"].iat[row, col]),
                signal_factor=float(factor.iat[row, col]), raw_close=float(raw["close"].iat[row, col]),
                h5_economic=previous_high, vwap_economic=vwap_economic, close_economic=close, vwap_gate=gate,
                raw_amount=quote["amount"] if quote else None, raw_volume=quote["volume"] if quote else None,
                quote_source=quote["source"] if quote else None, **q))
        columns = ["signal_date", "decision_date", "code", "row", "col", "corrected_candidate", "legacy_candidate",
            "legacy_selected", "original_score", "legacy_score", "signal_factor", "raw_close", "h5_economic",
            "vwap_economic", "close_economic", "vwap_gate", "raw_amount", "raw_volume", "quote_source",
            "vwap_known", "vwap_reason", "vwap_raw", "limit_cents"]
        frame = pd.DataFrame(records, columns=columns)
        mature = common_maturity_mask(raw["close"].index, start, end, max_hold=4)
        allowed = list(map(str, raw["close"].index[mature]))
        return dict(ctx=ctx, frame=frame, allowed=allowed, end=end, evidence=context_evidence(ctx))
    finally:
        store.close()


def select(frame: pd.DataFrame, arm: str) -> pd.DataFrame:
    if arm == "legacy_original":
        return frame[frame.legacy_selected].copy()
    eligible = frame.corrected_candidate.copy()
    if arm != "corrected_original":
        eligible &= frame.vwap_known
    if arm in (*POLICIES, STRESS):
        eligible &= frame.vwap_gate
    if arm not in (*CONTROLS, *POLICIES, STRESS):
        raise ValueError(arm)
    return frame[eligible].sort_values(["signal_date", "original_score", "code"], ascending=[True, False, True]).groupby("signal_date", sort=True).head(2).copy()


def limit_fill(opening: float, low: float, limit_cents: int, one_tick: bool) -> tuple[float | None, str]:
    limit = limit_cents/100
    if not np.isfinite(opening) or opening <= 0:
        return None, "unknown_or_invalid_open"
    if opening <= limit:
        return opening, "open_at_or_below_limit"
    if not np.isfinite(low) or low <= 0:
        return None, "unknown_or_invalid_low"
    threshold = (limit_cents-int(one_tick))/100
    return (limit, "intraday_limit_proxy") if low <= threshold else (None, "known_limit_not_reached")


def order_label(executor: Executor, event: dict, arm: str) -> dict:
    row, col = int(event["row"]), int(event["col"])
    entry = row+1
    record = {**event, "label_status": "unresolved", "label_reason": "entry_beyond_data",
              "label_available_date": None, "entry_date": None, "gross_return_pct": np.nan,
              "net_return_pct": np.nan, "entry_price": np.nan, "entry_factor": np.nan,
              "exit_date": None, "exit_price": np.nan, "exit_factor": np.nan, "exit_reason": None,
              "hold_days": np.nan, "entry_proxy_branch": None}
    def cancel(reason):
        record.update(label_status="cancelled", label_reason=reason, label_available_date=record["entry_date"], net_return_pct=0.)
        return record
    if entry >= len(executor.dates):
        return record
    day = str(executor.dates[entry])
    record["entry_date"] = day
    volume, opening = (float(executor.values[key][entry, col]) for key in ("volume", "open"))
    if np.isfinite(volume) and volume <= 0:
        return cancel("known_nonpositive_volume")
    if not np.isfinite(volume):
        record["label_reason"] = "unknown_volume"
        return record
    if not np.isfinite(opening) or opening <= 0:
        record["label_reason"] = "unknown_or_invalid_open"
        return record
    if not executor.known[entry, col]:
        record["label_reason"] = "unknown_limit_reference"
        return record
    if executor.blocked[entry, col]:
        return cancel("known_limit_up_open")
    entry_factor = float(executor.factor[entry, col])
    if arm in ("vwap_gate_limit", STRESS):
        if not np.isfinite(entry_factor) or entry_factor <= 0:
            record["label_reason"] = "unknown_entry_factor"
            return record
        if not np.isclose(entry_factor, event["signal_factor"], rtol=0, atol=1e-10):
            return cancel("overnight_factor_changed")
        fill, branch = limit_fill(opening, float(executor.values["low"][entry, col]), int(event["limit_cents"]), arm == STRESS)
        record["entry_proxy_branch"] = branch
        if fill is None:
            if branch == "known_limit_not_reached":
                return cancel(branch)
            record["label_reason"] = branch
            return record
    else:
        fill = opening
        record["entry_proxy_branch"] = "next_open"
    record.update(entry_price=float(fill), entry_factor=entry_factor)
    basis = fill*entry_factor
    cfg = BASELINE.config(executor.end)
    exit_row, price, reason = _resolve_exit(col=col, entry_idx=entry, entry_price=basis,
        planned_exit=entry+3, cfg=cfg, high_a=executor.ec["high"], low_a=executor.ec["low"],
        close_a=executor.ec["close"], open_a=executor.ec["open"], one_word_down=executor.down,
        volume_a=executor.values["volume"], last_index=len(executor.dates)-1)
    if exit_row is None or reason == "data_end" or not np.isfinite(price) or price <= 0:
        record["label_reason"] = "unresolved_exit_not_zero"
        return record
    # Daily engine skips missing bars. Distinguish missing from known suspension,
    # including a missing stop-trigger candle before an otherwise valid exit.
    for current in range(entry, exit_row+1):
        v = float(executor.values["volume"][current, col])
        values = [float(executor.values[k][current, col]) for k in ("open", "high", "low", "close")]
        o, h, low, c = values
        if (not np.isfinite(v) or (v > 0 and (not np.isfinite(values).all() or min(o, low, c) <= 0
                or h < max(o, c) or low > min(o, c) or not executor.known[current, col]))):
            record["label_reason"] = "unknown_or_invalid_holding_quote"
            return record
    if exit_row <= entry or str(executor.dates[exit_row]) > executor.end:
        raise AssertionError("Exit violates T+1 or phase cutoff")
    exit_factor = float(executor.factor[exit_row, col])
    raw_exit = float(price/exit_factor)
    for field in ("open", "close"):
        if price == executor.ec[field][exit_row, col]:
            raw_exit = float(executor.values[field][exit_row, col])
            break
    gross = float((price/basis-1)*100)
    record.update(label_status="closed", label_reason="closed", label_available_date=str(executor.dates[exit_row]),
        gross_return_pct=gross, net_return_pct=gross-.21, exit_date=str(executor.dates[exit_row]),
        exit_price=raw_exit, exit_factor=exit_factor, exit_reason=reason, hold_days=exit_row-entry)
    return record


def summarize(orders: pd.DataFrame, allowed: list[str], arm: str, segment: str) -> tuple[dict, pd.DataFrame]:
    closed = orders[orders.label_status.eq("closed")]
    totals = closed.groupby("signal_date").net_return_pct.sum()
    unknown = set(orders.loc[orders.label_status.eq("unresolved"), "signal_date"])
    daily = pd.DataFrame([dict(segment=segment, variant=arm, signal_date=d, opportunities=2,
        net_sum=np.nan if d in unknown else float(totals.get(d, 0.))) for d in allowed])
    return dict(metrics=metrics_bundle(orders, len(allowed)*2),
        active_entry_months=int(closed.entry_date.str[:7].nunique()) if len(closed) else 0,
        statuses=orders.label_reason.value_counts().to_dict()), daily


def paired_mechanism(orders: dict) -> pd.DataFrame | None:
    if not all(arm in orders for arm in POLICIES):
        return None
    columns = ["signal_date", "code", "label_status", "label_reason", "entry_price", "net_return_pct"]
    a, b = (orders[arm][columns] for arm in POLICIES)
    merged = a.merge(b, on=["signal_date", "code"], suffixes=("_open", "_limit"), validate="one_to_one")
    if len(a) != len(b) or len(merged) != len(a):
        raise AssertionError("A and B preselected keys differ")
    merged["limit_minus_open_net_pct"] = merged.net_return_pct_limit-merged.net_return_pct_open
    return merged


def evaluate(segment: str, policies: list[str], output: Path) -> tuple[dict, dict, pd.DataFrame]:
    destination = output/segment
    if destination.exists():
        raise FileExistsError("Preserve prior phase artifacts")
    destination.mkdir()
    prepared = prepare(*SPLITS[segment])
    allowed = prepared["allowed"]
    frame = prepared["frame"]
    frame.to_csv(destination/"all-candidate-qualifications.csv", index=False)
    frame = frame[frame.signal_date.isin(allowed)].copy()
    arms = [*CONTROLS, *policies]
    if "vwap_gate_limit" in policies:
        if "vwap_gate_open" not in arms:
            arms.append("vwap_gate_open")  # Mechanism control, never re-nominated.
        arms.append(STRESS)
    selections = {arm: select(frame, arm) for arm in arms}
    for arm, selected in selections.items():
        selected.to_csv(destination/f"{arm}-preselected.csv", index=False)
    if "vwap_gate_limit" in arms:
        for arm in ("vwap_gate_open", STRESS):
            if list(selections[arm][["signal_date", "code"]].itertuples(index=False, name=None)) != list(selections["vwap_gate_limit"][["signal_date", "code"]].itertuples(index=False, name=None)):
                raise AssertionError("Entry variants must use the identical frozen list")
    write_json(destination/"selection-receipt.json", dict(created_at=now(), returns_not_yet_evaluated=True,
        common_days=len(allowed), common_slots=2*len(allowed), first=allowed[0], last=allowed[-1],
        nominations=policies, preselected_sha256={a: sha256(destination/f"{a}-preselected.csv") for a in arms}))
    executor = Executor(prepared["ctx"], prepared["end"])
    runs, byarm, dailies = {}, {}, []
    for arm, selected in selections.items():
        items = [order_label(executor, event, arm) for event in selected.to_dict("records")]
        if items:
            orders = pd.DataFrame(items)
        else:
            orders = pd.DataFrame(columns=[*selected.columns, "label_status", "label_reason", "label_available_date",
                "entry_date", "exit_date", "entry_price", "gross_return_pct", "net_return_pct"])
        orders.to_csv(destination/f"{arm}-orders.csv", index=False)
        orders[orders.label_status.eq("closed")].to_csv(destination/f"{arm}-trades.csv", index=False)
        result, daily = summarize(orders, allowed, arm, segment)
        runs[arm], byarm[arm] = result, orders
        dailies.append(daily)
        print(segment, arm, json.dumps(result["metrics"]["base"]), flush=True)
    base = next(d for d in dailies if d.variant.iloc[0] == "corrected_original").set_index("signal_date").net_sum
    for daily in dailies:
        daily["base_net_sum"] = daily.signal_date.map(base)
        daily["delta_net_sum"] = daily.net_sum-daily.base_net_sum
        arm = str(daily.variant.iloc[0])
        runs[arm]["paired_month_bootstrap"] = paired_bootstrap(daily) if np.isfinite(daily.delta_net_sum).all() else None
    paired = paired_mechanism(byarm)
    if paired is not None:
        paired.to_csv(destination/"same-order-A-versus-B.csv", index=False)
    result = dict(context=prepared["evidence"], common_market_days=len(allowed), common_slots=2*len(allowed),
        nominees_evaluated=policies, mechanism_only=[a for a in POLICIES if a in arms and a not in policies],
        candidate_counts=dict(full_corrected=int(frame.corrected_candidate.sum()), vwap_known=int((frame.corrected_candidate & frame.vwap_known).sum()),
            gate=int((frame.corrected_candidate & frame.vwap_gate).sum())), runs=runs)
    write_json(destination/"summary.json", result)
    joined = pd.concat(dailies, ignore_index=True)
    joined.to_csv(destination/"daily-budget.csv", index=False)
    return result, byarm, joined


def positive_stress(result: dict) -> bool:
    m = result["runs"][STRESS]["metrics"]["base"]
    return bool(m["unresolved"] == 0 and m["avg_net_return"] is not None and m["avg_net_return"] > 0)


def freeze(output: Path):
    if (output/"PLAN.json").exists():
        raise FileExistsError("Preserve frozen plan")
    plan = dict(created_at=now(), sources=sources(), snapshot_sha256=sha256(DB),
        root_plan_sha256=sha256(ROOT_PLAN), contract_sha256=sha256(output/"PLAN.md"), splits=SPLITS,
        controls=CONTROLS, policies=POLICIES, stress=STRESS, shared_contract="PLAN.md and root VWAP PLAN.md; exact hashes above",
        no_2023h2_outcomes=True, current_catalog_and_revised_factors_not_PIT=True,
        independent_event_budget_not_capital_NAV=True)
    write_json(output/"PLAN.json", plan)
    write_json(output/"freeze-receipt.json", dict(created_at=now(), plan_sha256=sha256(output/"PLAN.json")))
    print(json.dumps(dict(frozen=True, plan_sha256=sha256(output/"PLAN.json"))), flush=True)


def verify_frozen(plan: dict, output: Path):
    if (sources() != plan["sources"] or sha256(DB) != plan["snapshot_sha256"]
            or sha256(ROOT_PLAN) != plan["root_plan_sha256"] or sha256(output/"PLAN.md") != plan["contract_sha256"]):
        raise AssertionError("Frozen source, data or contract changed")


def run(output: Path):
    plan = json.loads((output/"PLAN.json").read_text(encoding="utf-8"))
    verify_frozen(plan, output)
    train, _, _ = evaluate("train", list(POLICIES), output)
    controls = {c: train["runs"][c] for c in COMPARATORS}
    nominees = [p for p in POLICIES if phase_pass(train["runs"][p], controls, 20, 6, True)
                and (p != "vwap_gate_limit" or positive_stress(train))]
    write_json(output/"training-nomination.json", dict(created_at=now(), nominees=nominees, no_diagnostic_fallback=True,
        train_summary_sha256=sha256(output/"train/summary.json"), later_returns_not_yet_evaluated=True))
    result = dict(train=train, nominees=nominees, later_not_evaluated=not nominees, plan_sha256=sha256(output/"PLAN.json"))
    if nominees:
        stages, pooled, budgets = {}, {}, 0
        for segment in ("validation_2025h2", "observed_2026"):
            verify_frozen(plan, output)
            stages[segment], orders, _ = evaluate(segment, nominees, output)
            budgets += stages[segment]["common_slots"]
            for arm, frame in orders.items():
                pooled.setdefault(arm, []).append(frame)
        result["later"] = stages
        result["pooled_later"] = {a: metrics_bundle(pd.concat(frames, ignore_index=True), budgets) for a, frames in pooled.items()}
        result["statistical_pass"] = {}
        for arm in nominees:
            passes = all(phase_pass(s["runs"][arm], {c: s["runs"][c] for c in COMPARATORS}, 12, 4, False)
                and (arm != "vwap_gate_limit" or positive_stress(s)) for s in stages.values())
            metrics = result["pooled_later"][arm]
            combined = metrics["double_cost_winner_removed"]["avg_net_return"]
            passes &= metrics["base"]["trades"] >= 40 and metrics["base"]["unresolved"] == 0 and combined is not None and combined > 0
            result["statistical_pass"][arm] = bool(passes)
    verify_frozen(plan, output)
    result.update(completed_at=now(), sources_and_snapshot_unchanged=True, no_2023h2_outcomes=True,
        capital_validation_not_performed=True)
    write_json(output/"summary.json", result)
    print(json.dumps(dict(nominees=nominees, later_not_evaluated=not nominees)), flush=True)


def self_check() -> dict:
    q = dict(source="tdx", amount=250., volume=20., low=12., high=13.)
    assert vwap_quality(q)["limit_cents"] == 1250
    assert vwap_quality({**q, "amount": 250.199})["limit_cents"] == 1250
    assert not vwap_quality({**q, "source": "tencent"})["vwap_known"]
    assert not vwap_quality({**q, "volume": None})["vwap_known"]
    assert not vwap_quality({**q, "amount": 300.})["vwap_known"]
    assert limit_fill(12.5, np.nan, 1250, True) == (12.5, "open_at_or_below_limit")
    assert limit_fill(12.6, 12.5, 1250, False) == (12.5, "intraday_limit_proxy")
    assert limit_fill(12.6, 12.5, 1250, True)[1] == "known_limit_not_reached"
    assert limit_fill(12.6, 12.49, 1250, True) == (12.5, "intraday_limit_proxy")
    assert limit_fill(12.6, np.nan, 1250, True)[1] == "unknown_or_invalid_low"
    frame = pd.DataFrame([dict(signal_date="2024-01-02", decision_date="2024-01-02", code=code,
        legacy_selected=i < 2, corrected_candidate=True, vwap_known=True, vwap_gate=True, original_score=score)
        for i, (code, score) in enumerate((("300003", 90.), ("300001", 90.), ("300002", 80.)))])
    selected = select(frame, "vwap_gate_open")
    assert selected.code.tolist() == ["300001", "300003"]
    pd.testing.assert_frame_equal(selected, select(frame, "vwap_gate_limit"))
    # A preselected unknown does not admit the third-ranked name or a zero label.
    dates = pd.Index([f"2024-01-{d:02d}" for d in range(2, 10)])
    raw = {k: pd.DataFrame(10., index=dates, columns=["300001"]) for k in ("open", "high", "low", "close")}
    raw.update(volume=pd.DataFrame(100., index=dates, columns=["300001"]),
               __adjust_factor=pd.DataFrame(1., index=dates, columns=["300001"]))
    executor = Executor(dict(execution_panels=raw), str(dates[-1]))
    executor.factor = executor.factor.copy()
    executor.values = {key: value.copy() for key, value in executor.values.items()}
    event = dict(signal_date=str(dates[1]), decision_date=str(dates[1]), code="300001", row=1, col=0,
                 signal_factor=1., limit_cents=1000)
    normal = order_label(executor, event, "vwap_gate_open")
    assert normal["label_status"] == "closed" and normal["exit_date"] == dates[5]
    assert normal["net_return_pct"] == -.21
    executor.factor[2, 0] = 1.1
    assert order_label(executor, event, "vwap_gate_limit")["label_reason"] == "overnight_factor_changed"
    executor.factor[2, 0] = 1.
    executor.values["volume"][2, 0] = np.nan
    missing = order_label(executor, event, "vwap_gate_open")
    assert missing["label_status"] == "unresolved" and np.isnan(missing["net_return_pct"])
    executor.values["volume"][2, 0] = 0.
    assert order_label(executor, event, "vwap_gate_open")["label_status"] == "cancelled"
    executor.values["volume"][2, 0] = 100.
    executor.values["volume"][3, 0] = np.nan
    assert order_label(executor, event, "vwap_gate_open")["label_reason"] == "unknown_or_invalid_holding_quote"
    m = metrics_bundle(pd.DataFrame([normal, missing]), 10)
    assert m["base"]["common_slot_mean"] is None and m["base"]["unresolved"] == 1
    return dict(passed=True, synthetic_only=True, checks=["TDX units and missing/range exclusion", "decimal cent floor",
        "open branch independent of tick-through", "intraday touch vs tick-through", "stable Top2/code tie",
        "A/B identical names", "strictT+1/4sessions", "factor-change cancellation", "unknown not zero",
        "known suspension zero", "unknown holding quote prevents false closed return", "unknown blocks calendar metrics"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("self-check", "freeze", "run"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "self-check":
        print(json.dumps(self_check()))
    elif args.action == "freeze":
        freeze(args.output.resolve(strict=True))
    else:
        run(args.output.resolve(strict=True))


if __name__ == "__main__":
    main()
