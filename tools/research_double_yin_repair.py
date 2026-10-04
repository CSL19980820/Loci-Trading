"""Frozen, causal multi-session repair study; research artifacts only.

No live selector guard is disabled. Full daily openings are proxies, and current
industry/factor revisions are not historical point-in-time observations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _resolve_exit  # noqa: E402
from src.backtest.domain.models import Trade  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore, common_maturity_mask, sha256  # noqa: E402
from tools.research_double_yin_redesign import (  # noqa: E402
    baseline_check, config, execute, execution_arrays, mask_keys, metrics,
)
from tools.research_double_yin_scoring_proxy import prepare_proxy_context, rank_with_groups  # noqa: E402
from tools.research_impulse_scoring import paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-double-yin-repair"
DB = ROOT / ".local/multi-strategy-scoring-20261004/market.db"
OLD_GROUPS = ROOT / ".local/multi-strategy-scoring-20261004/candidate-industry-groups.json"
GROUPS = OUTPUT / "industry-groups.json"
SPLITS = {
    "train": ("2024-01-01", "2025-06-30"),
    "validation_2025h2": ("2025-07-01", "2025-12-31"),
    "observed_2026": ("2026-01-01", "2026-09-30"),
}
CONTROLS = ["original_baseline", "corrected_baseline"]
VARIANTS = {
    "one_dry_fixed": {"base": "one", "exit": "fixed"},
    "one_dry_structural": {"base": "one", "exit": "structural"},
    "two_dry_fixed": {"base": "two", "exit": "fixed"},
    "two_dry_structural": {"base": "two", "exit": "structural"},
}


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sources() -> dict[str, str]:
    names = [
        "tools/research_double_yin_repair.py", "tools/research_double_yin_redesign.py",
        "tools/research_double_yin_scoring_proxy.py", "tools/research_chinext_payoff_exits.py",
        "tools/research_impulse_scoring.py", "src/strategy/application/double_yin_low_open.py",
        "src/backtest/application/engine.py", "src/backtest/application/execution_contract.py",
        "src/backtest/domain/models.py", "src/market/infrastructure/store_panel.py",
    ]
    return {name: sha256(ROOT / name) for name in names}


def coordinate_inputs(ctx: dict) -> dict:
    """Recompute full historical shape and ranking in one economic coordinate.

    price_floor=0 is essential: six yuan is a raw executable price, never a
    six-unit threshold in a factor-scaled economic price series.
    """
    factors = ctx["execution_panels"]["__adjust_factor"]
    p = ctx["panels"]
    economic = {**p, **{key: p[key]*factors for key in ("open", "high", "low", "close")}}
    computed = ctx["engine"].compute(economic, {**ctx["resolved_params"], "price_floor": 0.})
    low_open = computed.factors["条件候选"] & p["open"].gt(6)
    corrected, _, _ = rank_with_groups(low_open, computed.factors["score"], p["__sector_groups__"])
    return {"economic": economic, "computed": computed, "candidates": low_open,
            "baseline": corrected, "score": computed.factors["score"].where(low_open),
            "origins": computed.factors["历史形态候选"]}


def prepare_groups() -> None:
    """Metadata-only pass over 2024 onward; never evaluates any returns."""
    if GROUPS.exists():
        raise FileExistsError("Industry receipt already exists")
    store = CutoffMarketStore(DB, SPLITS["observed_2026"][1])
    try:
        ctx, _, old, _, _, _ = prepare_proxy_context(
            store, "2024-01-01", "2026-09-30", config("2026-09-30"), OLD_GROUPS,
        )
        corrected = coordinate_inputs(ctx)
        union = (old | corrected["candidates"] | corrected["origins"]).loc["2024-01-01":]
        codes = sorted(map(str, union.columns[union.any(axis=0)]))
        counts = {"full_shape_events": int(corrected["origins"].loc["2024-01-01":].to_numpy().sum()),
                  "corrected_low_open_events": int(corrected["candidates"].loc["2024-01-01":].to_numpy().sum()),
                  "original_low_open_events": int(old.loc["2024-01-01":].to_numpy().sum())}
    finally:
        store.close()
    old_payload = json.loads(OLD_GROUPS.read_text(encoding="utf-8"))
    groups = old_payload["sector_groups"]
    missing = [code for code in codes if not groups.get(code)]
    print(json.dumps({**counts, "candidate_codes": len(codes), "missing_metadata": len(missing),
                      "no_returns_evaluated": True}), flush=True)
    from src.market.application.double_yin_inputs import fetch_double_yin_industries
    metadata, receipt = fetch_double_yin_industries(missing) if missing else ({}, {"requested": 0})
    for code, item in metadata.items():
        groups[code] = list(item["groups"])
    still_missing = [code for code in codes if not groups.get(code)]
    payload = {"source": "eastmoney_orginfo", "classification": "EM2016", "fetched_at": now(),
               "historical_membership": False, "base_path": str(OLD_GROUPS),
               "base_sha256": sha256(OLD_GROUPS), "base_fetched_at": old_payload.get("fetched_at"),
               "supplement": receipt, "supplement_metadata": metadata, "sector_groups": groups,
               "candidate_codes": codes, "candidate_code_count": len(codes), **counts,
               "missing_codes": still_missing, "coverage": (len(codes)-len(still_missing))/len(codes),
               "limitation": "Current real EM2016 groups, not historical memberships; 2023H2 remains unevaluated"}
    write_json(GROUPS, payload)
    print(json.dumps({"metadata_saved": True, "missing": len(still_missing), "coverage": payload["coverage"]}), flush=True)


def plan() -> dict:
    return {
        "created_at": now(), "variants": VARIANTS, "controls": CONTROLS, "splits": SPLITS,
        "preflight_changes": [
            "Old low-open density preflight computed counts only, no new rule returns.",
            "Before code freeze the task scope expanded origins to all strong-up then double-volume-yin shapes; day T low-open is no longer required for repair variants.",
            "Dropped the redundant entry risk<=6% gate before outcomes; losses controlled by exits.",
        ],
        "origin": "T is first market session after yin; full corrected historical strong-up(>=8%,bullish) then double-volume-yin, recent10 gain<=30%, main/nonST/name/history rules retained. No T opening condition for repairs; actual entry raw>6. Controls keep original low-open rule.",
        "coordinate": "Full pool recomputed raw OHLC*hfq factor; all price geometry, recent return, position and MA in consistent economic units. Raw volume, raw actual six-yuan gate, raw limit/fill. Current factors are revisioned, not PIT. Preserve exact original control and separate corrected control; no repair alpha credit for technical price fixes.",
        "observation": {
            "window": "T through T+5 inclusive; complete closed bars only. Expire after final day's confirmation opportunity.",
            "invalid": "Cancel on close below impulse T-2 low, any factor change over anchor T-3..T or observation/entry (raw volume incomparable), unknown industry, or expiration.",
            "one": "First dry stabilizing bar: V<=0.6*yin V, L>=preceding L, C>=O. Freeze trigger=max(bar H,yin C), base low=bar L, last volume=bar V. Formation bar cannot trigger.",
            "two": "First two consecutive dry bars, each V<=0.6*yin V; second V<=first V,L>=first L,C>=first C; range maxH/minL-1<=8%. Freeze trigger=max(two H), low=min(two L), last volume=second V. Both bars inside observation window.",
            "first_break": "On FIRST later bar H>frozen trigger consume opportunity. Confirm only C>trigger,C>O,V>=1.2*last base V; otherwise terminal failed_first_breakout; no retry/rearming/moving trigger.",
        },
        "selection": {
            "ranking": "At confirmation close: smaller (C-base_low)/C, then higher CLV, then smaller mean base V/yin V, code, older origin. All features now known.",
            "quota": "Greedy max2 orders per confirmation day with intersection of ALL industry groups excluded. Also cumulative max2 orders per origin date. Unfilled consumes quota; no refill. Unselected confirmations terminate with daily_capacity/industry_conflict/origin_quota.",
            "duplicates": "Keep earliest active origin for same code; later origins during watch/pending/position rejected and logged. Exit day origins blocked because ingest precedes exits. Two sessions after exit blocked; next third allowed. No hidden future exit to release code.",
            "entry": "Next market open only. Require economic O>=frozen trigger and O<=confirmation C*1.02; raw O>6; positive observed volume; known strict limit reference; no upper-limit opening; unchanged anchor factor. Otherwise cancel permanently.",
        },
        "exits": {
            "fixed": "4 sessions including entry; -6% economic stop, no profit take.",
            "structural": "3 sessions including entry; stop=max(base_low-.01*entry_factor,entry_basis*.94), frozen at entry; no profit take.",
            "causality": "At each market day opening process pending; ingest origins with current occupied/cooldown state; call unchanged _resolve_exit only with last_index=current_day; then closed-bar observation/confirmation. No entry-day sale. Gap uses worse opening, blocked sells delay.",
            "censoring": "data_end during simulation means still held, never release. Final unresolved fills are censored, not zero. Any such fill makes primary/origin budget means and CI/nomination unavailable.",
        },
        "comparison": {
            "maturity": "Every variant/control shares origins T+9<=segment end, exactly10 sessions from origin. Calendar not compressed for suspensions. Baseline old-mature versus common trim explicitly recorded.",
            "primary": "All market days from segment start through end-3 sessions times2 slots, INCLUDING empty days. Allocate realized net return to actual entry date; unused/unfilled slots zero. Not portfolio NAV or capital/time utilization.",
            "secondary": "Origin-date budget uses every common origin calendar date times2; separate month-block paired bootstrap. Auxiliary old active-origin-date slots disclosed. Never label origin CI as primary entry calendar CI.",
            "cost_pct": .21, "double_cost_pct": .42,
        },
        "nomination": {
            "max": 2, "train": ">=20 closed trades,>=6 active entry months,mean>0,PF>1,primary calendar slot mean>corrected baseline,positive double-cost+largest-winner-removed mean; no censored positions.",
            "sort": "Eligible by primary slot mean desc,PF desc,lexical id. If none eligible, at most2 nonzero closed noncensored diagnostic-only candidates by same ordering, retaining low-frequency positive evidence.",
            "later": "Evaluate only training-selected maximum2 plus both controls. Both later segments require mean>0,PF>1,>=12 closed,>=4 active months; combined later>=40 and positive double-cost+max-winner-removed mean. Publish primary budget increment vs corrected baseline and frequency loss, not merely less trading.",
            "status": "Previously observed historical periods, not untouched out-of-sample. No 2023H2 returns; reserve them for future supplemental historical evidence. Confidence intervals descriptive with no multiplicity correction.",
        },
        "limitations": ["Daily opening execution proxy, no 09:25 availability or queue-priority evidence.",
                        "Current instrument identity, EM2016 memberships and factor revisions; survivor/PIT caveat.",
                        "Controls reproduce independent historical trade events; repairs explicitly reject overlapping same-code origins. These are alternative mechanisms, not identical portfolio backtests.",
                        "Costs are per trade; slot sums/means do not model shared capital, sizing, financing or liquidity capacity."],
        "sources": sources(), "snapshot_sha256": sha256(DB), "groups_sha256": sha256(GROUPS),
    }


def stable_factor(data: dict, col: int, start: int, end: int) -> bool:
    values = data["factors"][start:end+1, col]
    return bool(len(values) and np.isfinite(values).all() and (values > 0).all()
                and np.allclose(values, values[0], rtol=0, atol=1e-10))


def valid_bar(data: dict, day: int, col: int) -> bool:
    o, h, low, c, v = (data[key][day, col] for key in ("open", "high", "low", "close", "volume"))
    return bool(np.isfinite([o, h, low, c, v]).all() and min(o, low, c, v) > 0
                and h >= max(o, c) and low <= min(o, c))


def form_base(state: dict, day: int, data: dict, kind: str) -> dict | None:
    j, origin = state["col"], state["origin"]
    e = {key: data[f"economic_{key}"] for key in ("open", "high", "low", "close")}
    v = data["volume"]
    if not valid_bar(data, day, j) or v[day, j] > .6*state["yin_volume"]:
        return None
    if kind == "one":
        if e["low"][day, j] < e["low"][day-1, j] or e["close"][day, j] < e["open"][day, j]:
            return None
        trigger = max(e["high"][day, j], state["yin_close"])
        low, mean = e["low"][day, j], v[day, j]
    elif kind == "two":
        if day <= origin or not valid_bar(data, day-1, j):
            return None
        if not (v[day-1, j] <= .6*state["yin_volume"] and v[day, j] <= v[day-1, j]
                and e["low"][day, j] >= e["low"][day-1, j]
                and e["close"][day, j] >= e["close"][day-1, j]):
            return None
        trigger = max(e["high"][day-1:day+1, j])
        low = min(e["low"][day-1:day+1, j])
        if trigger/low-1 > .08+1e-12:
            return None
        mean = float(v[day-1:day+1, j].mean())
    else:
        raise ValueError(kind)
    return {"base_day": day, "trigger": float(trigger), "base_low": float(low),
            "last_volume": float(v[day, j]), "contraction": float(mean/state["yin_volume"])}


def first_break_status(state: dict, day: int, data: dict) -> str | None:
    j, trigger = state["col"], state["trigger"]
    if day <= state["base_day"] or data["economic_high"][day, j] <= trigger:
        return None
    return "confirmed" if (data["economic_close"][day, j] > trigger
                            and data["economic_close"][day, j] > data["economic_open"][day, j]
                            and data["volume"][day, j] >= 1.2*state["last_volume"]) else "failed_first_breakout"


def entry_reason(state: dict, day: int, data: dict) -> str:
    j = state["col"]
    raw, economic = data["open"][day, j], data["economic_open"][day, j]
    if not np.isfinite(raw) or raw <= 6:
        return "raw_entry_price_not_above_six"
    if not data["volume"][day, j] > 0:
        return "suspended_entry"
    if not data["known"][day, j]:
        return "unknown_limit_reference"
    if data["strict_entry"][day, j]:
        return "upper_limit_opening"
    if not stable_factor(data, j, state["origin"]-3, day):
        return "factor_changed_entry"
    if economic < state["trigger"]:
        return "entry_below_trigger"
    if economic > state["confirm_close"]*1.02:
        return "entry_gap_above_two_pct"
    return "filled"


def repair(ctx: dict, origins: pd.DataFrame, data: dict, spec: dict) -> tuple[list[Trade], list[dict], list[dict]]:
    dates, codes = data["dates"], data["codes"]
    grouped = defaultdict(list)
    ii, jj = np.nonzero(origins.to_numpy(dtype=bool))
    for i, j in zip(ii, jj):
        grouped[int(i)].append(int(j))
    records, transitions, trades = [], [], []
    active: dict[int, dict] = {}
    cooldown: dict[int, int] = {}
    origin_orders = Counter()
    groups = ctx["panels"]["__sector_groups__"]

    def mark(state: dict, day: int, status: str, terminal: bool = False) -> None:
        state["status"] = status
        state["last_date"] = str(dates[day])
        transitions.append({"signal_date": state["signal_date"], "code": state["code"],
                            "date": str(dates[day]), "event": status})
        if terminal and active.get(state["col"]) is state:
            active.pop(state["col"])

    for day in range(len(dates)):
        # All orders here were chosen on a previous closed candle.
        for state in list(active.values()):
            if state["status"] != "pending" or state["entry_idx"] != day:
                continue
            reason = entry_reason(state, day, data)
            if reason != "filled":
                mark(state, day, reason, True)
                continue
            j = state["col"]
            state.update(entry_date=str(dates[day]), entry_price=float(data["open"][day, j]),
                         entry_factor=float(data["factors"][day, j]),
                         basis=float(data["economic_open"][day, j]))
            stop = state["basis"]*.94
            if spec["exit"] == "structural":
                stop = max(stop, state["base_low"]-.01*state["entry_factor"])
            state["stop_price"] = stop
            state["hold_days_target"] = 3 if spec["exit"] == "fixed" else 2
            mark(state, day, "position")
        # Before exits: an origin cannot assume today's currently unknown exit.
        for j in grouped.get(day, []):
            state = {"origin": day, "col": j, "signal_date": str(dates[day]), "code": str(codes[j]),
                     "yin_volume": float(data["volume"][day-1, j]),
                     "yin_close": float(data["economic_close"][day-1, j]),
                     "anchor_low": float(data["economic_low"][day-2, j]),
                     "opportunity_net_pct": 0.}
            records.append(state)
            if j in active:
                state["prior_origin"] = active[j]["signal_date"]
                mark(state, day, "duplicate_active_origin")
            elif day <= cooldown.get(j, -1):
                mark(state, day, "cooldown_origin")
            elif not groups.get(str(codes[j])):
                mark(state, day, "missing_industry")
            elif not stable_factor(data, j, day-3, day):
                mark(state, day, "factor_changed_anchor")
            else:
                active[j] = state
                mark(state, day, "watch")
        for state in list(active.values()):
            if state["status"] != "position" or day <= state["entry_idx"]:
                continue
            j, entry, basis = state["col"], state["entry_idx"], state["basis"]
            cfg = replace(ctx["config"], hold_days=state["hold_days_target"],
                          stop_loss_pct=(state["stop_price"]/basis-1)*100)
            exit_idx, price, reason = _resolve_exit(
                col=j, entry_idx=entry, entry_price=basis, planned_exit=entry+cfg.hold_days, cfg=cfg,
                high_a=data["economic_high"], low_a=data["economic_low"],
                close_a=data["economic_close"], open_a=data["economic_open"],
                one_word_down=data["strict_down"], volume_a=data["volume"], last_index=day,
            )
            if exit_idx is None or reason == "data_end" or not np.isfinite(price) or price <= 0:
                continue
            if exit_idx != day or exit_idx <= entry:
                raise AssertionError("Exit must occur today, after entry; no future release")
            factor = float(data["factors"][day, j])
            gross = (price/basis-1)*100
            window = slice(entry, day+1)
            live = data["volume"][window, j] > 0
            highs, lows = data["economic_high"][window, j][live], data["economic_low"][window, j][live]
            trade = Trade(code=state["code"], signal_date=state["signal_date"],
                          entry_date=state["entry_date"], entry_price=state["entry_price"],
                          exit_date=str(dates[day]), exit_price=float(price/factor), hold_days=day-entry,
                          gross_return_pct=float(gross), net_return_pct=float(gross-cfg.round_trip_cost_pct()),
                          mae_pct=float((np.nanmin(lows)/basis-1)*100),
                          mfe_pct=float((np.nanmax(highs)/basis-1)*100), exit_reason=reason,
                          entry_factor=state["entry_factor"], exit_factor=factor)
            assert math.isclose((trade.exit_price*factor/(trade.entry_price*trade.entry_factor)-1)*100,
                                trade.gross_return_pct, abs_tol=1e-8)
            trades.append(trade)
            state.update(exit_date=trade.exit_date, exit_reason=reason, exit_price=trade.exit_price,
                         opportunity_net_pct=trade.net_return_pct)
            mark(state, day, "closed", True)
            cooldown[j] = day+2
        confirmed = []
        for state in list(active.values()):
            if state["status"] not in {"watch", "armed"}:
                continue
            j, origin = state["col"], state["origin"]
            if not stable_factor(data, j, origin-3, day):
                mark(state, day, "factor_changed_observation", True)
                continue
            if valid_bar(data, day, j):
                if data["economic_close"][day, j] < state["anchor_low"]:
                    mark(state, day, "impulse_support_broken", True)
                    continue
                if state["status"] == "watch":
                    base = form_base(state, day, data, spec["base"])
                    if base:
                        state.update(base)
                        state["base_date"] = str(dates[day])
                        mark(state, day, "armed")
                elif state["status"] == "armed":
                    status = first_break_status(state, day, data)
                    if status == "failed_first_breakout":
                        mark(state, day, status, True)
                        continue
                    if status == "confirmed":
                        c, low, high = (data[f"economic_{key}"][day, j] for key in ("close", "low", "high"))
                        state.update(confirm_date=str(dates[day]), confirm_close=float(c),
                                     risk=float((c-state["base_low"])/c),
                                     clv=float((c-low)/(high-low)) if high > low else 0.)
                        mark(state, day, "confirmed")
                        confirmed.append(state)
                        continue
            if day >= origin+5:
                mark(state, day, "expired", True)
        confirmed.sort(key=lambda s: (s["risk"], -s["clv"], s["contraction"], s["code"], s["origin"]))
        used: set[str] = set()
        picked = 0
        for rank, state in enumerate(confirmed, 1):
            state["confirm_rank"] = rank
            own = set(groups[state["code"]])
            if origin_orders[state["origin"]] >= 2:
                mark(state, day, "origin_quota", True)
            elif used.intersection(own):
                mark(state, day, "industry_conflict", True)
            elif picked >= 2:
                mark(state, day, "daily_capacity", True)
            else:
                picked += 1
                used.update(own)
                origin_orders[state["origin"]] += 1
                state["entry_idx"] = day+1
                mark(state, day, "pending")
    for state in list(active.values()):
        if state["status"] == "position":
            state["opportunity_net_pct"] = None
            mark(state, len(dates)-1, "censored_position", True)
        else:
            raise AssertionError("Common maturity must complete observations and entries")
    assert len(records) == int(origins.to_numpy().sum())
    assert all(value <= 2 for value in origin_orders.values())
    assert all(count <= 2 for count in Counter(t.entry_date for t in trades).values())
    return trades, records, transitions


def daily_budget(events: list[dict], days: list[str], date_field: str) -> pd.DataFrame:
    bydate: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event.get("entry_date"):
            bydate[event[date_field]].append(event)
    rows = []
    for day in days:
        part = bydate.get(day, [])
        censored = sum(e.get("opportunity_net_pct") is None for e in part)
        rows.append({"signal_date": day, "opportunities": 2, "unresolved_positions": censored,
                     "filled": len(part), "net_sum": None if censored else sum(e["opportunity_net_pct"] for e in part)})
    if set(bydate)-set(days):
        raise AssertionError("A filled entry/origin lies outside the common budget")
    return pd.DataFrame(rows)


def evaluate(segment: str, selected_variants: list[str]) -> dict:
    start, end = SPLITS[segment]
    print(f"Prepare {segment} cutoff={end}", flush=True)
    store = CutoffMarketStore(DB, end)
    try:
        ctx, computed, old, oldscore, _, _ = prepare_proxy_context(store, start, end, config(end), GROUPS)
        corrected = coordinate_inputs(ctx)
        index = old.index
        mature = common_maturity_mask(index, start, end, entry_timing="open", max_hold=10)
        entry_mature = common_maturity_mask(index, start, end, entry_timing="open", max_hold=4)
        origins = corrected["origins"].where(mature, False, axis=0)
        old_mask = old.where(mature, False, axis=0)
        new_mask = corrected["candidates"].where(mature, False, axis=0)
        controls = {"original_baseline": computed.signals.where(mature, False, axis=0),
                    "corrected_baseline": corrected["baseline"].where(mature, False, axis=0)}
        group_map = ctx["panels"]["__sector_groups__"]
        missing = [str(code) for code in origins.columns[origins.any(axis=0)] if not group_map.get(str(code))]
        data = execution_arrays(ctx)
        # One prefix feature computation checks all source decisions, not returns.
        split_at = str(index[len(index)*2//3])
        prefix_ctx = {**ctx, "panels": {k: v.loc[:split_at] if isinstance(v, pd.DataFrame) else v for k, v in ctx["panels"].items()},
                      "execution_panels": {k: v.loc[:split_at] if isinstance(v, pd.DataFrame) else v for k, v in ctx["execution_panels"].items()}}
        prefix = coordinate_inputs(prefix_ctx)
        for key in ("candidates", "origins", "score", "baseline"):
            pd.testing.assert_frame_equal(prefix[key], corrected[key].loc[:split_at])
        membership = []
        all_keys = mask_keys(origins) | mask_keys(old_mask) | mask_keys(new_mask)
        for day, code in sorted(all_keys):
            membership.append({"signal_date": day, "code": code, "repair_origin": bool(origins.at[day, code]),
                               "original_low_open": bool(old_mask.at[day, code]), "corrected_low_open": bool(new_mask.at[day, code]),
                               "original_selected": bool(controls["original_baseline"].at[day, code]),
                               "corrected_selected": bool(controls["corrected_baseline"].at[day, code]),
                               "original_score": oldscore.at[day, code], "corrected_score": corrected["score"].at[day, code]})
        pd.DataFrame(membership).to_csv(OUTPUT / f"{segment}-origin-membership.csv", index=False)
        results, primary, secondary = {}, {}, {}
        for name in CONTROLS+selected_variants:
            print(f"Execute {segment}/{name}", flush=True)
            if name in controls:
                trades, events, _ = execute(ctx, controls[name], {"entry": "open", "exit": "fixed"}, {}, data)
                if name == "original_baseline":
                    baseline_check(segment, trades, mask_keys(controls[name]))
                transitions = []
            else:
                trades, events, transitions = repair(ctx, origins, data, VARIANTS[name])
            pd.DataFrame([t.to_dict(include_factors=True) for t in trades], columns=list(Trade.__dataclass_fields__)).to_csv(
                OUTPUT / f"{segment}-{name}-trades.csv", index=False)
            pd.DataFrame(events).to_csv(OUTPUT / f"{segment}-{name}-events.csv", index=False)
            if transitions:
                pd.DataFrame(transitions).to_csv(OUTPUT / f"{segment}-{name}-transitions.csv", index=False)
            primary[name] = daily_budget(events, list(map(str, index[entry_mature])), "entry_date")
            secondary[name] = daily_budget(events, list(map(str, index[mature])), "signal_date")
            censored = sum(e.get("opportunity_net_pct") is None for e in events)
            results[name] = {"metrics": metrics(trades), "active_entry_months": len({t.entry_date[:7] for t in trades}),
                             "event_accounting": dict(Counter(e["status"] for e in events)),
                             "transition_counts": dict(Counter(e["event"] for e in transitions)),
                             "unresolved_positions": censored,
                             "calendar_slots": int(primary[name].opportunities.sum()),
                             "calendar_slot_mean": None if censored else float(primary[name].net_sum.sum()/primary[name].opportunities.sum()),
                             "origin_slots": int(secondary[name].opportunities.sum()),
                             "origin_slot_mean": None if censored else float(secondary[name].net_sum.sum()/secondary[name].opportunities.sum())}
        for arm, frames in (("entry_calendar", primary), ("origin_calendar", secondary)):
            for name, daily in frames.items():
                daily["delta_net_sum"] = daily.net_sum-frames["corrected_baseline"].net_sum
                daily["variant"], daily["segment"] = name, segment
                results[name][f"{arm}_month_blocks_vs_corrected"] = None if daily.net_sum.isna().any() or frames["corrected_baseline"].net_sum.isna().any() else paired_bootstrap(daily)
            pd.concat(list(frames.values()), ignore_index=True).to_csv(OUTPUT / f"{segment}-{arm}-budget.csv", index=False)
        old_mature = common_maturity_mask(index, start, end, entry_timing="open", max_hold=4)
        audit = {"repair_origins": int(origins.to_numpy().sum()),
                 "original_low_open_origins": int(old_mask.to_numpy().sum()), "corrected_low_open_origins": int(new_mask.to_numpy().sum()),
                 "repair_added_beyond_corrected_low_open": int((origins & ~new_mask).to_numpy().sum()),
                 "corrected_candidates_added": len(mask_keys(new_mask)-mask_keys(old_mask)),
                 "corrected_candidates_removed": len(mask_keys(old_mask)-mask_keys(new_mask)),
                 "original_old_mature_top2": int(computed.signals.where(old_mature, False, axis=0).to_numpy().sum()),
                 "original_common_mature_top2": int(controls["original_baseline"].to_numpy().sum()),
                 "original_active_origin_date_slots": int(controls["original_baseline"].any(axis=1).sum()*2),
                 "common_origin_days": int(mature.sum()), "common_entry_budget_days": int(entry_mature.sum()),
                 "missing_industry_codes": missing, "prefix_feature_check": "passed", "original_baseline_parity": "passed"}
        summary = {"segment": segment, "start": start, "end": end, "audit": audit, "runs": results,
                   "completed_at": now(), "snapshot": ctx["data_snapshot"]}
        write_json(OUTPUT / f"{segment}-summary.json", summary)
        return summary
    finally:
        store.close()


def shortlist(train: dict) -> dict:
    baseline = train["runs"]["corrected_baseline"]["calendar_slot_mean"]
    candidates, eligible = [], []
    for name in VARIANTS:
        result = train["runs"][name]
        base = result["metrics"]["base"]
        if result["unresolved_positions"] or not base["trades"]:
            continue
        candidates.append(name)
        stress = result["metrics"]["double_cost_largest_winner_removed"]["avg_net_return"]
        if (base["trades"] >= 20 and result["active_entry_months"] >= 6 and base["avg_net_return"] > 0
                and (base["profit_factor"] or 0) > 1 and baseline is not None
                and result["calendar_slot_mean"] > baseline and stress is not None and stress > 0):
            eligible.append(name)
    chosen = sorted(eligible or candidates, key=lambda n: (-train["runs"][n]["calendar_slot_mean"],
                    -(train["runs"][n]["metrics"]["base"]["profit_factor"] or 0), n))[:2]
    return {"created_at": now(), "selected": chosen, "qualified": eligible,
            "status": "qualified_training_candidates" if eligible else "diagnostic_only_no_qualified_candidate",
            "train_sha256": sha256(OUTPUT / "train-summary.json"), "plan_sha256": sha256(OUTPUT / "PLAN.json")}


def pooled_summary(short: dict, stages: dict) -> dict:
    pooled = {}
    for name in CONTROLS+short["selected"]:
        all_trades, later_trades = [], []
        for segment in SPLITS:
            frame = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str})
            trades = [Trade(**row) for row in frame.to_dict("records")]
            all_trades.extend(trades)
            if segment != "train":
                later_trades.extend(trades)
        entry = pd.concat([pd.read_csv(OUTPUT / f"{s}-entry_calendar-budget.csv") for s in SPLITS])
        entry = entry[entry.variant.eq(name)]
        origin = pd.concat([pd.read_csv(OUTPUT / f"{s}-origin_calendar-budget.csv") for s in SPLITS])
        origin = origin[origin.variant.eq(name)]
        later = entry[entry.segment.ne("train")]
        late_metrics = metrics(later_trades)
        gates = []
        for segment in ("validation_2025h2", "observed_2026"):
            result = stages[segment]["runs"][name]
            base = result["metrics"]["base"]
            gates.append(base["trades"] >= 12 and result["active_entry_months"] >= 4 and
                         (base["avg_net_return"] or 0) > 0 and (base["profit_factor"] or 0) > 1 and
                         not result["unresolved_positions"])
        stress = late_metrics["double_cost_largest_winner_removed"]["avg_net_return"]
        pooled[name] = {"metrics": metrics(all_trades), "later_metrics": late_metrics,
                        "calendar_slots": int(entry.opportunities.sum()),
                        "calendar_slot_mean": None if entry.net_sum.isna().any() else float(entry.net_sum.sum()/entry.opportunities.sum()),
                        "later_calendar_slot_mean": None if later.net_sum.isna().any() else float(later.net_sum.sum()/later.opportunities.sum()),
                        "all_entry_month_blocks_vs_corrected": None if entry.delta_net_sum.isna().any() else paired_bootstrap(entry),
                        "later_entry_month_blocks_vs_corrected": None if later.delta_net_sum.isna().any() else paired_bootstrap(later),
                        "all_origin_month_blocks_vs_corrected": None if origin.delta_net_sum.isna().any() else paired_bootstrap(origin),
                        "later_gates_passed": all(gates) and len(later_trades) >= 40 and stress is not None and stress > 0}
    return pooled


def self_check() -> dict:
    dates = pd.Index([f"2025-01-{d:02d}" for d in range(1, 13)])
    mature = common_maturity_mask(dates, dates[0], dates[-1], entry_timing="open", max_hold=10)
    assert list(dates[mature]) == list(dates[:3])  # T+9 is last, not T+10.
    shape = (12, 1)
    data = {k: np.full(shape, v) for k, v in {"open": 10., "high": 10.4, "low": 9.8,
            "close": 10.2, "volume": 100., "factors": 1.}.items()}
    data.update(dates=list(dates), codes=["600001"], known=np.ones(shape, bool),
                strict_entry=np.zeros(shape, bool), strict_down=np.zeros(shape, bool))
    for key in ("open", "high", "low", "close"):
        data[f"economic_{key}"] = data[key]*data["factors"]
    state = dict(col=0, origin=3, yin_volume=200., yin_close=10.3)
    base = form_base(state, 3, data, "one")
    assert base and base["trigger"] == 10.4
    state.update(base)
    assert first_break_status(state, 3, data) is None
    data["economic_high"][4, 0] = 10.5
    assert first_break_status(state, 4, data) == "failed_first_breakout"
    state["confirm_close"] = 10.5
    assert entry_reason(state, 5, data) == "entry_below_trigger"
    data["open"][5, 0], data["economic_open"][5, 0] = 10.8, 10.8
    assert entry_reason(state, 5, data) == "entry_gap_above_two_pct"
    data["open"][5, 0], data["economic_open"][5, 0] = 10.5, 10.5
    assert entry_reason(state, 5, data) == "filled"
    data["factors"][5, 0] = 1.1
    assert entry_reason(state, 5, data) == "factor_changed_entry"
    data["factors"][5, 0] = 1.
    idx, _, reason = _resolve_exit(col=0, entry_idx=3, entry_price=10., planned_exit=6,
        cfg=config("2025-01-12"), high_a=data["economic_high"], low_a=data["economic_low"],
        close_a=data["economic_close"], open_a=data["economic_open"],
        one_word_down=data["strict_down"], volume_a=data["volume"], last_index=4)
    assert idx == 4 and reason == "data_end"
    events = [{"entry_date": dates[1], "signal_date": dates[0], "opportunity_net_pct": None}]
    assert pd.isna(daily_budget(events, list(dates), "entry_date").iloc[1].net_sum)
    # A failed FIRST breakout remains terminal even if later bars are perfect.
    origins = pd.DataFrame(False, index=dates, columns=["600001"])
    origins.iloc[3, 0] = True
    data["volume"][2, 0] = 200.
    data["economic_low"][1, 0] = 9.
    ctx = {"panels": {"__sector_groups__": {"600001": ["industry:synthetic"]}}, "config": config(dates[-1])}
    trades, records, transitions = repair(ctx, origins, data, VARIANTS["one_dry_fixed"])
    assert not trades and records[0]["status"] == "failed_first_breakout"
    assert sum(e["event"] == "failed_first_breakout" for e in transitions) == 1
    # Full path: close confirmation, next open, T+1, occupied origins and cooldown.
    long_dates = pd.Index(pd.bdate_range("2025-01-01", periods=22).strftime("%Y-%m-%d"))
    long_shape = (22, 1)
    sequence = {k: np.full(long_shape, v) for k, v in {"open": 10., "high": 10.4, "low": 9.8,
                "close": 10.2, "volume": 100., "factors": 1.}.items()}
    sequence.update(dates=list(long_dates), codes=["600001"], known=np.ones(long_shape, bool),
                    strict_entry=np.zeros(long_shape, bool), strict_down=np.zeros(long_shape, bool))
    sequence["volume"][2, 0] = 200.
    for key, val in {"open": 10.3, "high": 10.8, "low": 10.2, "close": 10.6, "volume": 130.}.items():
        sequence[key][4, 0] = val
    for key, val in {"open": 10.6, "high": 10.8, "low": 8., "close": 10.7}.items():
        sequence[key][5, 0] = val
    for key, val in {"open": 10.5, "high": 10.8, "low": 10.2, "close": 10.6}.items():
        sequence[key][6:9, 0] = val
    for key in ("open", "high", "low", "close"):
        sequence[f"economic_{key}"] = sequence[key]*sequence["factors"]
    many_origins = pd.DataFrame(False, index=long_dates, columns=["600001"])
    for row in (3, 4, 8, 9, 10, 11):
        many_origins.iloc[row, 0] = True
    trades, records, _ = repair(ctx, many_origins, sequence, VARIANTS["one_dry_fixed"])
    assert len(trades) == 1 and trades[0].entry_date == long_dates[5] and trades[0].exit_date == long_dates[8]
    statuses = {r["origin"]: r["status"] for r in records}
    assert statuses[4] == statuses[8] == "duplicate_active_origin"
    assert statuses[9] == statuses[10] == "cooldown_origin" and statuses[11] == "expired"
    # Poisoning the future must not change transitions through an earlier cutoff.
    cut = 7
    prefix_sequence = {key: val[:cut+1] if isinstance(val, (np.ndarray, list)) else val for key, val in sequence.items()}
    _, prefix_records, prefix_events = repair(ctx, many_origins.iloc[:cut+1], prefix_sequence, VARIANTS["one_dry_fixed"])
    _, _, all_events = repair(ctx, many_origins, sequence, VARIANTS["one_dry_fixed"])
    assert [e for e in prefix_events if e["event"] != "censored_position"] == [e for e in all_events if e["date"] <= long_dates[cut]]
    assert prefix_records[0]["status"] == "censored_position" and prefix_records[0]["opportunity_net_pct"] is None
    # A genuine factor-scale transformation preserves economic geometry while
    # the raw six-yuan executable-price gate remains independent.
    from src.strategy.application.double_yin_low_open import DoubleYinLowOpenV1
    price_dates = pd.Index(pd.bdate_range("2024-01-01", periods=80).strftime("%Y-%m-%d"))
    prices = {key: pd.DataFrame(value, index=price_dates, columns=["600001"])
              for key, value in {"open": 10., "high": 10.3, "low": 9.8, "close": 10., "volume": 100.}.items()}
    for offset, vals in {-3: {"open": 10., "high": 11.2, "low": 9.9, "close": 11., "volume": 100.},
                         -2: {"open": 11.2, "high": 11.4, "low": 10.4, "close": 10.6, "volume": 200.},
                         -1: {"open": 10.5, "high": 10.8, "low": 10.3, "close": 10.6, "volume": 100.}}.items():
        for key, val in vals.items():
            prices[key].iloc[offset, 0] = val
    prices.update(__instrument_names__={"600001": "合成检查"}, __sector_groups__={"600001": ["industry:synthetic"]})
    factor = pd.DataFrame(1., index=price_dates, columns=["600001"])
    engine = DoubleYinLowOpenV1()
    pricing_ctx = {"engine": engine, "panels": prices, "execution_panels": {"__adjust_factor": factor},
                   "resolved_params": engine.default_params()}
    original_coordinate = coordinate_inputs(pricing_ctx)
    assert original_coordinate["candidates"].iloc[-1, 0]
    scaled_prices = {key: val/2 if key in {"open", "high", "low", "close"} else val for key, val in prices.items()}
    scaled = coordinate_inputs({**pricing_ctx, "panels": scaled_prices,
                               "execution_panels": {"__adjust_factor": factor*2}})
    pd.testing.assert_frame_equal(original_coordinate["origins"], scaled["origins"])
    assert not scaled["candidates"].iloc[-1, 0] and scaled["origins"].iloc[-1, 0]
    return {"status": "passed", "checks": ["ten_session_origin_maturity", "formation_cannot_trigger",
            "first_failed_high_break_terminal", "entry_trigger_and_gap_bounds", "factor_cancel",
            "prefix_data_end_is_not_exit", "censored_budget_is_null", "occupied_and_exit_day_origin_rejected",
            "two_day_cooldown", "T0_extreme_does_not_stop", "prefix_state_transitions_causal",
            "full_shape_coordinate_scale_invariance", "raw_six_yuan_gate_not_economic"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare-data", "self-check", "freeze", "train", "evaluate"])
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.phase == "prepare-data":
        prepare_groups()
        return
    if args.phase == "self-check":
        print(json.dumps(self_check(), ensure_ascii=False), flush=True)
        return
    if args.phase == "freeze":
        if (OUTPUT / "PLAN.json").exists():
            raise FileExistsError("Plan already frozen")
        checked = self_check()
        write_json(OUTPUT / "PLAN.json", plan())
        write_json(OUTPUT / "self-check.json", checked)
        print(json.dumps({"frozen": True, "plan_sha256": sha256(OUTPUT / "PLAN.json")}), flush=True)
        return
    frozen = json.loads((OUTPUT / "PLAN.json").read_text(encoding="utf-8"))
    if sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"] or sha256(GROUPS) != frozen["groups_sha256"]:
        raise AssertionError("Frozen source, snapshot or industry receipt changed")
    if args.phase == "train":
        if (OUTPUT / "training-shortlist.json").exists():
            raise FileExistsError("Training already frozen")
        train = evaluate("train", list(VARIANTS))
        short = shortlist(train)
        write_json(OUTPUT / "training-shortlist.json", short)
        print(json.dumps(short, ensure_ascii=False), flush=True)
        return
    short = json.loads((OUTPUT / "training-shortlist.json").read_text(encoding="utf-8"))
    if short["train_sha256"] != sha256(OUTPUT / "train-summary.json") or short["plan_sha256"] != sha256(OUTPUT / "PLAN.json"):
        raise AssertionError("Training nomination changed")
    stages = {"train": json.loads((OUTPUT / "train-summary.json").read_text(encoding="utf-8"))}
    for segment in ("validation_2025h2", "observed_2026"):
        if (OUTPUT / f"{segment}-summary.json").exists():
            raise FileExistsError("Later period already evaluated")
        stages[segment] = evaluate(segment, short["selected"])
    if sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"] or sha256(GROUPS) != frozen["groups_sha256"]:
        raise AssertionError("Frozen source/data changed during evaluation")
    write_json(OUTPUT / "summary.json", {"completed_at": now(), "shortlist": short, "segments": stages,
               "pooled": pooled_summary(short, stages), "plan_sha256": sha256(OUTPUT / "PLAN.json"),
               "source_snapshot_groups_unchanged": True})
    print(json.dumps({"completed": True, "selected": short["selected"]}), flush=True)


if __name__ == "__main__":
    main()
