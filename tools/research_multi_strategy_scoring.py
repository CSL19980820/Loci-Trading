"""Frozen scoring transfer study. Only research outputs are written.

Run with tools/isolated_check.py; source quotes are read-only. Each strategy is
evaluated independently; train nomination precedes later-period execution.
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

from src.backtest.application.runner import prepare_backtest_context  # noqa: E402
from src.backtest.domain.models import BacktestConfig  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.research_chinext_payoff_exits import (  # noqa: E402
    CutoffMarketStore, common_maturity_mask, context_evidence,
    execute_split_context, sha256, source_hashes,
)
from tools.research_chinext_payoff_filters import SPLITS, independent_metrics  # noqa: E402
from tools.research_impulse_scoring import VARIANTS, keys, now, paired_bootstrap, trade_key  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-multi-strategy-scoring"
SPECS = {
    "yangshi-tail-v1": dict(position_lag=1, trend_lag=0, top_n=1, hold_days=2,
                            stop=None, slippage_bps=10, evidence="native_daily"),
    "qianlong-close-v3": dict(position_lag=1, trend_lag=0, top_n=2, hold_days=3,
                             stop=-7., slippage_bps=10, evidence="native_daily"),
    "contraction-rebreakout-v1": dict(position_lag=13, trend_lag=0, top_n=2, hold_days=3,
                                     stop=-6., slippage_bps=5, evidence="native_daily"),
    "double-volume-yin-low-open-v1": dict(position_lag=3, trend_lag=1, top_n=2, hold_days=3,
                                         stop=-6., slippage_bps=5, evidence="daily_open_proxy"),
}


def config(spec: dict, end: str) -> BacktestConfig:
    return BacktestConfig(hold_days=spec["hold_days"], stop_loss_pct=spec["stop"],
        take_profit_pct=None, commission_bps=3, stamp_duty_bps=5,
        slippage_bps=spec["slippage_bps"], benchmark=None, strict_limit_prices=True,
        economic_returns=True, valuation_end=end)


def context_scores(panels: dict, old: pd.DataFrame, spec: dict):
    close, high, low = (panels[k] for k in ("close", "high", "low"))
    lag = spec["position_lag"]
    lo, hi = low.rolling(120).min().shift(lag), high.rolling(120).max().shift(lag)
    position = ((close.shift(lag) - lo) / (hi - lo).where(hi.gt(lo))).clip(0, 1)
    trend_close = close.shift(spec["trend_lag"])
    ma20, ma60 = trend_close.rolling(20).mean(), trend_close.rolling(60).mean()
    repair = trend_close.gt(ma20) & ma20.gt(ma20.shift(10))
    uptrend = repair & ma20.ge(ma60) & ma60.ge(ma60.shift(10))
    valid = np.isfinite(position) & np.isfinite(ma60.shift(10)) & np.isfinite(ma20.shift(10))
    comfort = pd.DataFrame(np.minimum.reduce([
        (position / .2).to_numpy(), np.ones(position.shape), ((1 - position) / .5).to_numpy(),
    ]), index=old.index, columns=old.columns).clip(0, 1)
    raw = {"baseline": old, "low80": .8 * old + 20 * (1-position),
        "context70": .7 * old + 20 * repair * comfort + 5 * repair + 5 * uptrend,
        "trend80": .8 * old + 15 * repair + 5 * uptrend,
        "context80": .8 * old + 10 * repair + 5 * uptrend + 5 * repair * comfort}
    scores = {k: v.where(valid, old).where(old.notna()).clip(0, 100).round(4) for k, v in raw.items()}
    return scores, dict(position120=position, repair=repair, uptrend=uptrend,
                        comfort=comfort, context_valid=valid)


def rank_candidates(candidates: pd.DataFrame, score: pd.DataFrame, native: pd.DataFrame,
                    top_n: int) -> pd.DataFrame:
    """Rounded score, original strength, code. Native strength resolves quantization ties."""
    selected = pd.DataFrame(False, index=score.index, columns=score.columns)
    for date in score.index:
        values = score.loc[date].where(candidates.loc[date]).dropna()
        ordered = sorted(values.index, key=lambda code: (-values[code], -native.at[date, code], str(code)))
        selected.loc[date, ordered[:top_n]] = True
    return selected


def extract(computed: Any, slug: str):
    f = computed.factors
    candidates = f["条件候选"].fillna(False).astype(bool)
    if slug == "yangshi-tail-v1":
        candidates &= f["弱市可交易_上涨家数>=40%"]
        old, native = f["评分百分位"], f["当日涨幅(%)"]
    elif slug == "qianlong-close-v3":
        candidates &= f["弱市可交易"]
        native = f["白线贴近度"]
        old = native.mul(100).clip(0, 100)
    else:
        old = native = f["score"]
    return candidates, old.where(candidates), native


def metrics(trades: list, cost: float) -> dict:
    biggest = max(trades, key=lambda t: t.net_return_pct) if trades else None
    rest = [t for t in trades if t is not biggest]
    values = np.array([t.net_return_pct for t in trades])
    return {"base": independent_metrics(trades, cost),
        "double_cost": independent_metrics(trades, 2*cost),
        "largest_winner_removed": independent_metrics(rest, cost),
        "double_cost_largest_winner_removed": independent_metrics(rest, 2*cost),
        "worst_net_return": float(values.min()) if len(values) else None,
        "return_p10": float(np.quantile(values, .1)) if len(values) else None}


def sources(slug: str) -> dict:
    paths = ["tools/research_multi_strategy_scoring.py", "tools/research_impulse_scoring.py",
        "tools/research_chinext_payoff_filters.py",
        "src/strategy/application/yangshi_tail.py", "src/strategy/application/qianlong.py",
        "src/strategy/application/double_yin_low_open.py", "src/strategy/application/persist.py",
        "src/strategy/application/score_percentile.py"]
    proxy = "tools/research_double_yin_scoring_proxy.py"
    if SPECS[slug]["evidence"] == "daily_open_proxy":
        paths.append(proxy)
    return {**source_hashes(), **{p: sha256(ROOT / p) for p in paths}}


def prepare(store, slug, start, end, spec, groups_path):
    if spec["evidence"] == "daily_open_proxy":
        from tools.research_double_yin_scoring_proxy import prepare_proxy_context
        return prepare_proxy_context(store, start, end, config(spec, end), groups_path)
    engine = copy.copy(get(slug))
    # Local adapter changes only data loading/execution coordinates. No registry mutation.
    engine.execution_adjust = "none"
    engine.warmup_bars = max(getattr(engine, "warmup_bars", 0), 160)
    ctx = prepare_backtest_context(store, engine, start=start, end=end,
        config=config(spec, end), source_evidence_mode="compact")
    computed = engine.compute(ctx["panels"], ctx["resolved_params"])
    candidates, old, native = extract(computed, slug)
    return ctx, computed, candidates, old, native, None


def evaluate(db, slug, segment, start, end, output, groups_path):
    spec = SPECS[slug]
    cfg = config(spec, end)
    cost = cfg.round_trip_cost_pct()
    print(f"Prepare {slug}/{segment}", flush=True)
    store = CutoffMarketStore(db, end)
    try:
        ctx, computed, candidates, old, native, ranker = prepare(store, slug, start, end, spec, groups_path)
        rank = ranker or (lambda s: rank_candidates(candidates, s, native, spec["top_n"]))
        scores, features = context_scores(ctx["panels"], old, spec)
        expected_baseline = rank(scores["baseline"])
        window = old.index >= start
        pd.testing.assert_frame_equal(expected_baseline.loc[window], computed.signals.loc[window])
        pd.testing.assert_frame_equal(expected_baseline.loc[start:end], ctx["signals"].loc[start:end].fillna(False).astype(bool))
        days = store.trading_days(start=str(old.index[0]), end=end)
        if list(old.index) != days:
            raise AssertionError("Market calendar compressed")
        cutoff = old.index[len(old)//2]
        prefix = {k: v.loc[:cutoff] if isinstance(v, pd.DataFrame) else v for k,v in ctx["panels"].items()}
        prefix_computed = ctx["engine"].compute(prefix, ctx["resolved_params"])
        pd.testing.assert_frame_equal(prefix_computed.signals, computed.signals.loc[:cutoff])
        prefix_scores, _ = context_scores(prefix, old.loc[:cutoff], spec)
        for key in scores:
            pd.testing.assert_frame_equal(prefix_scores[key], scores[key].loc[:cutoff])
        max_hold = spec["hold_days"] + 1
        mature = common_maturity_mask(old.index, start, end,
            entry_timing=ctx["engine"].entry_timing, max_hold=max_hold)
        base_keys = keys(expected_baseline.where(mature, False, axis=0))
        if not base_keys:
            raise ValueError(f"No mature baseline signals for {slug}/{segment}; verify data and industry coverage")
        rows, closed, daily_frames = {}, {}, []
        candidate_records = []
        for date, code in sorted(keys(candidates.where(mature, False, axis=0))):
            record = dict(signal_date=date, code=code, native_strength=float(native.at[date, code]))
            record.update({k: float(v.at[date, code]) for k,v in scores.items()})
            record.update({k: float(v.at[date, code]) for k,v in features.items()})
            candidate_records.append(record)
        pd.DataFrame(candidate_records).to_csv(output / f"{segment}-candidates.csv", index=False)
        for variant, score in scores.items():
            selected = expected_baseline if variant == "baseline" else rank(score)
            if spec["evidence"] != "daily_open_proxy":
                pd.testing.assert_series_equal(selected.sum(axis=1), expected_baseline.sum(axis=1))
            selected_keys = keys(selected.where(mature, False, axis=0))
            run = execute_split_context({**ctx, "signals": selected}, cfg, start, end, max_hold=max_hold)
            closed[variant] = run["closed_trades"]
            bundle = metrics(closed[variant], cost)
            for name, digits in (("trades",0),("avg_net_return",4),("win_rate",2),("profit_factor",3),("payoff_ratio",3)):
                val = bundle["base"][name]
                if val is not None and round(val, digits) != run["metrics"][name]:
                    raise AssertionError((name, val, run["metrics"][name]))
            outcomes = {trade_key(t): t for t in closed[variant]}
            base_outcomes = {trade_key(t): t for t in closed["baseline"]}
            for k in selected_keys & base_keys & outcomes.keys() & base_outcomes.keys():
                if not np.isclose(outcomes[k].net_return_pct, base_outcomes[k].net_return_pct, atol=1e-9, rtol=0):
                    raise AssertionError("Common signal execution mismatch")
            pd.DataFrame([t.to_dict(include_factors=True) for t in run["all_trades"]]).to_csv(output/f"{segment}-{variant}-trades.csv", index=False)
            signal_rows = [dict(signal_date=d, code=c, score=float(score.at[d,c]),
                baseline_selected=(d,c) in base_keys, closed=(d,c) in outcomes,
                opportunity_net_pct=outcomes[(d,c)].net_return_pct if (d,c) in outcomes else 0.) for d,c in sorted(selected_keys)]
            pd.DataFrame(signal_rows).to_csv(output/f"{segment}-{variant}-signals.csv", index=False)
            added, removed = selected_keys-base_keys, base_keys-selected_keys
            replacements = [dict(side=side,signal_date=d,code=c,
                net_pct=mapping[(d,c)].net_return_pct if (d,c) in mapping else 0.,closed=(d,c) in mapping)
                for side,group,mapping in (("added",added,outcomes),("removed",removed,base_outcomes)) for d,c in sorted(group)]
            pd.DataFrame(replacements,columns=["side","signal_date","code","net_pct","closed"]).to_csv(output/f"{segment}-{variant}-replacements.csv",index=False)
            daily = []
            for date in old.index[mature]:
                base_n = int(expected_baseline.loc[date].sum())
                n = int(selected.loc[date].sum())
                # Fixed native maximum slots if sector reordering changes occupancy.
                denominator = spec["top_n"] if spec["evidence"] == "daily_open_proxy" and (base_n or n) else base_n
                if not denominator:
                    continue
                net_sum = sum(t.net_return_pct for k,t in outcomes.items() if k[0] == date)
                base_sum = sum(t.net_return_pct for k,t in base_outcomes.items() if k[0] == date)
                daily.append(dict(segment=segment,variant=variant,signal_date=date,opportunities=denominator,
                    baseline_picks=base_n,selected_picks=n,net_sum=net_sum,delta_net_sum=net_sum-base_sum))
            daily_frame = pd.DataFrame(daily)
            daily_frames.append(daily_frame)
            rows[variant] = dict(metrics=bundle, accounting=run["accounting"],
                opportunity_mean=float(daily_frame.net_sum.sum()/daily_frame.opportunities.sum()) if len(daily_frame) else None,
                added_picks=len(added),removed_picks=len(removed),changed_days=len({d for d,c in added|removed}),
                added_metrics=independent_metrics([outcomes[k] for k in added if k in outcomes],cost),
                removed_metrics=independent_metrics([base_outcomes[k] for k in removed if k in base_outcomes],cost),
                paired_month_block_bootstrap=paired_bootstrap(daily_frame) if len(daily_frame) else None)
            m=bundle["base"]
            print(f"{slug}/{segment}/{variant}: {m}",flush=True)
        count=candidates.where(mature,False,axis=0).sum(axis=1)
        return dict(context=context_evidence(ctx),prefix_check=str(cutoff),
            baseline_reproduced=True,scope=dict(candidates=int(count.sum()),baseline_opportunities=len(base_keys),
            competitive_days=int(count.gt(spec["top_n"]).sum()),
            missing_context_candidates=int((candidates & ~features["context_valid"]).where(mature,False,axis=0).to_numpy().sum())),
            runs=rows),closed,daily_frames
    finally:
        store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--slug",choices=list(SPECS),required=True)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    parser.add_argument("--groups",type=Path)
    args=parser.parse_args()
    output=args.output/args.slug
    output.mkdir(parents=True,exist_ok=True)
    if (output/"PLAN.json").exists():
        raise FileExistsError("Do not overwrite a frozen study")
    before=sources(args.slug)
    dbhash=sha256(args.db)
    frozen=dict(created_at=now(),slug=args.slug,spec=SPECS[args.slug],variants=VARIANTS,splits=SPLITS,
        sources=before,snapshot_sha256=dbhash,groups_sha256=sha256(args.groups) if args.groups else None,
        features="P=120-session high/low position at fixed prepattern lag; B=min(P/.2,1,(1-P)/.5) clipped; R=C>MA20 and MA20>MA20.shift10; U=R and MA20>=MA60 and MA60>=MA60.shift10; trend lag as specified. Missing context retains S0.",
        ranking="All original candidates and market gates retained. Same TopN; score rounded4, native rank strength secondary, code ascending. Double-yin preserves sector exclusions.",
        nomination="Train-only mean>baseline AND original-opportunity mean>baseline AND PF>max(1,baseline), >=80 closed; order by opportunity mean, PF, lexical id. All frozen variants reported; no tuning.",
        limitations=["Retrospective observed periods, not untouched OOS", "Current membership/names and factor revisions, not strict PIT", "Independent event trades, not portfolio NAV", "Qianlong qfq absolute-price signal gate retained: split-end adjustment can change earlier absolute-price eligibility; prefix check on an already-adjusted panel does not eliminate that time bias. Raw execution and economic factors are separate.", "Double-yin proxy only; historical daily open and current sector mapping do not recreate 09:25 feeds; hold/stop is a research convention"])
    write_json(output/"PLAN.json",frozen)
    write_json(output/"freeze-receipt.json",dict(created_at=now(),plan_sha256=sha256(output/"PLAN.json")))
    summary=dict(slug=args.slug,spec=SPECS[args.slug],plan_sha256=sha256(output/"PLAN.json"),segments={})
    all_trades={k:[] for k in VARIANTS}
    all_daily=[]
    for segment,(start,end) in SPLITS.items():
        if sources(args.slug)!=before:
            raise AssertionError("Sources changed after freeze")
        result,trades,daily=evaluate(args.db,args.slug,segment,start,end,output,args.groups)
        summary["segments"][segment]=result
        for k in VARIANTS:
            all_trades[k].extend(trades[k])
        all_daily.extend(daily)
        write_json(output/f"{segment}-summary.json",result)
        if segment=="train":
            base=result["runs"]["baseline"]["metrics"]["base"]
            eligible=[k for k in VARIANTS if k!="baseline" and result["runs"][k]["metrics"]["base"]["trades"]>=80
                and result["runs"][k]["metrics"]["base"]["avg_net_return"]>base["avg_net_return"]
                and result["runs"][k]["opportunity_mean"]>result["runs"]["baseline"]["opportunity_mean"]
                and (result["runs"][k]["metrics"]["base"]["profit_factor"] or 0)>max(1,base["profit_factor"] or 0)]
            eligible.sort(key=lambda k:(-result["runs"][k]["opportunity_mean"],-result["runs"][k]["metrics"]["base"]["profit_factor"],k))
            summary["training_nomination"]=eligible[0] if eligible else None
            write_json(output/"training-nomination.json",dict(created_at=now(),nominee=summary["training_nomination"],plan_sha256=summary["plan_sha256"],train_sha256=sha256(output/"train-summary.json")))
    daily=pd.concat(all_daily,ignore_index=True)
    daily.to_csv(output/"paired-daily-results.csv",index=False)
    cost=config(SPECS[args.slug],"2026-09-30").round_trip_cost_pct()
    summary["pooled"]={}
    table=[]
    for k in VARIANTS:
        frame=daily[daily.variant.eq(k)]
        later=frame[frame.segment.ne("train")]
        summary["pooled"][k]=dict(metrics=metrics(all_trades[k],cost),
            opportunity_mean=float(frame.net_sum.sum()/frame.opportunities.sum()),
            paired_month_block_bootstrap=paired_bootstrap(frame),post_train_bootstrap=paired_bootstrap(later),
            added_picks=sum(s["runs"][k]["added_picks"] for s in summary["segments"].values()))
        for segment,r in summary["segments"].items():
            table.append(dict(segment=segment,variant=k,**r["runs"][k]["metrics"]["base"],opportunity_mean=r["runs"][k]["opportunity_mean"]))
        table.append(dict(segment="pooled",variant=k,**summary["pooled"][k]["metrics"]["base"],opportunity_mean=summary["pooled"][k]["opportunity_mean"]))
    pd.DataFrame(table).to_csv(output/"metrics.csv",index=False)
    if sources(args.slug)!=before or sha256(args.db)!=dbhash or (args.groups and sha256(args.groups)!=frozen["groups_sha256"]):
        raise AssertionError("Source or snapshot changed")
    summary.update(completed_at=now(),source_and_snapshot_unchanged=True)
    write_json(output/"summary.json",summary)
    print(json.dumps(dict(output=str(output),nomination=summary["training_nomination"])),flush=True)


if __name__=="__main__":
    main()
