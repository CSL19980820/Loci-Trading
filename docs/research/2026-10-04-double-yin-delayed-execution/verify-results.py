"""Post-collection independent accounting checks; does not import the experiment."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import sqlite3

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SEGMENTS = {"train": 356, "validation_2025h2": 123, "observed_2026": 178}
POLICIES = ["corrected_low_open", "yin_close_and_open_above_vwap"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(path):
    return pd.read_csv(path, dtype={"code": str})


def close(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-11, abs_tol=1e-10), (a, b)


def keyset(data, date="decision_date"):
    result = set(zip(data[date], data.code))
    assert len(result) == len(data)
    return result


def metrics(values):
    values = np.asarray(values, dtype=float)
    wins, losses = values[values > 0], values[values < 0]
    return {"trades": len(values), "avg_net_return": float(values.mean()),
            "win_rate": float((values > 0).mean()*100),
            "profit_factor": float(wins.sum() / -losses.sum()),
            "payoff_ratio": float(wins.mean() / -losses.mean()),
            "avg_win": float(wins.mean()), "avg_loss": float(losses.mean()),
            "worst_net": float(values.min())}


def budget(data, dates):
    assert not data.label_status.eq("unresolved").any()
    net = data.groupby("decision_date").net_return_pct.sum().reindex(dates, fill_value=0.)
    return net.to_numpy(float)


def main():
    frozen = read(HERE / "freeze-receipt.json")
    for path, digest in frozen["files_sha256"].items():
        assert sha(ROOT / path) == digest, path
    database = ROOT / ".local/multi-strategy-scoring-20261004/market.db"
    assert sha(database) == frozen["snapshot_sha256"]
    assert sha(ROOT / "docs/research/2026-10-04-double-yin-repair/industry-groups.json") == frozen["groups_sha256"]
    collection = read(HERE / "collection-summary.json")
    quality = frame(HERE / "collection-quality.csv")
    keys = frame(HERE / "order-keys.csv")
    assert len(keys) == 1069 and keyset(keys) == keyset(quality)
    assert sha(HERE / "collection-quality.csv") == collection["quality_csv_sha256"]
    actual_cache = {str(path.relative_to(HERE)).replace("\\", "/") for path in (HERE / "cache").glob("*/*") if path.is_file()}
    assert actual_cache == set(collection["cache_sha256"])
    for path, digest in collection["cache_sha256"].items():
        assert sha(HERE / path) == digest
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    requested = set()
    for item in keys.itertuples():
        folder = HERE / "cache" / f"{item.decision_date}-{item.code}"
        if item.officially_confirmed_suspension_entry:
            assert (item.decision_date, item.code) == ("2026-07-23", "002036")
            assert not folder.exists()
            continue
        request = read(folder / "attempt-01-request.json")
        receipt = read(folder / "attempt-01-receipt.json")
        raw = read(folder / "attempt-01-source-decoded.json")
        assert request["code"] == item.code and request["requested_date"] == item.decision_date
        assert request["market"] == int(item.code.startswith("6"))
        assert request["date_argument"] == int(item.decision_date.replace("-", ""))
        assert request["method"] == "get_history_minute_time_data" and request["attempt"] == 1
        assert not request["source_timestamp_present"] and receipt["status"] == "valid"
        assert receipt["raw_sha256"] == sha(folder / "attempt-01-source-decoded.json")
        assert len(raw) == 240
        prices = np.array([r["price"] for r in raw], float)
        volumes = np.array([r["vol"] for r in raw], float)
        assert np.isfinite(prices).all() and np.isfinite(volumes).all()
        assert (volumes >= 0).all() and (prices >= 0).all() and (prices[volumes > 0] > 0).all()
        quote = dict(connection.execute("SELECT high,low,close,volume,source FROM quotes_daily WHERE trade_date=? AND code=?", (item.decision_date, item.code)).fetchone())
        assert quote["source"] == "tdx"
        assert abs(prices[-1]-quote["close"]) <= .01+1e-8
        assert abs(volumes.sum()*100-quote["volume"]) <= max(100., quote["volume"]*.001)
        assert (prices[prices > 0] >= quote["low"]-.01-1e-8).all()
        assert (prices[prices > 0] <= quote["high"]+.01+1e-8).all()
        close(receipt["quality"]["slot_price"], prices[4])
        close(receipt["quality"]["slot_volume_lots"], volumes[4])
        requested.add((item.decision_date, item.code))
    connection.close()
    assert len(requested) == 1068 and len(actual_cache) == 3204
    results = read(HERE / "summary.json")
    assert results["sensitivity_only"] and results["no_new_nomination"] and not results["original_B_strict_pass"]
    arms, paired = [], []
    for segment, days in SEGMENTS.items():
        summary = read(HERE / f"{segment}-summary.json")
        for path, digest in summary["artifact_sha256"].items():
            assert sha(HERE / path) == digest
        pair = frame(HERE / f"{segment}-paired-calendar.csv")
        dates = sorted(pair.signal_date.unique())
        assert len(dates) == days
        changes = frame(HERE / f"{segment}-execution-changes.csv")
        old_folder = ROOT / "docs/research/2026-10-04-double-yin-vwap"
        if segment != "train":
            old_folder /= "data-correction"
        budgets = {}
        for policy in POLICIES:
            selected = keys[keys.segment.eq(segment) & (keys.in_B if policy == POLICIES[1] else keys.in_corrected_low_open)]
            labelled = frame(HERE / f"{segment}-{policy}-labels.csv")
            events = frame(HERE / f"{segment}-{policy}-events.csv")
            trades = frame(HERE / f"{segment}-{policy}-trades.csv")
            original_labels = frame(old_folder / f"{segment}-{policy}-labels.csv")
            original_trades = frame(old_folder / f"{segment}-{policy}-trades.csv")
            assert keyset(labelled) == keyset(selected) == keyset(original_labels) == keyset(events, "signal_date")
            assert keyset(trades, "signal_date") == keyset(labelled[labelled.label_status.eq("closed")])
            assert labelled.net_return_pct.notna().all()
            assert (labelled[labelled.label_status.eq("cancelled")].net_return_pct == 0).all()
            assert (trades.exit_date > trades.entry_date).all() and (trades.entry_date == trades.signal_date).all()
            assert trades.mae_pct.isna().all() and trades.mfe_pct.isna().all()
            gross = (trades.exit_price*trades.exit_factor/(trades.entry_price*trades.entry_factor)-1)*100
            assert np.allclose(gross, trades.gross_return_pct, rtol=1e-11, atol=1e-10)
            assert np.allclose(gross-.21, trades.net_return_pct, rtol=1e-11, atol=1e-10)
            values = trades.net_return_pct.to_numpy(float)
            dropped = np.delete(values, int(values.argmax()))
            recomputed = {"base": metrics(values), "double_cost": metrics(values-.21),
                          "largest_winner_removed": metrics(dropped), "double_cost_largest_winner_removed": metrics(dropped-.21)}
            run = summary["runs"][policy]
            for mode, expected in recomputed.items():
                for name, value in expected.items():
                    close(value, run["metrics"][mode][name])
            assert dict(Counter(labelled.label_status)) == run["label_accounting"]
            assert dict(Counter(events.status)) == run["execution_accounting"]
            assert run["selected_orders"] == len(selected) and run["slots"] == days*2 and run["unresolved_selected"] == 0
            close(labelled.net_return_pct.sum()/(days*2), run["slot_mean"])
            close(original_labels.net_return_pct.sum()/(days*2), run["original_open_slot_mean"])
            budgets[policy] = budget(labelled, dates)
            budgets[f"{policy}_original_open"] = budget(original_labels, dates)
            change = changes[changes.policy.eq(policy)]
            assert keyset(change) == keyset(selected)
            both = change[change.old_closed & change.new_closed]
            arms.append({"segment": segment, "policy": policy, "selected": len(selected),
                         "old_closed": len(original_trades), "new_closed": len(trades), "events": dict(Counter(events.status)),
                         "old_metrics": metrics(original_trades.net_return_pct), "new_metrics": recomputed,
                         "old_slot_mean": run["original_open_slot_mean"], "new_slot_mean": run["slot_mean"],
                         "both_closed": len(both), "entry_change_mean_pct": float(both.entry_price_change_pct.mean()),
                         "entry_change_median_pct": float(both.entry_price_change_pct.median()),
                         "exit_dates_changed": int((both.old_exit_date != both.new_exit_date).sum()),
                         "old_filled_new_cancelled": int((change.old_closed & ~change.new_closed).sum()),
                         "old_cancelled_new_filled": int((~change.old_closed & change.new_closed).sum())})
        pairs = [(f"{p}_vs_original_open", p, f"{p}_original_open") for p in POLICIES]
        pairs.append(("B_vs_low_at_fifth_slot", POLICIES[1], POLICIES[0]))
        for name, left, right in pairs:
            block = pair[pair.comparison.eq(name)].sort_values("signal_date")
            assert block.signal_date.tolist() == dates and (block.opportunities == 2).all()
            assert (block.unresolved_orders == 0).all()
            assert np.allclose(block.net_sum, budgets[left], rtol=1e-11, atol=1e-10)
            delta = budgets[left]-budgets[right]
            assert np.allclose(block.delta_net_sum, delta, rtol=1e-11, atol=1e-10)
            close(delta.sum()/(days*2), summary["paired_comparisons"][name]["point_delta_per_opportunity"])
            paired.append({"segment": segment, "comparison": name, **summary["paired_comparisons"][name]})
    valid = quality[quality.status.eq("valid")]
    result = {"verified": True, "method": "independent CSV/raw JSON/sqlite checks without experiment imports",
              "frozen_input_files": len(frozen["files_sha256"]), "snapshot_hash_unchanged": True,
              "cached_files": len(actual_cache), "requests": len(requested), "retries": 0,
              "fixed_keys": len(keys), "quality_counts": dict(Counter(quality.status)),
              "exact_numeric_pairs": int(valid.match_class.eq("exact_numeric").sum()),
              "tail_exact_numeric": int(valid.tail_exact_numeric_match.sum()),
              "volume_exact_numeric": int(valid.volume_exact_numeric_match.sum()),
              "volume_max_abs_delta_shares": float(valid.volume_abs_delta_shares.max()),
              "volume_max_abs_relative_delta": float(valid.volume_relative_delta.abs().max()),
              "tail_max_abs_delta_yuan": float(valid.tail_price_abs_delta_yuan.max()),
              "zero_volume_fifth_slots": int(valid.slot_volume_lots.eq(0).sum()),
              "calendar_days": SEGMENTS, "arms": arms, "paired": paired,
              "original_B_strict_pass": False, "no_new_nomination": True}
    with (HERE / "verification.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"verified": True, "arms": len(arms), "fixed_keys": len(keys), "requests": len(requested)}))


if __name__ == "__main__":
    main()
