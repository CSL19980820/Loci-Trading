"""Independent CSV/order accounting and raw-row checks; no strategy imports."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT/".local/chinext-payoff-20261004/market.db"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def same(actual, expected):
    if expected is None:
        assert actual is None
    else:
        assert actual is not None and np.isclose(float(actual), float(expected), atol=1e-9, rtol=0), (actual, expected)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify():
    plan = load(HERE/"PLAN.json")
    assert digest(DB) == plan["snapshot_sha256"]
    for path, expected in plan["sources"].items():
        assert digest(ROOT/path) == expected
    assert digest(HERE/"PLAN.md") == plan["contract_sha256"]
    assert digest(ROOT/"docs/research/2026-10-04-vwap-study/PLAN.md") == plan["root_plan_sha256"]
    assert digest(HERE/"PLAN.json") == load(HERE/"freeze-receipt.json")["plan_sha256"]
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    def quote(code, date):
        row = conn.execute("SELECT * FROM quotes_daily WHERE code=? AND trade_date=?", (code, date)).fetchone()
        assert row is not None
        return dict(row)
    def factor(code, date):
        return float(conn.execute("SELECT hfq_factor FROM adjust_factors WHERE code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1", (code, date)).fetchone()[0])
    outcomes = load(HERE/"summary.json")
    phases = {"train": outcomes["train"], **outcomes.get("later", {})}
    counts = dict(formal_orders=0, closed_trade_returns=0, candidate_amount_rows=0,
                  raw_fill_branches=0, stored_factor_endpoints=0, preselection_lists=0)
    unknown_quotes, phase_results, all_orders = {}, {}, {}
    for phase, results in phases.items():
        path = HERE/phase
        receipt = load(path/"selection-receipt.json")
        candidates = pd.read_csv(path/"all-candidate-qualifications.csv", dtype={"code": str})
        daily = pd.read_csv(path/"daily-budget.csv")
        dates = sorted(daily.signal_date.unique())
        assert len(dates)*2 == results["common_slots"]
        assert len(dates) == results["common_market_days"]
        for row in candidates.itertuples():
            raw = quote(row.code, row.signal_date)
            if row.vwap_known:
                assert raw["source"] == "tdx" and min(raw["amount"], raw["volume"]) > 0
                value = raw["amount"]/raw["volume"]
                same(row.vwap_raw, value)
                same(row.raw_amount, raw["amount"])
                same(row.raw_volume, raw["volume"])
                assert raw["low"]-.01 <= value <= raw["high"]+.01
                cents = int((Decimal(str(raw["amount"]))/Decimal(str(raw["volume"]))*100).to_integral_value(rounding=ROUND_FLOOR))
                assert int(row.limit_cents) == cents
                assert row.vwap_gate == (row.h5_economic < row.vwap_economic <= row.close_economic)
                counts["candidate_amount_rows"] += 1
        candidates = candidates[candidates.signal_date.isin(dates)]
        phase_results[phase] = {}
        for arm, result in results["runs"].items():
            assert digest(path/f"{arm}-preselected.csv") == receipt["preselected_sha256"][arm]
            chosen = pd.read_csv(path/f"{arm}-preselected.csv", dtype={"code": str})
            orders = pd.read_csv(path/f"{arm}-orders.csv", dtype={"code": str})
            all_orders[(phase, arm)] = orders
            expected = candidates[candidates.legacy_selected] if arm == "legacy_original" else candidates[candidates.corrected_candidate]
            if arm != "legacy_original":
                if arm != "corrected_original":
                    expected = expected[expected.vwap_known]
                if arm.startswith("vwap_gate_"):
                    expected = expected[expected.vwap_gate]
                expected = expected.sort_values(["signal_date", "original_score", "code"], ascending=[True, False, True]).groupby("signal_date", sort=True).head(2)
            keys = ["signal_date", "code"]
            assert chosen[keys].to_records(index=False).tolist() == expected[keys].to_records(index=False).tolist()
            assert chosen[keys].to_records(index=False).tolist() == orders[keys].to_records(index=False).tolist()
            assert len(orders) == len(orders[keys].drop_duplicates())
            assert orders.groupby("signal_date").size().max() <= 2
            counts["preselection_lists"] += 1
            counts["formal_orders"] += len(orders)
            closed = orders[orders.label_status.eq("closed")]
            unknown = orders[orders.label_status.eq("unresolved")]
            cancelled = orders[orders.label_status.eq("cancelled")]
            assert unknown.net_return_pct.isna().all()
            assert cancelled.net_return_pct.eq(0).all()
            winner = closed.net_return_pct.idxmax() if len(closed) else None
            for stress, cost, remove in (("base", .21, False), ("double_cost", .42, False),
                    ("winner_removed", .21, True), ("double_cost_winner_removed", .42, True)):
                subset = closed.drop(index=winner) if remove and winner is not None else closed
                net = subset.gross_return_pct-cost
                m = result["metrics"][stress]
                assert m["trades"] == len(net) and m["unresolved"] == len(unknown)
                same(m["avg_net_return"], float(net.mean()) if len(net) else None)
                wins, losses = net[net > 0], net[net <= 0]
                same(m["profit_factor"], float(wins.sum()/-losses.sum()) if losses.sum() < 0 else None)
                same(m["common_slot_mean"], None if len(unknown) else float(net.sum()/results["common_slots"]))
            armdaily = daily[daily.variant.eq(arm)]
            assert armdaily.signal_date.tolist() == dates and armdaily.opportunities.eq(2).all()
            for date, day in armdaily.set_index("signal_date").iterrows():
                if unknown.signal_date.eq(date).any():
                    assert pd.isna(day.net_sum)
                else:
                    same(day.net_sum, closed.loc[closed.signal_date.eq(date), "net_return_pct"].sum())
            for row in closed.itertuples():
                entry = quote(row.code, row.entry_date)
                assert entry["volume"] > 0
                if arm in ("vwap_gate_limit", "vwap_gate_limit_one_tick"):
                    limit = int(row.limit_cents)/100
                    if entry["open"] <= limit:
                        expected_price, expected_branch = entry["open"], "open_at_or_below_limit"
                    else:
                        expected_price, expected_branch = limit, "intraday_limit_proxy"
                        assert entry["low"] <= (int(row.limit_cents)-(arm.endswith("one_tick")))/100
                    assert row.entry_proxy_branch == expected_branch
                else:
                    expected_price = entry["open"]
                same(row.entry_price, expected_price)
                ef, xf = factor(row.code, row.entry_date), factor(row.code, row.exit_date)
                same(row.entry_factor, ef)
                same(row.exit_factor, xf)
                raw_exit = quote(row.code, row.exit_date)
                if row.exit_reason == "hold_expired":
                    same(row.exit_price, raw_exit["close"])
                gross = (row.exit_price*xf/(row.entry_price*ef)-1)*100
                same(row.gross_return_pct, gross)
                same(row.net_return_pct, gross-.21)
                assert row.exit_date > row.entry_date
                counts["raw_fill_branches"] += 1
                counts["stored_factor_endpoints"] += 2
                counts["closed_trade_returns"] += 1
            for row in unknown.itertuples():
                if row.label_reason != "unknown_or_invalid_holding_quote":
                    continue
                # Preserve actual unknown source rows only; no source rewriting.
                end = plan["splits"][phase][1]
                rows = conn.execute("SELECT trade_date,code,open,high,low,close,volume,amount,source FROM quotes_daily WHERE code=? AND trade_date>=? AND trade_date<=? AND volume IS NULL ORDER BY trade_date", (row.code, row.entry_date, end)).fetchall()
                for raw in rows:
                    key = (raw["trade_date"], raw["code"])
                    unknown_quotes[key] = dict(raw)
            phase_results[phase][arm] = dict(orders=len(orders), closed=len(closed), cancelled=len(cancelled), unresolved=len(unknown),
                entry_months=int(closed.entry_date.str[:7].nunique()), budget=results["common_slots"])
        if "vwap_gate_limit" in results["runs"]:
            a = all_orders[(phase, "vwap_gate_open")]
            b = all_orders[(phase, "vwap_gate_limit")]
            stress = all_orders[(phase, "vwap_gate_limit_one_tick")]
            assert a[["signal_date", "code"]].equals(b[["signal_date", "code"]])
            assert a[["signal_date", "code"]].equals(stress[["signal_date", "code"]])
    conn.close()
    pd.DataFrame(unknown_quotes.values()).sort_values(["code", "trade_date"]).to_csv(HERE/"unknown-holding-raw-quotes.csv", index=False)
    result = dict(passed=True, counts=counts, phases=phase_results, raw_unknown_rows=len(unknown_quotes),
        no_strategy_or_metric_helper_imports=True, source_plan_snapshot_hashes_unchanged=True,
        checks=["frozen preselection hashes", "independent Top2 and no refill", "same A/B/stress keys",
            "all four cost/winner metric bundles", "whole calendar budget and unknown nulls",
            "raw TDX amount quotient and Decimal cents", "actual raw opening/limit branches",
            "stored factors and raw/economic gross/net returns", "original NULL-volume rows exported"],
        plan_sha256=digest(HERE/"PLAN.json"), verifier_sha256=digest(Path(__file__)))
    (HERE/"verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    verify()
