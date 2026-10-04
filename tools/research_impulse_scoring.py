"""Frozen, read-only scoring comparison for impulse-inside-breakout-v1.

Uses the existing snapshot and execution contract; never edits live scoring.
Run via tools/isolated_check.py. The plan and source hashes are written before
opening market data, and the training nomination before later-period evaluation.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE,
    CutoffMarketStore,
    common_maturity_mask,
    context_evidence,
    execute_split_context,
    prepare,
    sha256,
    source_hashes,
)
from tools.research_chinext_payoff_filters import (  # noqa: E402
    SPLITS,
    independent_metrics,
    rank_filtered,
    verify_metrics,
)
from tools.strategy_chinext_review import write_json  # noqa: E402

SLUG = "impulse-inside-breakout-v1"
OUTPUT = ROOT / "docs/research/2026-10-04-impulse-scoring-study"
VARIANTS = {
    "baseline": "原评分 S0",
    "low80": "简单低位：0.8*S0 + 20*(1-P)",
    "context70": "位置+修复：0.7*S0 + 20*R*B(P) + 5*R + 5*U",
    "trend80": "纯趋势：0.8*S0 + 15*R + 5*U",
    "context80": "轻量位置+修复：0.8*S0 + 10*R + 5*U + 5*R*B(P)",
}


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sources() -> dict[str, str]:
    return {**source_hashes(),
            "tools/research_chinext_payoff_filters.py": sha256(ROOT / "tools/research_chinext_payoff_filters.py"),
            "tools/research_impulse_scoring.py": sha256(Path(__file__))}


def plan() -> dict[str, Any]:
    return {
        "created_at": now(), "strategy": SLUG, "variants": VARIANTS,
        "features": {
            "P": "(C(T-5)-LLV(L,120)(T-5))/(HHV(H,120)(T-5)-LLV(L,120)(T-5)); clip[0,1]",
            "B": "min(P/0.2,1,(1-P)/0.5), clipped[0,1]; 20%-50% full comfort bonus",
            "R": "C(T)>MA20(T) AND MA20(T)>MA20(T-10)",
            "U": "R AND MA20(T)>=MA60(T) AND MA60(T)>=MA60(T-10)",
            "missing": "Any missing/invalid context => retain S0 for all alternatives; no candidate deletion",
        },
        "splits": SPLITS, "fixed_exit": BASELINE.to_dict(),
        "cost_pct": .21, "stress_cost_pct": .42,
        "common_maturity_sessions": 4,
        "selection": "Train-only nomination: mean net > baseline and PF > baseline and PF>1; highest mean, PF, lexical id. All five frozen variants reported in every segment; no tuning.",
        "comparison": "Full shape candidates reranked then daily Top2, rounded4, code ascending tie. Same number of signals daily; unfilled or censored opportunities count zero in opportunity mean.",
        "robustness": "Report changed dates/picks; replaced contribution; monthly-block paired bootstrap 5000 seed20261004; double costs; largest winner removed; per-period and pooled metrics. CI descriptive, not multiple-testing corrected.",
        "limitations": [
            "All periods retrospective: prior studies already inspected 2025H2 and 2026; no new untouched holdout.",
            "Current catalog and names, stored adjustment revisions: not strict point-in-time or survivor-free.",
            "Independent trade events, equal opportunity accounting; no portfolio NAV/capacity/compounding simulation.",
            "Four-session maturity purge for this fixed exit; old study used 20 sessions, so baseline is verified on the common subset.",
            "Daily bar execution and worst low through exit session cannot establish exact intraday path.",
        ],
    }


def context_scores(panels: dict[str, Any], old: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    close, high, low = (panels[key] for key in ("close", "high", "low"))
    lo = low.rolling(120).min().shift(5)
    hi = high.rolling(120).max().shift(5)
    position = ((close.shift(5) - lo) / (hi - lo).where(hi.gt(lo))).clip(0, 1)
    ma20, ma60 = close.rolling(20).mean(), close.rolling(60).mean()
    repair = close.gt(ma20) & ma20.gt(ma20.shift(10))
    uptrend = repair & ma20.ge(ma60) & ma60.ge(ma60.shift(10))
    valid = np.isfinite(position) & np.isfinite(ma60.shift(10)) & np.isfinite(ma20.shift(10))
    comfort = pd.DataFrame(np.minimum.reduce([
        (position / .2).to_numpy(), np.ones(position.shape), ((1 - position) / .5).to_numpy(),
    ]), index=old.index, columns=old.columns).clip(0, 1)
    raw = {
        "baseline": old,
        "low80": .8 * old + 20 * (1 - position),
        "context70": .7 * old + 20 * repair * comfort + 5 * repair + 5 * uptrend,
        "trend80": .8 * old + 15 * repair + 5 * uptrend,
        "context80": .8 * old + 10 * repair + 5 * uptrend + 5 * repair * comfort,
    }
    scores = {key: value.where(valid, old).where(old.notna()).clip(0, 100).round(4)
              for key, value in raw.items()}
    return scores, {"position120_before_pattern": position, "repair": repair, "uptrend": uptrend,
                    "comfort": comfort, "context_valid": valid}


def keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return {(str(frame.index[i]), str(frame.columns[j])) for i, j in zip(*np.nonzero(frame.to_numpy()))}


def trade_key(trade: Any) -> tuple[str, str]:
    return str(trade.signal_date), str(trade.code)


def metric_bundle(trades: list[Any]) -> dict[str, Any]:
    values = np.array([trade.net_return_pct for trade in trades])
    adverse = np.array([trade.mae_pct for trade in trades])
    largest = max(trades, key=lambda trade: trade.net_return_pct) if trades else None
    reduced = [trade for trade in trades if trade is not largest]
    return {
        "base": independent_metrics(trades), "double_cost": independent_metrics(trades, .42),
        "largest_winner_removed": independent_metrics(reduced),
        "double_cost_largest_winner_removed": independent_metrics(reduced, .42),
        "return_p10": float(np.quantile(values, .1)) if len(values) else None,
        "worst_net_return": float(values.min()) if len(values) else None,
        "loss_le_minus6_pct": float(np.mean(values <= -6) * 100) if len(values) else None,
        "daily_bar_mae_mean": float(adverse.mean()) if len(adverse) else None,
        "daily_bar_mae_p10": float(np.quantile(adverse, .1)) if len(adverse) else None,
    }


def paired_bootstrap(daily: pd.DataFrame) -> dict[str, Any]:
    """Resample paired calendar-month blocks; same signal budget in both arms."""
    blocks = daily.assign(month=daily.signal_date.str[:7]).groupby("month")[
        ["delta_net_sum", "opportunities"]].sum().to_numpy()
    if not len(blocks):
        return {"months": 0, "ci95_delta_per_opportunity": None}
    indices = np.random.default_rng(20261004).integers(0, len(blocks), (5000, len(blocks)))
    samples = blocks[indices].sum(axis=1)
    valid = samples[:, 1] > 0
    estimates = samples[valid, 0] / samples[valid, 1]
    return {"months": len(blocks), "replicates": 5000, "seed": 20261004,
            "ci95_delta_per_opportunity": np.quantile(estimates, [.025, .975]).tolist(),
            "point_delta_per_opportunity": float(daily.delta_net_sum.sum() / daily.opportunities.sum())}


def past_baseline_check(segment: str, trades: list[Any], previous_last_signal: str) -> bool:
    path = ROOT / f"docs/research/2026-10-04-chinext-payoff-study/filters/{SLUG}-{segment}-baseline-trades.csv"
    previous = pd.read_csv(path, dtype={"code": str, "signal_date": str})
    previous = previous[previous.exit_reason.ne("data_end")]
    observed = {(row.signal_date, row.code): row.net_return_pct for row in previous.itertuples()}
    current = {trade_key(trade): trade.net_return_pct for trade in trades if trade.signal_date <= previous_last_signal}
    if observed.keys() != current.keys() or not all(np.isclose(current[key], value, atol=1e-9, rtol=0) for key, value in observed.items()):
        raise AssertionError(f"Prior baseline diverged: {segment}")
    return True


def evaluate(db: Path, segment: str, start: str, end: str, output: Path) -> tuple[dict[str, Any], dict[str, list[Any]], list[pd.DataFrame]]:
    print(f"Prepare {segment}, market cutoff {end}", flush=True)
    store = CutoffMarketStore(db, end)
    try:
        ctx = prepare(store, SLUG, start, end)
        computed = ctx["engine"].compute(ctx["panels"], ctx["resolved_params"])
        candidates, old = computed.factors["条件候选"], computed.factors["score"]
        scores, features = context_scores(ctx["panels"], old)
        baseline, _, _ = rank_filtered(candidates, old, candidates)
        pd.testing.assert_frame_equal(baseline.loc[start:end], ctx["signals"].loc[start:end].fillna(False).astype(bool))
        cutoff = old.index[len(old) * 2 // 3]
        prefix = {key: value.loc[:cutoff] if isinstance(value, pd.DataFrame) else value for key, value in ctx["panels"].items()}
        prefix_computed = ctx["engine"].compute(prefix, ctx["resolved_params"])
        pd.testing.assert_frame_equal(prefix_computed.factors["score"], old.loc[:cutoff])
        prefix_scores, _ = context_scores(prefix, prefix_computed.factors["score"])
        for key in scores:
            pd.testing.assert_frame_equal(prefix_scores[key], scores[key].loc[:cutoff])
        mature = common_maturity_mask(old.index, start, end, max_hold=4)
        previous_mature = common_maturity_mask(old.index, start, end, max_hold=20)
        previous_last_signal = str(old.index[previous_mature][-1])
        base_mask = baseline.where(mature, False, axis=0)
        base_keys = keys(base_mask)
        candidate_mask = (candidates & old.notna()).where(mature, False, axis=0)
        candidate_records = []
        for date, code in sorted(keys(candidate_mask)):
            record = {"segment": segment, "signal_date": date, "code": code}
            record.update({key: float(value.loc[date, code]) for key, value in features.items()})
            record.update({key: float(value.loc[date, code]) for key, value in scores.items()})
            candidate_records.append(record)
        pd.DataFrame(candidate_records).to_csv(output / f"{segment}-candidates.csv", index=False)
        rows, closed, daily_frames = {}, {}, []
        for variant, score in scores.items():
            selected, _, ranks = rank_filtered(candidates, score, candidates)
            pd.testing.assert_series_equal(selected.sum(axis=1), baseline.sum(axis=1))
            selected_keys = keys(selected.where(mature, False, axis=0))
            run = execute_split_context({**ctx, "signals": selected}, BASELINE.config(end), start, end, max_hold=4)
            verify_metrics(run)
            closed[variant] = run["closed_trades"]
            if variant == "baseline":
                past_baseline_check(segment, closed[variant], previous_last_signal)
            outcomes = {trade_key(t): t for t in closed[variant]}
            base_outcomes = {trade_key(t): t for t in closed["baseline"]}
            common = selected_keys & base_keys
            for key in common & outcomes.keys() & base_outcomes.keys():
                if not np.isclose(outcomes[key].net_return_pct, base_outcomes[key].net_return_pct, atol=1e-9, rtol=0):
                    raise AssertionError("Identical signal has different execution")
            signal_records = []
            for date, code in sorted(selected_keys):
                trade = outcomes.get((date, code))
                signal_records.append({"segment": segment, "variant": variant,
                    "signal_date": date, "code": code, "score": score.loc[date, code],
                    "rank": ranks.loc[date, code], "baseline_selected": (date, code) in base_keys,
                    "closed": trade is not None, "opportunity_net_pct": trade.net_return_pct if trade else 0.0})
            pd.DataFrame(signal_records).to_csv(output / f"{segment}-{variant}-signals.csv", index=False)
            pd.DataFrame([t.to_dict(include_factors=True) for t in run["all_trades"]]).to_csv(
                output / f"{segment}-{variant}-trades.csv", index=False)
            added, removed = selected_keys - base_keys, base_keys - selected_keys
            replacement_records = [{"side": side, "signal_date": date, "code": code,
                "net_pct": mapping[(date, code)].net_return_pct if (date, code) in mapping else 0.0,
                "closed": (date, code) in mapping}
                for side, group, mapping in (("added", added, outcomes), ("removed", removed, base_outcomes))
                for date, code in sorted(group)]
            pd.DataFrame(replacement_records, columns=["side", "signal_date", "code", "net_pct", "closed"]).to_csv(
                output / f"{segment}-{variant}-replacements.csv", index=False)
            daily = []
            for date in old.index[mature]:
                n = int(baseline.loc[date].sum())
                alt_sum = sum(t.net_return_pct for t in closed[variant] if t.signal_date == date)
                base_sum = sum(t.net_return_pct for t in closed["baseline"] if t.signal_date == date)
                daily.append({"segment": segment, "variant": variant, "signal_date": str(date),
                    "opportunities": n, "net_sum": alt_sum, "base_net_sum": base_sum,
                    "delta_net_sum": alt_sum - base_sum})
            daily_frame = pd.DataFrame(daily)
            daily_frames.append(daily_frame)
            added_sum = sum(outcomes[key].net_return_pct for key in added if key in outcomes)
            removed_sum = sum(base_outcomes[key].net_return_pct for key in removed if key in base_outcomes)
            if not np.isclose(daily_frame.delta_net_sum.sum(), added_sum - removed_sum):
                raise AssertionError("Replacement contribution does not reconcile")
            rows[variant] = {
                "definition": VARIANTS[variant], "metrics": metric_bundle(closed[variant]),
                "accounting": run["accounting"],
                "opportunity_mean": sum(t.net_return_pct for t in closed[variant]) / len(base_keys),
                "changed_days": len({date for date, _ in added | removed}),
                "added_picks": len(added), "removed_picks": len(removed),
                "added_metrics": independent_metrics([outcomes[key] for key in added if key in outcomes]),
                "removed_metrics": independent_metrics([base_outcomes[key] for key in removed if key in base_outcomes]),
                "replacement_net_sum_delta": added_sum - removed_sum,
                "paired_month_block_bootstrap": paired_bootstrap(daily_frame),
            }
            m = rows[variant]["metrics"]["base"]
            print(f"{segment}/{variant}: n={m['trades']} mean={m['avg_net_return']:.4f} PF={m['profit_factor']:.3f}; replaced={len(added)}", flush=True)
        # All raw shape opportunities, used only for frozen location bucket diagnostics.
        all_run = execute_split_context({**ctx, "signals": candidates & old.notna()}, BASELINE.config(end), start, end, max_hold=4)
        all_closed = {trade_key(t): t for t in all_run["closed_trades"]}
        buckets = {}
        for label, lower, upper in (("0-20%", 0, .2), ("20-50%", .2, .5), ("50-80%", .5, .8), ("80-100%", .8, 1.000001)):
            selected_trades = [trade for (date, code), trade in all_closed.items()
                if lower <= features["position120_before_pattern"].loc[date, code] < upper]
            buckets[label] = independent_metrics(selected_trades)
        count = candidate_mask.sum(axis=1).loc[mature]
        return {"context": context_evidence(ctx), "prefix_checks_cutoff": str(cutoff),
                "baseline_matches_previous_study": True,
                "scope": {"shape_candidates": int(count.sum()), "top2_opportunities": len(base_keys),
                    "days_with_signals": int(count.gt(0).sum()), "days_over_two_candidates": int(count.gt(2).sum()),
                    "missing_context_candidates": int((candidate_mask & ~features["context_valid"]).to_numpy().sum())},
                "runs": rows, "all_shape_position_buckets": buckets,
                "all_shape_accounting": all_run["accounting"]}, closed, daily_frames
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output, db = args.output.resolve(), args.db.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "PLAN.json").exists():
        raise FileExistsError("Use a fresh output directory; do not overwrite a frozen study")
    source_before, db_before = sources(), sha256(db)
    frozen = {**plan(), "sources": source_before, "snapshot_sha256": db_before}
    write_json(output / "PLAN.json", frozen)
    write_json(output / "freeze-receipt.json", {"created_at": now(), "plan_sha256": sha256(output / "PLAN.json")})
    summary: dict[str, Any] = {"plan_sha256": sha256(output / "PLAN.json"), "segments": {}}
    all_trades: dict[str, list[Any]] = {key: [] for key in VARIANTS}
    all_daily = []
    for segment, (start, end) in SPLITS.items():
        if sources() != source_before:
            raise AssertionError("Research sources changed after freeze")
        result, trades, daily = evaluate(db, segment, start, end, output)
        summary["segments"][segment] = result
        for variant in VARIANTS:
            all_trades[variant].extend(trades[variant])
        all_daily.extend(daily)
        write_json(output / f"{segment}-summary.json", result)
        if segment == "train":
            base = result["runs"]["baseline"]["metrics"]["base"]
            eligible = [key for key in VARIANTS if key != "baseline"
                and result["runs"][key]["metrics"]["base"]["avg_net_return"] > base["avg_net_return"]
                and result["runs"][key]["metrics"]["base"]["profit_factor"] > max(1, base["profit_factor"])]
            eligible.sort(key=lambda key: (-result["runs"][key]["metrics"]["base"]["avg_net_return"],
                -result["runs"][key]["metrics"]["base"]["profit_factor"], key))
            summary["training_nomination"] = eligible[0] if eligible else None
            write_json(output / "training-nomination.json", {"created_at": now(), "nominee": summary["training_nomination"],
                "plan_sha256": summary["plan_sha256"], "training_summary_sha256": sha256(output / "train-summary.json")})
    daily = pd.concat(all_daily, ignore_index=True)
    daily.to_csv(output / "paired-daily-results.csv", index=False)
    summary["pooled"] = {}
    for key in VARIANTS:
        frame = daily[daily.variant.eq(key)]
        summary["pooled"][key] = {"metrics": metric_bundle(all_trades[key]),
            "opportunity_mean": float(frame.net_sum.sum() / frame.opportunities.sum()),
            "paired_month_block_bootstrap": paired_bootstrap(frame),
            "added_picks": sum(segment["runs"][key]["added_picks"] for segment in summary["segments"].values())}
    if sources() != source_before or sha256(db) != db_before:
        raise AssertionError("Source or snapshot changed during research")
    summary["completed_at"] = now()
    summary["source_and_snapshot_unchanged"] = True
    write_json(output / "summary.json", summary)
    print(json.dumps({"output": str(output), "training_nomination": summary["training_nomination"],
                      "source_and_snapshot_unchanged": True}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
