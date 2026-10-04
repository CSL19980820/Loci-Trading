"""One frozen fixed-order opening-gap sensitivity; never modify source results."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import research_exit_mask_incidence as incidence  # noqa: E402

RESEARCH = ROOT / "docs/research/2026-10-04-exit-causality"
OUTPUT = RESEARCH / "sensitivity"
PLAN_HASH = "343cfa43cbd4ba804116458389a0e73140670ee907b1d291addd4b16e426dce6"
KEYS = ["group_id", "signal_date", "code"]
VALUE_FIELDS = ["entry_date", "entry_price", "entry_factor", "exit_date", "exit_price", "exit_factor",
                "exit_reason", "hold_days", "gross_return_pct", "net_return_pct"]


def csv(path, **kwargs):
    return pd.read_csv(path, dtype={"code": str}, float_precision="round_trip", **kwargs)


def write_csv(path, data):
    with path.open("x", encoding="utf-8", newline="") as handle:
        data.to_csv(handle, index=False)


def group_id(spec):
    return f"{spec['family']}/{spec['segment']}/{spec['policy']}"


def group_specs():
    result = []
    for spec in incidence.SPECS:
        item = dict(spec, group_id=group_id(spec))
        path = ROOT / spec["path"]
        if spec["kind"] == "labels":
            item.update(trades=path.with_name(path.name.replace("-labels.csv", "-trades.csv")).relative_to(ROOT).as_posix(),
                        summary=(incidence.YIN / f"{spec['segment']}-summary.json").relative_to(ROOT).as_posix(),
                        budget=(incidence.YIN / f"{spec['segment']}-paired-calendar.csv").relative_to(ROOT).as_posix(),
                        budget_column="comparison", budget_value=f"{spec['policy']}_vs_original_open")
        else:
            item.update(trades=None, summary=(path.parent / "summary.json").relative_to(ROOT).as_posix(),
                        budget=(path.parent / "daily-budget.csv").relative_to(ROOT).as_posix(),
                        budget_column="variant", budget_value=spec["policy"])
        result.append(item)
    return result


def protected():
    paths = {Path(__file__), RESEARCH / "SENSITIVITY-PLAN.md", RESEARCH / "sensitivity-contract-freeze.json",
             RESEARCH / "review/verification.json", RESEARCH / "review/verify_incidence.py"}
    root_receipt = incidence.read(RESEARCH / "sensitivity-contract-freeze.json")
    for name, expected in root_receipt["sha256"].items():
        assert incidence.sha(RESEARCH / name) == expected
        paths.add(RESEARCH / name)
    assert incidence.sha(RESEARCH / "SENSITIVITY-PLAN.md") == PLAN_HASH
    plan = incidence.verify(incidence.OUTPUT)
    paths.update(ROOT / name for name in plan["files_sha256"])
    completion = incidence.read(incidence.OUTPUT / "completion-receipt.json")
    assert completion["plan_sha256"] == incidence.sha(incidence.OUTPUT / "PLAN.json")
    for name, expected in completion["artifacts_sha256"].items():
        assert incidence.sha(incidence.OUTPUT / name) == expected
    paths.update(p for p in incidence.OUTPUT.iterdir() if p.is_file() and p.name in {
        "PLAN.md", "PLAN.json", "freeze-receipt.json", "completion-receipt.json", "all-orders-incidence.csv",
        "stop-window-ledger.csv", "summary.json"})
    paths.add(ROOT / "tools/research_contraction_learned_rank.py")
    for spec in group_specs():
        paths.update(ROOT / spec[name] for name in ("path", "summary", "budget"))
        if spec["trades"]:
            paths.add(ROOT / spec["trades"])
    return {p.relative_to(ROOT).as_posix(): incidence.sha(p) for p in sorted(paths)}


def valid_bar(day):
    o, h, low, c = (day.get(k) for k in ("open", "high", "low", "close"))
    return (all(incidence.positive(v) for v in (o, h, low, c, day.get("volume"), day.get("factor")))
            and h >= max(o, c) and low <= min(o, c) and bool(day.get("reference_known")))


def narrow_eligible(order, trigger, prefix_complete):
    return bool(prefix_complete and order["source_label_status"] == "closed"
        and order["source_exit_reason"] == "stop_loss"
        and order["source_exit_date"] > trigger["trade_date"] > order["entry_date"]
        and trigger["offset_after_entry"] in (1, 2, 3) and valid_bar(trigger)
        and trigger["low"]*trigger["factor"] <= order["stop_economic"]
        and trigger["open"]*trigger["factor"] <= order["stop_economic"]
        and trigger["open"] > trigger["lower_limit_raw"]+.005
        and trigger["close"] <= trigger["lower_limit_raw"]+.005)


def replacement(order, trigger):
    result = dict(order)
    result.update(exit_date=trigger["trade_date"], exit_price=trigger["open"], exit_factor=trigger["factor"],
                  hold_days=trigger["offset_after_entry"], exit_reason="stop_loss")
    result["gross_return_pct"] = (result["exit_price"]*result["exit_factor"]/(result["entry_price"]*result["entry_factor"])-1)*100
    result["net_return_pct"] = result["gross_return_pct"]-.21
    return result


def eligible_facts():
    """No source outcome values or hypothetical return calculations in this step."""
    all_rows = csv(incidence.OUTPUT / "all-orders-incidence.csv")
    mask = (all_rows.incidence_status.eq("first_stop_trigger_known")
            & all_rows.trigger_mask_evidence.eq("close_at_lower_masked")
            & all_rows.trigger_open_at_or_below_stop.eq(True)
            & all_rows.trigger_open_relative_lower.eq("above_lower"))
    selected = all_rows[mask].copy().sort_values(KEYS)
    assert len(selected) == 12 and not selected.duplicated(KEYS).any()
    assert selected.source_label_status.eq("closed").all()
    records, ledger = [], []
    for db, group in selected.groupby("db", sort=True):
        market = incidence.Market(db, set(group.code))
        try:
            for order in group.to_dict("records"):
                panel = market.panels[order["code"]]
                entry = market.indices[order["entry_date"]]
                assert valid_bar(panel[entry]), "Selected entry's raw/factor/limit reference must be complete"
                assert np.isclose(panel[entry]["factor"], order["entry_factor"], rtol=0, atol=1e-12)
                stop = order["entry_price"]*panel[entry]["factor"]*.94
                assert stop == order["stop_economic"]
                prefix_complete = True
                first = None
                entry_ledger = {**{k: order[k] for k in KEYS}, **panel[entry], "offset_after_entry": 0,
                                "role": "entry_bar_and_factor_validation"}
                ledger.append(entry_ledger)
                for offset in (1, 2, 3):
                    day = panel[entry+offset]
                    assert day["trade_date"] <= incidence.SPLITS[order["segment"]][1]
                    row = {**day, "offset_after_entry": offset}
                    if incidence.finite(day["volume"]) and day["volume"] == 0:
                        # Preserve the established known-no-trading status, never trigger on stale prices.
                        state = "known_no_trading_skipped"
                    elif not valid_bar(day):
                        prefix_complete = False
                        state = "incomplete_prior_path"
                    elif day["low"]*day["factor"] <= stop:
                        first, state = row, "first_known_stop_trigger"
                    else:
                        state = "known_bar_without_stop_trigger"
                    ledger.append({**{k: order[k] for k in KEYS}, **row, "role": state})
                    if first is not None:
                        break
                assert first is not None and prefix_complete
                assert first["trade_date"] == order["trigger_trade_date"]
                assert narrow_eligible(order, first, prefix_complete), "No silent exclusion of a frozen incidence candidate"
                for key in ("open", "high", "low", "close", "volume", "factor", "lower_limit_raw"):
                    assert first[key] == order[f"trigger_{key}"]
                records.append({**{k: order[k] for k in all_rows.columns if not k.startswith("trigger_")},
                                **{f"trigger_{k}": v for k, v in first.items()}, "full_prior_path_validated": True})
        finally:
            market.close()
    return pd.DataFrame(records).sort_values(KEYS), pd.DataFrame(ledger).sort_values([*KEYS, "offset_after_entry"])


def freeze():
    before = protected()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT / "freeze-receipt.json").exists():
        raise FileExistsError("Preserve original freeze")
    checks = self_check()
    selected, ledger = eligible_facts()
    # Header-only schema inspection; selected facts come from the outcome-excluding incidence reader.
    schemas = {}
    for spec in group_specs():
        schemas[spec["group_id"]] = {"source_columns": csv(ROOT / spec["path"], nrows=0).columns.tolist(),
                                    "trade_columns": csv(ROOT / spec["trades"], nrows=0).columns.tolist() if spec["trades"] else None}
    write_csv(OUTPUT / "eligible-orders.csv", selected)
    write_csv(OUTPUT / "sql-validation.csv", ledger)
    incidence.write_new(OUTPUT / "schema-manifest.json", dict(groups=group_specs(), schemas=schemas))
    assert before == protected()
    receipt = dict(created_at=incidence.now(), plan_sha256=PLAN_HASH, files_sha256=before,
        databases_sha256={k: incidence.sha(p) for k, p in incidence.DBS.items()},
        derived_pre_return_sha256={p.name: incidence.sha(p) for p in OUTPUT.iterdir() if p.is_file()},
        groups=group_specs(), all_eligible_orders=len(selected), group_counts=selected.group_id.value_counts().to_dict(),
        real_alternative_returns_computed=False, real_alternative_returns_read=False, self_check=checks)
    incidence.write_new(OUTPUT / "freeze-receipt.json", receipt)
    print(incidence.clean(dict(frozen=True, eligible=len(selected), groups=11, receipt_sha256=incidence.sha(OUTPUT / "freeze-receipt.json"))))


def verify():
    receipt = incidence.read(OUTPUT / "freeze-receipt.json")
    assert receipt["plan_sha256"] == PLAN_HASH and receipt["files_sha256"] == protected()
    assert receipt["databases_sha256"] == {k: incidence.sha(p) for k, p in incidence.DBS.items()}
    assert all(incidence.sha(OUTPUT / n) == h for n, h in receipt["derived_pre_return_sha256"].items())
    return receipt


def source_group(spec):
    source = csv(ROOT / spec["path"])
    if spec["kind"] == "labels":
        labels = source.rename(columns={"decision_date": "signal_date", "execution_reason": "label_reason"})
        trades = csv(ROOT / spec["trades"])
        fields = ["signal_date", "code", *VALUE_FIELDS]
        source = labels[["signal_date", "code", "label_status", "label_reason"]].merge(
            trades[fields], on=["signal_date", "code"], how="left", validate="one_to_one")
        assert (source.label_status.eq("closed") == source.gross_return_pct.notna()).all()
        source.loc[source.label_status.eq("cancelled"), "net_return_pct"] = 0.
        assert np.allclose(source.net_return_pct, labels.net_return_pct, equal_nan=True, atol=1e-10, rtol=1e-11)
    source = source[["signal_date", "code", "label_status", "label_reason", *VALUE_FIELDS]].copy()
    source["group_id"] = spec["group_id"]
    source = source[[*KEYS, "label_status", "label_reason", *VALUE_FIELDS]].reset_index(drop=True)
    assert not source.duplicated(KEYS).any() and source.label_status.isin(["closed", "cancelled", "unresolved"]).all()
    assert source[source.label_status.eq("unresolved")].net_return_pct.isna().all()
    assert source[source.label_status.eq("cancelled")].net_return_pct.eq(0).all()
    closed = source[source.label_status.eq("closed")]
    direct = (closed.exit_price*closed.exit_factor/(closed.entry_price*closed.entry_factor)-1)*100
    assert np.allclose(direct, closed.gross_return_pct, rtol=1e-11, atol=1e-8)
    assert np.allclose(closed.gross_return_pct-.21, closed.net_return_pct, rtol=1e-11, atol=1e-10)
    return source


def summarize(orders, slots, complete):
    closed = orders[orders.label_status.eq("closed")]
    values = closed.net_return_pct.to_numpy(float)
    winner = int(np.argmax(values)) if len(values) else None
    reduced = np.delete(values, winner) if winner is not None else values
    result = {}
    for mode, array in (("base", values), ("double_cost", values-.21),
                        ("winner_removed", reduced), ("double_cost_winner_removed", reduced-.21)):
        positive, negative = array[array > 0], array[array < 0]
        result[mode] = dict(trades=len(array), avg_net_return=float(array.mean()) if len(array) else None,
            profit_factor=float(positive.sum()/-negative.sum()) if negative.sum() < 0 else None,
            win_rate=float((array > 0).mean()*100) if len(array) else None,
            positive_net_sum=float(positive.sum()), negative_net_sum=float(negative.sum()),
            known_closed_net_sum=float(array.sum()), net_sum=float(array.sum()) if complete else None,
            common_slot_mean=float(array.sum()/slots) if complete else None)
    result["largest_winner_key"] = {k: closed.iloc[winner][k] for k in KEYS} if winner is not None else None
    return result


def run():
    receipt = verify()
    if (OUTPUT / "summary.json").exists():
        raise FileExistsError("Preserve completed sensitivity")
    selected = csv(OUTPUT / "eligible-orders.csv")
    original_incidence = csv(incidence.OUTPUT / "all-orders-incidence.csv")
    groups, changes, old_frames, new_frames, daily_frames = {}, [], [], [], []
    for spec in receipt["groups"]:
        original = source_group(spec)
        revised = original.copy()
        incidence_keys = original_incidence[original_incidence.group_id.eq(spec["group_id"])][KEYS]
        assert set(map(tuple, original[KEYS].to_numpy())) == set(map(tuple, incidence_keys.to_numpy()))
        matching = selected[selected.group_id.eq(spec["group_id"])]
        for facts in matching.to_dict("records"):
            positions = original.index[original.signal_date.eq(facts["signal_date"]) & original.code.eq(facts["code"])]
            assert len(positions) == 1
            idx = positions[0]
            old = original.loc[idx].to_dict()
            assert old["label_status"] == "closed" and old["exit_reason"] == "stop_loss"
            assert old["exit_date"] == facts["source_exit_date"] and old["exit_date"] > facts["trigger_trade_date"]
            assert old["entry_date"] == facts["entry_date"] and old["entry_price"] == facts["entry_price"]
            assert old["entry_factor"] == facts["entry_factor_direct"]
            trigger = {k.removeprefix("trigger_"): v for k, v in facts.items() if k.startswith("trigger_")}
            assert narrow_eligible(facts, trigger, bool(facts["full_prior_path_validated"]))
            new = replacement(old, trigger)
            for field in VALUE_FIELDS:
                revised.at[idx, field] = new[field]
            changes.append({**{k: old[k] for k in KEYS}, "entry_date": old["entry_date"],
                "entry_price_raw": old["entry_price"], "entry_factor": old["entry_factor"],
                "stop_economic": facts["stop_economic"], "trigger_lower_limit_raw": trigger["lower_limit_raw"],
                **{f"old_{k}": old[k] for k in VALUE_FIELDS if not k.startswith("entry_")},
                **{f"new_{k}": new[k] for k in VALUE_FIELDS if not k.startswith("entry_")},
                "delta_gross_return_pct": new["gross_return_pct"]-old["gross_return_pct"],
                "delta_net_return_pct": new["net_return_pct"]-old["net_return_pct"]})
        changed_mask = original.signal_date.astype(str)+"/"+original.code
        selected_keys = set(matching.signal_date.astype(str)+"/"+matching.code)
        unaffected = ~changed_mask.isin(selected_keys)
        pd.testing.assert_frame_equal(original.loc[unaffected], revised.loc[unaffected])
        pd.testing.assert_frame_equal(original[[*KEYS, "label_status", "label_reason", "entry_date", "entry_price", "entry_factor"]],
                                      revised[[*KEYS, "label_status", "label_reason", "entry_date", "entry_price", "entry_factor"]])
        daily = csv(ROOT / spec["budget"])
        daily = daily[daily[spec["budget_column"]].eq(spec["budget_value"])].copy()
        assert not daily.signal_date.duplicated().any() and daily.opportunities.eq(2).all()
        assert set(original.signal_date).issubset(set(daily.signal_date))
        slots = int(daily.opportunities.sum())
        for frame in (original, revised):
            assert frame[frame.label_status.eq("closed")].exit_date.gt(frame[frame.label_status.eq("closed")].entry_date).all()
        unknown = int(original.label_status.eq("unresolved").sum())
        complete = not unknown and not daily.net_sum.isna().any()
        old_totals = original[original.label_status.eq("closed")].groupby("signal_date").net_return_pct.sum()
        expected_old = daily.signal_date.map(old_totals).fillna(0.)
        known_days = daily.net_sum.notna()
        assert np.allclose(daily.loc[known_days, "net_sum"], expected_old[known_days], rtol=1e-11, atol=1e-9)
        delta = revised.net_return_pct-original.net_return_pct
        byday = delta.groupby(original.signal_date).sum(min_count=1)
        daily["old_net_sum"] = daily.net_sum
        daily["delta_net_sum"] = daily.signal_date.map(byday).fillna(0.)
        daily["new_net_sum"] = daily.old_net_sum+daily.delta_net_sum
        daily.loc[daily.old_net_sum.isna(), ["new_net_sum", "delta_net_sum"]] = np.nan
        daily["group_id"] = spec["group_id"]
        old_metrics, new_metrics = summarize(original, slots, complete), summarize(revised, slots, complete)
        source_run = incidence.read(ROOT / spec["summary"])["runs"][spec["policy"]]
        for name in ("avg_net_return", "profit_factor", "win_rate"):
            expected = source_run["metrics"]["base"][name]
            actual = old_metrics["base"][name]
            assert (expected is None and actual is None) or np.isclose(actual, expected, rtol=1e-10, atol=1e-9)
        for mode, source_mode in (("double_cost", "double_cost"), ("winner_removed", "largest_winner_removed" if spec["kind"] == "labels" else "winner_removed"),
                                  ("double_cost_winner_removed", "double_cost_largest_winner_removed" if spec["kind"] == "labels" else "double_cost_winner_removed")):
            assert np.isclose(old_metrics[mode]["avg_net_return"], source_run["metrics"][source_mode]["avg_net_return"], atol=1e-9, rtol=1e-10)
        expected_slot = source_run["slot_mean"] if spec["kind"] == "labels" else source_run["metrics"]["base"]["common_slot_mean"]
        assert (expected_slot is None and old_metrics["base"]["common_slot_mean"] is None) or np.isclose(expected_slot, old_metrics["base"]["common_slot_mean"], atol=1e-9, rtol=1e-10)
        if complete:
            assert np.isclose(daily.new_net_sum.sum()/slots, new_metrics["base"]["common_slot_mean"], atol=1e-9, rtol=1e-10)
        groups[spec["group_id"]] = dict(orders=len(original), statuses=dict(Counter(original.label_status)),
            changed_orders=len(matching), unchanged_orders=int(unaffected.sum()), common_market_days=len(daily), common_slots=slots,
            unresolved_preserved=unknown, complete_opportunity_statistics=complete, old=old_metrics, new=new_metrics,
            known_changed_order_delta_sum=float(delta.dropna().sum()), fixed_order_sensitivity_not_strategy_reexecution=True)
        old_frames.append(original)
        new_frames.append(revised.assign(sensitivity_changed=~unaffected))
        daily_frames.append(daily[["group_id", "signal_date", "opportunities", "old_net_sum", "new_net_sum", "delta_net_sum"]])
    assert len(changes) == 12 and len(groups) == 11
    write_csv(OUTPUT / "changed-orders.csv", pd.DataFrame(changes).sort_values(KEYS))
    write_csv(OUTPUT / "all-orders-old.csv", pd.concat(old_frames, ignore_index=True))
    write_csv(OUTPUT / "all-orders-new.csv", pd.concat(new_frames, ignore_index=True))
    write_csv(OUTPUT / "daily-budget.csv", pd.concat(daily_frames, ignore_index=True))
    verify()
    incidence.write_new(OUTPUT / "summary.json", dict(completed_at=incidence.now(), groups=groups,
        changed_policy_orders=12, fixed_policy_groups=11, unknown_labels_unchanged=True,
        original_strict_failures_unchanged=True, no_new_nomination=True, real_execution_not_proven=True,
        current_script_sha256=incidence.sha(Path(__file__)), freeze_receipt_sha256=incidence.sha(OUTPUT / "freeze-receipt.json")))
    incidence.write_new(OUTPUT / "completion-receipt.json", dict(completed_at=incidence.now(),
        artifacts_sha256={p.name: incidence.sha(p) for p in OUTPUT.iterdir() if p.is_file()}, protected_sources_unchanged=True))
    print(dict(completed=True, groups=11, changed_orders=12, original_strict_failures_unchanged=True))


def self_check():
    old = dict(source_label_status="closed", source_exit_reason="stop_loss", source_exit_date="2024-01-04",
        entry_date="2024-01-02", entry_price=10., entry_factor=1., stop_economic=9.4,
        exit_date="2024-01-04", exit_price=9.6, exit_factor=1., exit_reason="stop_loss", hold_days=2)
    day = dict(trade_date="2024-01-03", offset_after_entry=1, open=9.3, high=9.8, low=9., close=9.,
               volume=100., factor=1., reference_known=True, lower_limit_raw=9.)
    assert narrow_eligible(old, day, True)
    changed = replacement(old, day)
    assert changed["exit_date"] == day["trade_date"] and changed["exit_price"] == 9.3
    assert replacement(old, {**day, "close": 9.2})["exit_price"] == changed["exit_price"]
    assert changed["hold_days"] == 1 and changed["entry_price"] == old["entry_price"]
    for field, value in (("open", 9.), ("volume", 0.), ("reference_known", False), ("factor", np.nan),
                          ("high", np.nan), ("offset_after_entry", 0), ("close", 9.2)):
        assert not narrow_eligible(old, {**day, field: value}, True)
    assert not narrow_eligible(old, day, False)
    assert not narrow_eligible({**old, "source_exit_reason": "hold_expired"}, day, True)
    assert not narrow_eligible({**old, "source_label_status": "unresolved"}, day, True)
    assert not narrow_eligible(old, {**day, "open": 9.8}, True)
    assert np.isclose(changed["gross_return_pct"]-.21, changed["net_return_pct"])
    uncertain = pd.DataFrame([dict(group_id="s", signal_date="d", code="a", label_status="closed", net_return_pct=-1.),
                              dict(group_id="s", signal_date="d", code="b", label_status="unresolved", net_return_pct=np.nan)])
    result = summarize(uncertain, 10, False)
    assert result["base"]["common_slot_mean"] is None and result["base"]["net_sum"] is None
    return dict(passed=True, synthetic_only=True, checks=["opening_gap_only", "late_close_cannot_change_open_price",
        "T_plus_1", "limit_open_blocked", "halt_blocked", "unknown_reference_factor_bar_blocked", "incomplete_prefix_blocked",
        "expiry_unchanged", "unresolved_not_promoted", "intraday_only_unchanged", "cost_identity", "unknown_full_budget_null"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("self-check", "freeze", "run", "verify"))
    args = parser.parse_args()
    if args.phase == "self-check":
        print(self_check())
    elif args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        run()
    else:
        verify()
        print("All source and frozen fact hashes match")
