"""Mechanism-led double-yin redesign in a read-only, daily-order proxy study.

No live strategy, jobs, accounts, source quotes, or existing research are edited.
All candidate definitions are frozen before this experiment's returns are read.
Previously observed baseline diagnostics are not new out-of-sample evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime
import json
import math
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _resolve_exit  # noqa: E402
from src.backtest.application.execution_contract import strict_price_masks  # noqa: E402
from src.backtest.domain.models import BacktestConfig, Trade  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore, common_maturity_mask, sha256  # noqa: E402
from tools.research_double_yin_scoring_proxy import prepare_proxy_context, rank_with_groups  # noqa: E402
from tools.research_impulse_scoring import paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

SLUG = "double-volume-yin-low-open-v1"
OUTPUT = ROOT / "docs/research/2026-10-04-double-yin-redesign"
DB = ROOT / ".local/multi-strategy-scoring-20261004/market.db"
GROUPS = ROOT / ".local/multi-strategy-scoring-20261004/candidate-industry-groups.json"
SPLITS = {
    "train": ("2024-01-01", "2025-06-30"),
    "validation_2025h2": ("2025-07-01", "2025-12-31"),
    "observed_2026": ("2026-01-01", "2026-09-30"),
}
VARIANTS = {
    "baseline": dict(label="原评分开盘买，4日/-6%", gate="all", rank="old", entry="open", exit="fixed"),
    "support_hold": dict(label="阴线守住前阳实体中点", gate="support", rank="old", entry="open", exit="fixed"),
    "safe_gap": dict(label="低开不破昨日低点且不超过2%", gate="gap", rank="old", entry="open", exit="fixed"),
    "quality_rank": dict(label="保留涨幅/阴线收盘/开盘承接重排", gate="all", rank="quality", entry="open", exit="fixed"),
    "quality_gate": dict(label="支撑与承接质量硬门", gate="quality", rank="quality", entry="open", exit="fixed"),
    "confirm_close": dict(label="当日收盘收复阴线收盘，次开买", gate="confirm", rank="old", entry="next_open", exit="fixed"),
    "reclaim_stop": dict(label="先定Top2，再挂收复昨日收盘买stop", gate="all", rank="old", entry="stop", exit="fixed"),
    "support_limit": dict(label="守前阳中点，开盘上方才挂中点限价", gate="limit", rank="old", entry="limit", exit="fixed"),
    "quality_stop": dict(label="质量硬门后挂收复阴线收盘买stop", gate="quality", rank="quality", entry="stop", exit="fixed"),
    "next_session_open": dict(label="原开盘买，最早合法次日开盘卖", gate="all", rank="old", entry="open", exit="next_open"),
    "next_session_close": dict(label="原开盘买，最早合法次日收盘卖", gate="all", rank="old", entry="open", exit="next_close"),
}


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def config(end: str) -> BacktestConfig:
    return BacktestConfig(
        hold_days=3, stop_loss_pct=-6., take_profit_pct=None, commission_bps=3,
        stamp_duty_bps=5, slippage_bps=5, benchmark=None, strict_limit_prices=True,
        economic_returns=True, valuation_end=end,
    )


def sources() -> dict[str, str]:
    names = (
        "tools/research_double_yin_redesign.py", "tools/research_double_yin_scoring_proxy.py",
        "tools/research_chinext_payoff_exits.py", "tools/research_impulse_scoring.py",
        "src/strategy/application/double_yin_low_open.py",
        "src/backtest/application/engine.py", "src/backtest/application/execution_contract.py",
        "src/backtest/domain/models.py", "src/market/infrastructure/store_panel.py",
    )
    return {name: sha256(ROOT / name) for name in names}


def plan() -> dict[str, Any]:
    return {
        "created_at": now(), "slug": SLUG, "variants": VARIANTS, "splits": SPLITS,
        "prior_observation": "The old strategy's loss and original training path diagnostics were already observed; these new rules are frozen before their own returns.",
        "definitions": {
            "origin": "T is the low-opening day; impulse=T-2, high-volume yin=T-1.",
            "midpoint": "(O(T-2)+C(T-2))/2",
            "retention": "clip((C(T-1)-O(T-2))/(C(T-2)-O(T-2)),0,1)",
            "yin_clv": "clip((C(T-1)-L(T-1))/(H(T-1)-L(T-1)),0,1)",
            "open_support": "clip((O(T)-L(T-1))/(C(T-1)-L(T-1)),0,1); zero if denominator<=0",
            "quality_score": "50*retention+30*yin_clv+20*open_support; rounded4",
            "support_gate": "C(T-1)>=midpoint AND L(T-1)>=O(T-2)",
            "gap_gate": "O(T)>L(T-1) AND O(T)/C(T-1)-1 >= -0.02",
            "quality_gate": "retention>=0.5 AND yin_clv>=0.35 AND O(T)>L(T-1) AND gap>=-0.03",
            "confirmation": "At T close, C(T)>O(T) AND C(T)>C(T-1), then next market session open entry",
            "stop_target": "C(T-1) rounded to cents + 0.01; order valid only after T opening and only for T",
            "limit_target": "floor(midpoint*100)/100; support_gate AND O(T)>target; order valid only for T",
        },
        "orders": {
            "allocation": "Original full candidates, missing sector excluded, greedy original group intersection exclusion and max2; rank BEFORE checking later touch; no refill for untriggered orders.",
            "decision_time": "All except confirm_close use prior closed candles and T opening only. confirm_close first becomes known at T close.",
            "stop_fill": "If open>=target, skip opening_already_crossed (no opening backfill). Otherwise high>=target fills target; high<target unfilled.",
            "limit_fill": "If open<=target, skip opening_already_crossed (no opening backfill). Otherwise low<=target fills target; low>target unfilled.",
            "tradability": "Positive observed daily volume/open, known adjusted previous-close limit reference; reject upper-limit opening and stop target at/above upper limit.",
            "corporate_actions": "For stop compare T-1 versus T adjustment factors, for limit T-2 versus T; any change cancels the source-price order as non-comparable, with reason counted. Current factors are revisioned retrospective evidence, not strict PIT.",
            "uncertainty": "Daily high/low prove a touch, not queue priority or exact post-order intraday fill. These are explicitly daily-order proxies, not historical 09:25 replay.",
        },
        "exits": {
            "fixed": "4 market sessions including entry; -6% stop from entry+1; existing _resolve_exit handles gap/slippage convention and limit/suspension delays; no take profit.",
            "next_open": "Earliest legal entry+1 open; no same-day sale, no fixed stop; if no valid opening or opening limit-down, defer to next tradable opening.",
            "next_close": "Earliest legal entry+1 close; no fixed stop; existing exit tradability rules defer suspension/close-at-limit-down.",
            "interpretation": "All exits are research conventions; the original live double-yin selector has no intrinsic holding/exit rule.",
        },
        "comparison": {
            "cost_pct": .21, "stress_cost_pct": .42,
            "common_maturity": "5 sessions from origin T: allows confirmation at T close, entry T+1 and 4-session holding; all variants including original use the same origin-date window.",
            "budget": "Exactly 2 slots on each original mature baseline-active origin date; filtered/unfilled/unused slots earn zero. Filled but censored positions remain unresolved: opportunity mean, paired CI and nomination are unavailable when any exist. Also report closed-trade mean and fill retention.",
            "baseline": "Original open entry and fixed exit must reproduce old-study baseline trades on the common mature origin-date subset.",
        },
        "selection": {
            "maximum_shortlist": 2,
            "eligible": "Train net mean>0, PF>1, original two-slot opportunity mean>baseline, and double-cost+largest-winner-removed mean>0; no fixed 80-trade cutoff.",
            "order": "Eligible first by original-budget mean descending, PF descending, lexical id.",
            "fallback": "If no eligible candidate, follow at most two candidates with budget improvement by the same ordering, labelled diagnostic_only, never qualified recommendations.",
            "uncertainty": "Counts, retention, winner sensitivity and monthly block intervals reported; a small sample can be shortlisted but cannot be called robust.",
            "later": "Freeze the maximum two training selections and then evaluate only them plus baseline in the later observed periods. No retuning or retrospective replacement.",
        },
        "diagnostics": "Training only: all original shape candidates under baseline execution grouped by fixed retention, yin close position, gap, support and volume bands; original Top2 entry-day/overnight marks and exit attribution. These do not create extra tuned rules.",
        "limitations": [
            "All time segments already observed historically, not untouched out-of-sample.",
            "Current instrument names/status and current EM2016 groups; no historical membership/PIT reconstruction.",
            "Raw daily-bar shape convention and current adjustment-factor revisions retained.",
            "Independent trade events; no portfolio NAV, sizing or liquidity-capacity claim.",
            "Day-of-entry MFE/MAE include full-day extremes, including pre-fill or post-exit points; not realizable intraday path.",
            "Multiple fixed hypotheses and selective follow-up remain vulnerable to data snooping; descriptive confidence intervals have no multiple-testing correction.",
        ],
        "sources": sources(), "snapshot_sha256": sha256(DB), "groups_sha256": sha256(GROUPS),
    }


def features(ctx: dict[str, Any]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    p = ctx["panels"]
    o, h, l, c, v = (p[k] for k in ("open", "high", "low", "close", "volume"))
    body = c.shift(2)-o.shift(2)
    midpoint = (c.shift(2)+o.shift(2))/2
    retained_unclipped = (c.shift(1)-o.shift(2))/body.where(body.gt(0))
    retention = retained_unclipped.clip(0, 1)
    prior_range = h.shift(1)-l.shift(1)
    yin_clv = ((c.shift(1)-l.shift(1))/prior_range.where(prior_range.gt(0))).clip(0, 1)
    support_width = c.shift(1)-l.shift(1)
    open_support = ((o-l.shift(1))/support_width.where(support_width.gt(0))).clip(0, 1).fillna(0)
    gap = o/c.shift(1)-1
    quality = (50*retention+30*yin_clv+20*open_support).clip(0, 100).round(4)
    stop_target = (np.floor(c.shift(1)*100+.5+1e-9)+1)/100
    limit_target = np.floor(midpoint*100+1e-9)/100
    support = c.shift(1).ge(midpoint) & l.shift(1).ge(o.shift(2))
    gates = {
        "all": pd.DataFrame(True, index=c.index, columns=c.columns),
        "support": support,
        "gap": o.gt(l.shift(1)) & gap.ge(-.02),
        "quality": retention.ge(.5) & yin_clv.ge(.35) & o.gt(l.shift(1)) & gap.ge(-.03),
        "confirm": c.gt(o) & c.gt(c.shift(1)),
        "limit": support & o.gt(limit_target),
    }
    return {
        "retention": retention, "retained_unclipped": retained_unclipped, "yin_clv": yin_clv,
        "open_support": open_support, "gap_pct": gap*100,
        "prior_low_support_pct": (o/l.shift(1)-1)*100,
        "volume_ratio": v.shift(1)/v.shift(2),
        "quality": quality, "midpoint": midpoint,
        "stop_target": stop_target, "limit_target": limit_target,
    }, {key: value.fillna(False).astype(bool) for key, value in gates.items()}


def order_fill(mode: str, open_price: float, high: float, low: float, target: float | None) -> tuple[float | None, str]:
    """No opening backfill after an opening-derived order decision."""
    if not math.isfinite(open_price) or open_price <= 0:
        return None, "invalid_open"
    if mode in {"open", "next_open"}:
        return open_price, "filled"
    if target is None or not math.isfinite(target) or target <= 0:
        return None, "invalid_target"
    if mode == "stop":
        if open_price >= target:
            return None, "opening_already_crossed"
        return (target, "filled") if math.isfinite(high) and high >= target else (None, "not_triggered")
    if mode == "limit":
        if open_price <= target:
            return None, "opening_already_crossed"
        return (target, "filled") if math.isfinite(low) and low <= target else (None, "not_triggered")
    raise ValueError(f"Unsupported order mode: {mode}")


def execution_arrays(ctx: dict[str, Any]) -> dict[str, Any]:
    p = ctx["execution_panels"]
    data = {key: p[key].to_numpy(dtype=float) for key in ("open", "high", "low", "close", "volume")}
    data["factors"] = p["__adjust_factor"].to_numpy(dtype=float)
    data["dates"], data["codes"] = list(p["close"].index), list(p["close"].columns)
    strict_entry, strict_down, known = strict_price_masks(
        data["open"], data["close"], data["factors"], data["codes"], data["volume"],
    )
    data.update(strict_entry=strict_entry, strict_down=strict_down, known=known)
    quoted = np.isfinite(data["close"]) & (data["close"] > 0) & (data["volume"] > 0)
    previous_close = pd.DataFrame(data["close"]).where(quoted).ffill().shift(1).to_numpy()
    previous_factor = pd.DataFrame(data["factors"]).where(quoted).ffill().shift(1).to_numpy()
    reference = previous_close*previous_factor/data["factors"]
    data["upper"] = np.floor(reference*1.1*100+.5+1e-9)/100
    data["lower"] = np.floor(reference*.9*100+.5+1e-9)/100
    for key in ("open", "high", "low", "close"):
        data[f"economic_{key}"] = data[key]*data["factors"]
    return data


def next_legal_open(data: dict, entry: int, col: int) -> tuple[int | None, float, str]:
    for idx in range(entry+1, len(data["dates"])):
        price = data["open"][idx, col]
        if not (np.isfinite(price) and price > 0 and data["volume"][idx, col] > 0):
            continue
        if not data["known"][idx, col] or price <= data["lower"][idx, col]+.005:
            continue
        return idx, float(data["economic_open"][idx, col]), "next_session_open"
    return None, 0., "data_end"


def execute(
    ctx: dict, selected: pd.DataFrame, spec: dict, feat: dict, data: dict,
) -> tuple[list[Trade], list[dict], dict[str, int]]:
    """Research orders only; reuse unchanged production exit behavior."""
    cfg = ctx["config"]
    rows, cols = np.nonzero(selected.to_numpy(dtype=bool))
    closed, events, counts = [], [], Counter()
    for row, col in zip(rows.tolist(), cols.tolist()):
        entry = row + (spec["entry"] == "next_open")
        day, code = str(data["dates"][row]), str(data["codes"][col])
        target = None
        if spec["entry"] in {"stop", "limit"}:
            target = float(feat[f"{spec['entry']}_target"].iat[row, col])
        event = dict(signal_date=day, code=code, decision_time="close" if spec["entry"] == "next_open" else "opening",
                     order_mode=spec["entry"], order_target=target, status="", opportunity_net_pct=0.)
        if entry < len(data["dates"]):
            event.update(entry_session=str(data["dates"][entry]), entry_open=float(data["open"][entry, col]),
                         entry_high=float(data["high"][entry, col]), entry_low=float(data["low"][entry, col]),
                         fill_assumption="daily_touch_proxy" if spec["entry"] in {"stop", "limit"} else "daily_open_proxy")
            if spec["entry"] in {"stop", "limit"}:
                source_row = row-(1 if spec["entry"] == "stop" else 2)
                event["source_factor_ratio"] = float(data["factors"][entry, col]/data["factors"][source_row, col])
                event["touch_margin_ticks"] = float((
                    data["high"][entry, col]-target if spec["entry"] == "stop"
                    else target-data["low"][entry, col]
                )*100)
        if entry >= len(data["dates"]):
            reason, price = "entry_out_of_range", None
        elif not data["volume"][entry, col] > 0:
            reason, price = "suspended_entry", None
        elif not data["known"][entry, col]:
            reason, price = "unknown_limit_reference", None
        elif data["strict_entry"][entry, col]:
            reason, price = "upper_limit_opening", None
        elif spec["entry"] in {"stop", "limit"} and not math.isclose(event["source_factor_ratio"], 1., abs_tol=1e-10, rel_tol=0):
            reason, price = "corporate_action_coordinate_change", None
        elif spec["entry"] == "stop" and target >= data["upper"][entry, col]-.005:
            reason, price = "stop_target_at_upper_limit", None
        else:
            price, reason = order_fill(
                spec["entry"], data["open"][entry, col], data["high"][entry, col],
                data["low"][entry, col], target,
            )
        if price is None:
            counts[reason] += 1
            events.append({**event, "status": reason})
            continue
        entry_factor = float(data["factors"][entry, col])
        basis = price*entry_factor
        exit_cfg = cfg if spec["exit"] == "fixed" else replace(cfg, hold_days=1, stop_loss_pct=None)
        if spec["exit"] == "next_open":
            exit_idx, exit_price, exit_reason = next_legal_open(data, entry, col)
        else:
            exit_idx, exit_price, exit_reason = _resolve_exit(
                col=col, entry_idx=entry, entry_price=basis,
                planned_exit=entry+exit_cfg.hold_days, cfg=exit_cfg,
                high_a=data["economic_high"], low_a=data["economic_low"],
                close_a=data["economic_close"], open_a=data["economic_open"],
                one_word_down=data["strict_down"], volume_a=data["volume"],
                last_index=len(data["dates"])-1,
            )
        if exit_idx is None or exit_reason == "data_end" or not np.isfinite(exit_price) or exit_price <= 0:
            counts["data_end"] += 1
            events.append({**event, "status": "data_end", "entry_date": str(data["dates"][entry]),
                           "entry_price": price, "opportunity_net_pct": None})
            continue
        if exit_idx <= entry:
            raise AssertionError("Newly bought shares cannot be sold on the entry day")
        exit_factor = float(data["factors"][exit_idx, col])
        raw_exit = float(exit_price/exit_factor)
        for raw, economic in ((data["close"], data["economic_close"]), (data["open"], data["economic_open"])):
            if exit_price == economic[exit_idx, col]:
                raw_exit = float(raw[exit_idx, col])
                break
        gross = (exit_price/basis-1)*100
        window = slice(entry, exit_idx+1)
        live = data["volume"][window, col] > 0
        highs, lows = data["economic_high"][window, col][live], data["economic_low"][window, col][live]
        trade = Trade(
            code=code, signal_date=day, entry_date=str(data["dates"][entry]), entry_price=float(price),
            exit_date=str(data["dates"][exit_idx]), exit_price=raw_exit,
            hold_days=exit_idx-entry, gross_return_pct=float(gross),
            net_return_pct=float(gross-cfg.round_trip_cost_pct()),
            mae_pct=float((np.nanmin(lows)/basis-1)*100), mfe_pct=float((np.nanmax(highs)/basis-1)*100),
            exit_reason=exit_reason, entry_factor=entry_factor, exit_factor=exit_factor,
        )
        assert math.isclose((trade.exit_price*trade.exit_factor/(trade.entry_price*trade.entry_factor)-1)*100,
                            trade.gross_return_pct, abs_tol=1e-8)
        closed.append(trade)
        counts["closed"] += 1
        events.append({**event, "status": "closed", "entry_date": trade.entry_date,
                       "entry_price": trade.entry_price, "exit_date": trade.exit_date,
                       "exit_price": trade.exit_price, "exit_reason": exit_reason,
                       "opportunity_net_pct": trade.net_return_pct})
    if sum(counts.values()) != len(rows):
        raise AssertionError("Selected-order accounting does not balance")
    return closed, events, dict(counts)


def metric(values: list[float] | np.ndarray) -> dict[str, Any]:
    arr = np.asarray(values, dtype=float)
    wins, losses = arr[arr > 0], arr[arr <= 0]
    return {
        "trades": len(arr), "avg_net_return": float(arr.mean()) if arr.size else None,
        "win_rate": float(100*len(wins)/len(arr)) if arr.size else None,
        "profit_factor": float(wins.sum()/-losses.sum()) if losses.sum() < 0 else None,
        "payoff_ratio": float(wins.mean()/-losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else None,
        "avg_win": float(wins.mean()) if len(wins) else None, "avg_loss": float(losses.mean()) if len(losses) else None,
        "worst_net": float(arr.min()) if arr.size else None,
    }


def metrics(trades: list[Trade]) -> dict[str, Any]:
    values = np.array([t.net_return_pct for t in trades])
    reduced = np.delete(values, int(np.argmax(values))) if values.size else values
    return {
        "base": metric(values), "double_cost": metric(values-.21),
        "largest_winner_removed": metric(reduced),
        "double_cost_largest_winner_removed": metric(reduced-.21),
    }


def mask_keys(mask: pd.DataFrame) -> set[tuple[str, str]]:
    rows, cols = np.nonzero(mask.to_numpy(dtype=bool))
    return {(str(mask.index[r]), str(mask.columns[c])) for r, c in zip(rows, cols)}


def baseline_check(segment: str, trades: list[Trade], origin_keys: set[tuple[str, str]]) -> None:
    path = ROOT / f"docs/research/2026-10-04-multi-strategy-scoring/{SLUG}/{segment}-baseline-trades.csv"
    previous = pd.read_csv(path, dtype={"code": str, "signal_date": str, "entry_date": str, "exit_date": str})
    expected = {(r.signal_date, r.code): r for r in previous.itertuples() if (r.signal_date, r.code) in origin_keys}
    observed = {(t.signal_date, t.code): t for t in trades}
    if observed.keys() != expected.keys():
        raise AssertionError("Baseline trade keys differ on the common mature opportunity set")
    for key, trade in observed.items():
        prior = expected[key]
        if trade.entry_date != prior.entry_date or trade.exit_date != prior.exit_date or trade.exit_reason != prior.exit_reason:
            raise AssertionError("Baseline execution dates/reason changed")
        if not math.isclose(trade.net_return_pct, prior.net_return_pct, abs_tol=1e-9):
            raise AssertionError("Baseline net return changed")


def diagnose_training(ctx: dict, candidates: pd.DataFrame, baseline: pd.DataFrame, feat: dict, data: dict) -> dict:
    trades, events, accounting = execute(ctx, candidates, VARIANTS["baseline"], feat, data)
    indexed = {(t.signal_date, t.code): t for t in trades}
    rows = []
    for day, code in sorted(mask_keys(candidates)):
        trade = indexed.get((day, code))
        if trade is None:
            continue
        i, j = candidates.index.get_loc(day), candidates.columns.get_loc(code)
        basis = trade.entry_price*trade.entry_factor
        row = dict(signal_date=day, code=code, original_top2=bool(baseline.at[day, code]),
                   net_return_pct=trade.net_return_pct, exit_reason=trade.exit_reason)
        row.update({key: float(feat[key].iat[i, j]) for key in (
            "retained_unclipped", "yin_clv", "gap_pct", "prior_low_support_pct", "volume_ratio", "quality",
        )})
        for label, offset, price in (("entry_day_close_mark", 0, "close"), ("next_open_mark", 1, "open"),
                                     ("next_close_mark", 1, "close"), ("fourth_close_mark", 3, "close")):
            value = data[f"economic_{price}"][i+offset, j]
            row[label] = float((value/basis-1)*100) if np.isfinite(value) and value > 0 else None
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUTPUT / "train-shape-diagnostics.csv", index=False)
    bands = {
        "retained_unclipped": [-np.inf, 0, .5, 1, np.inf],
        "yin_clv": [-np.inf, .25, .5, .75, np.inf],
        "gap_pct": [-np.inf, -3, -1, 0],
        "prior_low_support_pct": [-np.inf, 0, np.inf],
        "volume_ratio": [2-1e-9, 3, 4, 6, np.inf],
        "quality": [-np.inf, 25, 50, 75, np.inf],
    }
    grouped = {}
    for feature, cuts in bands.items():
        bucket = pd.cut(frame[feature], cuts, include_lowest=True)
        grouped[feature] = {
            str(key): metric(part.net_return_pct.to_numpy())
            for key, part in frame.groupby(bucket, observed=True)
        }
    top = frame[frame.original_top2]
    return {
        "all_candidate_execution": accounting, "fixed_feature_bands": grouped,
        "original_top2_exit_attribution": {
            str(key): metric(part.net_return_pct.to_numpy()) for key, part in top.groupby("exit_reason")
        },
        "original_top2_gross_marks_not_trades": {
            label: float(top[label].mean()) for label in (
                "entry_day_close_mark", "next_open_mark", "next_close_mark", "fourth_close_mark",
            )
        },
        "warning": "Marks ignore execution/fees and same-day sale is forbidden. Intraday entry-day rebound is not an executable T+0 profit.",
    }


def evaluate(segment: str, variants: list[str]) -> dict:
    start, end = SPLITS[segment]
    store = CutoffMarketStore(DB, end)
    try:
        ctx, computed, original_candidates, old, _, _ = prepare_proxy_context(store, start, end, config(end), GROUPS)
        feat, gates = features(ctx)
        sector_groups = ctx["panels"]["__sector_groups__"]
        mature = common_maturity_mask(old.index, start, end, entry_timing="open", max_hold=5)
        candidates = original_candidates.where(mature, False, axis=0)
        baseline = computed.signals.where(mature, False, axis=0)
        active_dates = baseline.index[baseline.any(axis=1)]
        original_keys = mask_keys(baseline)
        if not len(active_dates):
            raise ValueError("No original mature baseline opportunities")
        data = execution_arrays(ctx)
        cutoff = old.index[len(old)//2]
        prefix = {k: v.loc[:cutoff] if isinstance(v, pd.DataFrame) else v for k, v in ctx["panels"].items()}
        prefix_feat, prefix_gates = features({"panels": prefix})
        for key in feat:
            pd.testing.assert_frame_equal(prefix_feat[key], feat[key].loc[:cutoff])
        for key in gates:
            pd.testing.assert_frame_equal(prefix_gates[key], gates[key].loc[:cutoff])
        candidate_rows = []
        for day, code in sorted(mask_keys(candidates)):
            record = dict(signal_date=day, code=code, old_score=float(old.at[day, code]),
                          original_selected=(day, code) in original_keys)
            record.update({key: float(value.at[day, code]) for key, value in feat.items()})
            record.update({f"gate_{key}": bool(value.at[day, code]) for key, value in gates.items()})
            candidate_rows.append(record)
        pd.DataFrame(candidate_rows).to_csv(OUTPUT / f"{segment}-candidates.csv", index=False)
        rows, all_daily, baseline_outcomes, baseline_censored = {}, [], {}, set()
        for name in variants:
            spec = VARIANTS[name]
            eligible = candidates & gates[spec["gate"]]
            score = old if spec["rank"] == "old" else feat["quality"].where(original_candidates)
            selected, _, _ = rank_with_groups(eligible, score, sector_groups, top_n=2)
            if name == "baseline":
                pd.testing.assert_frame_equal(selected, baseline)
            trades, events, counts = execute(ctx, selected, spec, feat, data)
            trade_fields = list(Trade.__dataclass_fields__)
            pd.DataFrame([t.to_dict(include_factors=True) for t in trades], columns=trade_fields).to_csv(
                OUTPUT / f"{segment}-{name}-trades.csv", index=False,
            )
            pd.DataFrame(events, columns=[
                "signal_date", "code", "decision_time", "order_mode", "order_target", "status",
                "entry_date", "entry_price", "exit_date", "exit_price", "exit_reason", "opportunity_net_pct",
                "entry_session", "entry_open", "entry_high", "entry_low", "fill_assumption",
                "source_factor_ratio", "touch_margin_ticks",
            ]).to_csv(OUTPUT / f"{segment}-{name}-orders.csv", index=False)
            outcomes = {(t.signal_date, t.code): t.net_return_pct for t in trades}
            if name == "baseline":
                baseline_check(segment, trades, original_keys)
                baseline_outcomes = outcomes
                baseline_censored = {event["signal_date"] for event in events if event["status"] == "data_end"}
            censored_dates = {event["signal_date"] for event in events if event["status"] == "data_end"}
            daily = []
            for day in active_dates:
                net = sum(v for (d, _), v in outcomes.items() if d == day)
                base_net = sum(v for (d, _), v in baseline_outcomes.items() if d == day)
                daily.append(dict(segment=segment, variant=name, signal_date=str(day), opportunities=2,
                                  selected_orders=int(selected.loc[day].sum()),
                                  closed_trades=sum(d == day for d, _ in outcomes),
                                  unresolved_positions=sum(event["signal_date"] == day and event["status"] == "data_end" for event in events),
                                  net_sum=None if day in censored_dates else net,
                                  delta_net_sum=None if day in censored_dates or day in baseline_censored else net-base_net))
            dayframe = pd.DataFrame(daily)
            all_daily.extend(daily)
            bundle = metrics(trades)
            rows[name] = {
                "label": spec["label"], "metrics": bundle, "accounting": counts,
                "eligible_shape_events": int(eligible.to_numpy().sum()),
                "selected_orders": int(selected.to_numpy().sum()), "closed": len(trades),
                "unresolved_positions": counts.get("data_end", 0),
                "fixed_budget_slots": 2*len(active_dates),
                "unused_or_unfilled_slots": 2*len(active_dates)-len(trades)-counts.get("data_end", 0),
                "original_selected_events": len(original_keys),
                "fill_retention_pct_of_original": 100*(len(trades)+counts.get("data_end", 0))/len(original_keys),
                "opportunity_mean": None if censored_dates else float(dayframe.net_sum.sum()/dayframe.opportunities.sum()),
                "monthly_blocks": None if censored_dates or baseline_censored else paired_bootstrap(dayframe),
                "per_month": {str(month): {
                    "net_sum": None if part.net_sum.isna().any() else float(part.net_sum.sum()),
                    "slots": int(part.opportunities.sum()), "closed": int(part.closed_trades.sum()),
                    "unresolved_positions": int(part.unresolved_positions.sum()),
                    "opportunity_mean": None if part.net_sum.isna().any() else float(part.net_sum.sum()/part.opportunities.sum()),
                } for month, part in dayframe.groupby(dayframe.signal_date.str[:7])},
            }
            print(json.dumps(dict(segment=segment, variant=name, closed=len(trades),
                                  avg_net=bundle["base"]["avg_net_return"], pf=bundle["base"]["profit_factor"],
                                  opportunity_mean=rows[name]["opportunity_mean"]), ensure_ascii=False), flush=True)
        pd.DataFrame(all_daily).to_csv(OUTPUT / f"{segment}-paired-daily.csv", index=False)
        result = {
            "segment": segment, "origin_start": start, "origin_end": end,
            "last_mature_origin": str(mature.index[mature][-1]),
            "original_candidate_events": int(candidates.to_numpy().sum()),
            "original_selected_events": len(original_keys), "original_active_days": len(active_dates),
            "fixed_budget_slots": 2*len(active_dates), "prefix_check": str(cutoff),
            "baseline_original_common_subset_reproduced": True,
            "proxy_evidence": ctx["data_snapshot"]["research_proxy"], "runs": rows,
        }
        if segment == "train":
            result["loss_diagnostics"] = diagnose_training(ctx, candidates, baseline, feat, data)
        write_json(OUTPUT / f"{segment}-summary.json", result)
        return result
    finally:
        store.close()


def shortlist(train: dict) -> dict:
    base = train["runs"]["baseline"]["opportunity_mean"]
    candidates = []
    eligible = []
    for name, result in train["runs"].items():
        if name == "baseline":
            continue
        m = result["metrics"]["base"]
        if base is not None and result["opportunity_mean"] is not None and result["opportunity_mean"] > base and m["trades"]:
            candidates.append(name)
            stress = result["metrics"]["double_cost_largest_winner_removed"]["avg_net_return"]
            if m["avg_net_return"] > 0 and (m["profit_factor"] or 0) > 1 and stress is not None and stress > 0:
                eligible.append(name)
    rank = lambda name: (-train["runs"][name]["opportunity_mean"],
                         -(train["runs"][name]["metrics"]["base"]["profit_factor"] or 0), name)
    chosen = sorted(eligible or candidates, key=rank)[:2]
    return {
        "created_at": now(), "selected": chosen, "qualified": sorted(eligible),
        "status": "qualified_training_candidates" if eligible else "diagnostic_only_no_qualified_candidate",
        "unassessable_due_to_censoring": [name for name, result in train["runs"].items() if result["opportunity_mean"] is None],
        "train_sha256": sha256(OUTPUT / "train-summary.json"),
        "plan_sha256": sha256(OUTPUT / "PLAN.json"),
    }


def self_check() -> dict:
    assert order_fill("stop", 9., 10.2, 8., 10.) == (10., "filled")
    assert order_fill("stop", 10.5, 11., 10.2, 10.) == (None, "opening_already_crossed")
    assert order_fill("stop", 9., 9.9, 8., 10.) == (None, "not_triggered")
    assert order_fill("limit", 10., 11., 8.8, 9.) == (9., "filled")
    assert order_fill("limit", 8.5, 9.5, 8., 9.) == (None, "opening_already_crossed")
    assert order_fill("limit", 10., 11., 9.1, 9.) == (None, "not_triggered")
    try:
        order_fill("buy_stop", 9., 11., 8., 10.)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsupported entry must never silently become open")
    dates = pd.Index([f"2025-01-{d:02d}" for d in range(1, 9)])
    close = pd.DataFrame([10., 10., 11., 10.6, 10.7, 10.8, 10.9, 11.], index=dates, columns=["600001"])
    p = {"close": close, "open": close-.1, "high": close+.2, "low": close-.3,
         "volume": close*100}
    a, gates = features({"panels": p})
    changed = {key: frame.copy() for key, frame in p.items()}
    for key in ("close", "high", "low", "volume"):
        changed[key].iloc[-1] *= 2
    b, later_gates = features({"panels": changed})
    for key in a:
        pd.testing.assert_series_equal(a[key].iloc[-1], b[key].iloc[-1])
    for key in gates.keys()-{"confirm"}:
        pd.testing.assert_series_equal(gates[key].iloc[-1], later_gates[key].iloc[-1])
    mature = common_maturity_mask(dates, str(dates[0]), str(dates[-1]), entry_timing="open", max_hold=5)
    assert list(mature[mature].index) == list(dates[:4])
    arr = np.array([[10.], [9.3], [10.], [10.]])
    lows = np.array([[8.], [9.2], [9.9], [9.9]])
    idx, price, reason = _resolve_exit(
        col=0, entry_idx=0, entry_price=10., planned_exit=3, cfg=config("2025-01-04"),
        high_a=arr+.3, low_a=lows, close_a=arr+.1, open_a=arr,
        one_word_down=np.zeros((4, 1), dtype=bool), volume_a=np.ones((4, 1)), last_index=3,
    )
    assert idx == 1 and price == 9.3 and reason == "stop_loss"
    return {"status": "passed", "checks": [
        "buy_stop_fills_target_not_prior_open", "stop_open_gap_not_backfilled", "stop_not_touched",
        "limit_fills_target", "limit_open_gap_not_backfilled", "limit_not_touched",
        "unknown_entry_fails", "opening_features_ignore_same_day_HLCV", "only_close_confirmation_uses_today_close",
        "common_maturity_covers_delayed_entry", "no_T0_stop_and_next_day_gap_uses_worse_open",
    ]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "train", "evaluate", "self-check"])
    args = parser.parse_args()
    if args.phase == "self-check":
        print(json.dumps(self_check(), ensure_ascii=False, indent=2))
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.phase == "freeze":
        if (OUTPUT / "PLAN.json").exists():
            raise FileExistsError("Frozen plan already exists; do not replace it after seeing returns")
        write_json(OUTPUT / "PLAN.json", plan())
        write_json(OUTPUT / "self-check.json", self_check())
        print(json.dumps({"plan_sha256": sha256(OUTPUT / "PLAN.json")}), flush=True)
        return
    frozen = json.loads((OUTPUT / "PLAN.json").read_text(encoding="utf-8"))
    if sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"] or sha256(GROUPS) != frozen["groups_sha256"]:
        raise AssertionError("Frozen source/data/group evidence changed")
    if args.phase == "train":
        if (OUTPUT / "training-shortlist.json").exists():
            raise FileExistsError("Training shortlist already frozen")
        train = evaluate("train", list(VARIANTS))
        selected = shortlist(train)
        write_json(OUTPUT / "training-shortlist.json", selected)
        print(json.dumps(selected, ensure_ascii=False), flush=True)
        return
    selected = json.loads((OUTPUT / "training-shortlist.json").read_text(encoding="utf-8"))
    if selected["train_sha256"] != sha256(OUTPUT / "train-summary.json") or selected["plan_sha256"] != sha256(OUTPUT / "PLAN.json"):
        raise AssertionError("Training nomination changed after later evaluation")
    stages = {"train": json.loads((OUTPUT / "train-summary.json").read_text(encoding="utf-8"))}
    for segment in ("validation_2025h2", "observed_2026"):
        if (OUTPUT / f"{segment}-summary.json").exists():
            raise FileExistsError("Later-stage results already exist")
        stages[segment] = evaluate(segment, ["baseline", *selected["selected"]])
    if sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"] or sha256(GROUPS) != frozen["groups_sha256"]:
        raise AssertionError("Source/data/group changed during evaluation")
    pooled = {}
    for name in ["baseline", *selected["selected"]]:
        trades, days = [], []
        for segment in SPLITS:
            frame = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str})
            trades.extend(Trade(**row) for row in frame.to_dict("records"))
            daily = pd.read_csv(OUTPUT / f"{segment}-paired-daily.csv")
            days.append(daily[daily.variant.eq(name)])
        all_days = pd.concat(days, ignore_index=True)
        later = all_days[all_days.segment.ne("train")]
        pooled[name] = {
            "metrics": metrics(trades),
            "unresolved_positions": int(all_days.unresolved_positions.sum()),
            "opportunity_mean": None if all_days.net_sum.isna().any() else float(all_days.net_sum.sum()/all_days.opportunities.sum()),
            "fixed_budget_slots": int(all_days.opportunities.sum()),
            "post_train_opportunity_mean": None if later.net_sum.isna().any() else float(later.net_sum.sum()/later.opportunities.sum()),
            "post_train_month_blocks": None if later.delta_net_sum.isna().any() else paired_bootstrap(later),
            "all_month_blocks": None if all_days.delta_net_sum.isna().any() else paired_bootstrap(all_days),
        }
    write_json(OUTPUT / "summary.json", {
        "completed_at": now(), "evidence_mode": "daily_open_and_intraday_order_proxy_only",
        "shortlist": selected, "segments": stages, "pooled": pooled,
        "plan_sha256": sha256(OUTPUT / "PLAN.json"), "source_snapshot_groups_unchanged": True,
    })
    print(json.dumps({"completed": True, "shortlist": selected["selected"]}), flush=True)


if __name__ == "__main__":
    main()
