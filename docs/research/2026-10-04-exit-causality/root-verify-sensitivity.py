"""Independent source, SQL, and arithmetic verification; no experiment imports."""
from pathlib import Path
import hashlib
import json
import sqlite3

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / "sensitivity"
KEY = ["group_id", "signal_date", "code"]
CHANGED = ["exit_date", "exit_price", "exit_factor", "hold_days", "exit_reason", "gross_return_pct", "net_return_pct"]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def table(path):
    return pd.read_csv(path, dtype={"code": str}, float_precision="round_trip")


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def same(a, b):
    if a is None:
        assert b is None, (a, b)
    else:
        assert np.isclose(a, b, rtol=1e-10, atol=1e-9), (a, b)


def main():
    freeze = read(OUT / "freeze-receipt.json")
    complete = read(OUT / "completion-receipt.json")
    assert digest(HERE / "SENSITIVITY-PLAN.md") == freeze["plan_sha256"]
    for name, sha in freeze["files_sha256"].items():
        assert digest(ROOT / name) == sha, name
    for name, sha in freeze["derived_pre_return_sha256"].items():
        assert digest(OUT / name) == sha, name
    for name, sha in complete["artifacts_sha256"].items():
        assert digest(OUT / name) == sha, name
    summaries = read(OUT / "summary.json")["groups"]
    old, new = table(OUT / "all-orders-old.csv"), table(OUT / "all-orders-new.csv")
    old = old.sort_values(KEY).reset_index(drop=True)
    new = new.sort_values(KEY).reset_index(drop=True)
    assert len(old) == len(new) == 2022 and not old.duplicated(KEY).any()
    pd.testing.assert_frame_equal(old[KEY], new[KEY])
    incidence = table(HERE / "incidence/all-orders-incidence.csv")
    eligible = incidence[(incidence.incidence_status == "first_stop_trigger_known")
        & (incidence.trigger_mask_evidence == "close_at_lower_masked")
        & (incidence.trigger_open_at_or_below_stop == True)
        & (incidence.trigger_open_relative_lower == "above_lower")].set_index(KEY)
    wanted = set(eligible.index)
    assert len(wanted) == 12
    actual = set(map(tuple, new.loc[new.sensitivity_changed, KEY].to_numpy()))
    assert actual == wanted
    unchanged = ~new.sensitivity_changed
    pd.testing.assert_frame_equal(old.loc[unchanged], new.loc[unchanged, old.columns])
    pd.testing.assert_frame_equal(old.drop(columns=CHANGED), new[old.columns].drop(columns=CHANGED))
    databases = {"chinext": ROOT / ".local/chinext-payoff-20261004/market.db",
                 "main": ROOT / ".local/multi-strategy-scoring-20261004/market.db"}
    db_hashes = {k: digest(v) for k, v in databases.items()}
    assert db_hashes == freeze["databases_sha256"]
    sql_checks = []
    for row in new[new.sensitivity_changed].to_dict("records"):
        key = tuple(row[k] for k in KEY)
        fact = eligible.loc[key]
        with sqlite3.connect(f"file:{databases[fact.db].as_posix()}?mode=ro", uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            q = conn.execute("SELECT open,volume FROM quotes_daily WHERE code=? AND trade_date=?",
                             (row["code"], fact.trigger_trade_date)).fetchone()
            factor = conn.execute("SELECT hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
                                  (row["code"], fact.trigger_trade_date)).fetchone()[0]
            entry_factor = conn.execute("SELECT hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
                                        (row["code"], row["entry_date"])).fetchone()[0]
            hold = conn.execute("SELECT COUNT(*) FROM trading_calendar WHERE trade_date>? AND trade_date<=?",
                                (row["entry_date"], row["exit_date"])).fetchone()[0]
        assert row["exit_date"] == fact.trigger_trade_date and q[1] > 0
        assert row["exit_price"] == q[0] and row["exit_factor"] == factor and row["entry_factor"] == entry_factor
        assert row["hold_days"] == hold and hold in (1, 2, 3) and row["exit_reason"] == "stop_loss"
        gross = (q[0]*factor/(row["entry_price"]*entry_factor)-1)*100
        same(gross, row["gross_return_pct"])
        same(gross-.21, row["net_return_pct"])
        sql_checks.append({**dict(zip(KEY, key)), "exit_date": row["exit_date"], "raw_open": q[0], "net_return_pct": gross-.21})
    daily = table(OUT / "daily-budget.csv")
    for spec in freeze["groups"]:
        group = spec["group_id"]
        src = table(ROOT / spec["path"])
        if spec["kind"] == "labels":
            src = src.rename(columns={"decision_date": "signal_date", "execution_reason": "label_reason"})
            tr = table(ROOT / spec["trades"])
            cols = [c for c in old.columns if c not in ["group_id", "label_status", "label_reason"]]
            source = src[["signal_date", "code", "label_status", "label_reason"]].merge(
                tr[cols], on=["signal_date", "code"], how="left", validate="one_to_one")
            source.loc[source.label_status == "cancelled", "net_return_pct"] = 0.
        else:
            source = src.copy()
        source["group_id"] = group
        source = source[old.columns].sort_values(KEY).reset_index(drop=True)
        ours = old[old.group_id == group].reset_index(drop=True)
        pd.testing.assert_frame_equal(source, ours, check_dtype=False, rtol=1e-12, atol=1e-10)
        original_budget = table(ROOT / spec["budget"])
        original_budget = original_budget[original_budget[spec["budget_column"]] == spec["budget_value"]]
        slots = int(original_budget.opportunities.sum())
        assert slots == summaries[group]["common_slots"] and original_budget.opportunities.eq(2).all()
        budget = daily[daily.group_id == group]
        assert set(budget.signal_date) == set(original_budget.signal_date)
        assert int(budget.opportunities.sum()) == slots
        complete_group = not source.label_status.eq("unresolved").any() and not original_budget.net_sum.isna().any()
        assert bool(complete_group) == summaries[group]["complete_opportunity_statistics"]
        for kind, data in [("old", old), ("new", new)]:
            part = data[data.group_id == group]
            closed = part[part.label_status == "closed"]
            values = closed.net_return_pct.to_numpy()
            economic = (closed.exit_price*closed.exit_factor/(closed.entry_price*closed.entry_factor)-1)*100
            assert np.allclose(economic-.21, values, atol=1e-9, rtol=1e-10)
            reduced = np.delete(values, np.argmax(values))
            for mode, v in [("base", values), ("double_cost", values-.21), ("winner_removed", reduced),
                            ("double_cost_winner_removed", reduced-.21)]:
                m = summaries[group][kind][mode]
                assert len(v) == m["trades"]
                same(float(v.mean()), m["avg_net_return"])
                same(float(v[v > 0].sum()/-v[v < 0].sum()), m["profit_factor"])
                same(float((v > 0).mean()*100), m["win_rate"])
                same(float(v.sum()) if complete_group else None, m["net_sum"])
                same(float(v.sum()/slots) if complete_group else None, m["common_slot_mean"])
            assert part.loc[part.label_status == "unresolved", "net_return_pct"].isna().all()
            assert part.loc[part.label_status == "cancelled", "net_return_pct"].eq(0).all()
            totals = closed.groupby("signal_date").net_return_pct.sum()
            for d in budget.to_dict("records"):
                value = d[f"{kind}_net_sum"]
                if pd.notna(value):
                    same(float(totals.get(d["signal_date"], 0.)), value)
    differences = new.net_return_pct-old.net_return_pct
    check = dict(passed=True, source_orders=2022, source_groups=11, directly_verified_changed_orders=12,
        unchanged_orders=2010, original_statuses=new.label_status.value_counts().to_dict(),
        changed_orders_higher_net=int((differences[new.sensitivity_changed] > 0).sum()),
        changed_orders_lower_net=int((differences[new.sensitivity_changed] < 0).sum()),
        sql_checks=sql_checks, source_and_database_hashes_unchanged=True,
        no_experiment_module_import=True, group_metrics_and_daily_budget_verified=True,
        unknown_full_opportunity_statistics_remain_null=True,
        verifier_sha256=digest(Path(__file__)), input_receipt_sha256=digest(OUT / "freeze-receipt.json"),
        limitation="Fixed original orders and opening-price model sensitivity; own-order execution and a new strategy enhancement are not proved.")
    target = HERE / "root-sensitivity-check.json"
    with target.open("x", encoding="utf-8") as f:
        json.dump(check, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k:v for k,v in check.items() if k != "sql_checks"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
