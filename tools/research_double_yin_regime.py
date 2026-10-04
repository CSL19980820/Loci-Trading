"""A finite, frozen market/trend-permission study of the full double-yin pool.

Research only: the daily-open execution proxy never disables live realtime
requirements, and all source price/industry observations remain immutable.
"""
from __future__ import annotations

import argparse
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
from tools.research_double_yin_redesign import config, execute, execution_arrays, mask_keys, metric, metrics  # noqa: E402
from tools.research_double_yin_repair import daily_budget  # noqa: E402
from tools.research_double_yin_scoring_proxy import prepare_proxy_context, rank_with_groups  # noqa: E402
from tools.research_impulse_scoring import paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-double-yin-regime"
DB = ROOT / ".local/multi-strategy-scoring-20261004/market.db"
GROUPS = ROOT / "docs/research/2026-10-04-double-yin-repair/industry-groups.json"
SPLITS = {"train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}
CONTROLS = ["corrected_low_open", "full_shape"]
VARIANTS = ["market_permission", "stock_permission", "market_and_stock"]
CANDIDATES = ["full_shape", *VARIANTS]


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sources() -> dict[str, str]:
    names = ["tools/research_double_yin_regime.py", "tools/research_double_yin_repair.py",
             "tools/research_double_yin_redesign.py", "tools/research_double_yin_scoring_proxy.py",
             "tools/research_chinext_payoff_exits.py", "tools/research_impulse_scoring.py",
             "src/strategy/application/double_yin_low_open.py", "src/backtest/application/engine.py",
             "src/backtest/application/execution_contract.py", "src/market/infrastructure/store_panel.py",
             "src/market/domain/universe.py"]
    return {name: sha256(ROOT / name) for name in names}


def plan() -> dict:
    return {
        "created_at": now(), "controls": CONTROLS, "variants": VARIANTS, "nominatable": CANDIDATES, "splits": SPLITS,
        "prior_evidence": "Old low-open selector and subsequent repair variants were already observed; repair did not generalize. This new family is frozen before its own returns; no untouched OOS claim.",
        "universe": "Full corrected historical strong-up then double-volume-yin candidates; no low-open condition for full_shape/M/S/intersection. All require actual raw T opening>6 and valid opening. Retain original main-board/nonST/name/history/recent-gain identities. corrected_low_open independently retains original low-open gate.",
        "score": "Recompute for EVERY full shape from economic OHLC=raw*hfq factor:60*(1-clipped position of current O in previous60 high-low range)+40*clipped(1-min distance to previousMA5/10/20/0.03), rounded4. Never fill the old low-open-only masked score. Full-pool low-open rows must exactly match corrected original score.",
        "numeric_contract": "Read sparse hfq_factor directly from immutable snapshot with factor date<=phase cutoff; forward-align only. Positive quoted price without prior known factor fails; no future backfill or adjusted_close/raw_close reconstruction. For SIGNAL geometry and comparisons, economic prices and compared moving averages use10 significant decimal digits; observed quantization error must be<0.0001raw tick. Relative20d return difference rounded to10 decimals in percentage points before strict>0. Actual execution/returns use unquantized raw prices*direct stored factor. Same raw price with same factor must compare equal. All5 arms share this technical correction.",
        "market_permission": "M: at T-1 CSI300 C>MA60 AND above-MA20 main-stock breadth>=0.50. No current-day index/stock close is used.",
        "stock_permission": "S: at T-2 stock C>MA60 AND MA20>MA60 AND stock20-session return>CSI30020-session return. Stock and index use the same market-date endpoints, T-22 through T-2 inclusive endpoints.",
        "market_and_stock": "M AND S. Exactly3 new mechanisms; no window/threshold/exit grid.",
        "breadth": {
            "universe": "Every stored instrument_type=STOCK with six-digit 00/60 code, independent of double-yin shape, current name/ST/status, and candidate industry coverage; INDEX excluded explicitly.",
            "eligible": "On observation day,20 consecutive market sessions with finite positive economic close AND raw volume>0. New listings/missing/suspensions lacking that history are outside denominator; future listings cannot enter historical denominator.",
            "above_ma": "fraction of eligible names with C>MA20 on observation day, then shifted1 for T permission.",
            "advancing": "fraction of same eligible names with C>prior C; diagnostic-only fixed split50%, not an extra trading gate.",
            "missing": "No index forward fill or denominator guess. Any missing/nonpositive benchmark session fails preparation; no partially imputed run. Empty breadth denominator disables the market gate.",
        },
        "rank_and_execution": "Filter complete full-shape pool BEFORE original60/40 ranking and greedy group-intersection Top2. T daily-open proxy, raw limits/economic returns; original4-session including entry exit with-6% stop,strictT+1,gap worse-open,blocked exit delay. No additional duplicate/cooldown/repair state or exit parameters; independent events match controls.",
        "comparison": "Common origin T+3<=end for all5 arms. Primary every eligible market day*2 INCLUDING empty days; filtered/unfilled/unused slots0,censored fills unresolved and mean/CI unavailable. Compare mechanisms to BOTH full_shape causal control and corrected_low_open original-behavior control. All full-shape candidates independently executed for diagnostic conditional tables only; not a sixth tradable strategy or capital return.",
        "diagnostics": "Training only, pre-fixed boolean splits: CSI300 aboveMA60, breadth aboveMA20>=50%,advancing>=50%,stockC>MA60,stockMA20>MA60,positive20d relative return, and4 cells of M/S. Show all-candidate and each control's selected trade statistics; no alternate thresholds selected from these groups.",
        "cost_pct": .21, "double_cost_pct": .42,
        "nomination": {
            "full_shape_role": "full_shape is both the causal control for environmental gates AND a separately nominatable simple removal of the low-open gate. It competes within the same maximum2 quota; being displayed later as a control does not grant a retrospective nomination.",
            "eligible": "Train>=20 closed,>=6 active entry months,net mean>0,PF>1,double-cost+largest-winner-removed mean>0,and fixed calendar-slot mean greater than corrected_low_open; M/S/intersection must additionally beat full_shape. No censoring. This prevents fewer trades alone from qualifying.",
            "rank": "Among eligible only, calendar-slot mean descending,PF descending,lexical id; maximum2. If none eligible, STOP this family with diagnosis; no diagnostic fallback, more windows, thresholds, or exit rescues.",
            "later": "Only frozen maximum2 qualifiers plus two controls in already-observed2025H2/2026. Each later segment>=12 closed,>=4 active months,positive net mean,PF>1,slot mean>corrected_low_open; M/S/intersection additionally beat full_shape. Combined later>=40 and positive double-cost+largest-winner-removed mean. full_shape can only pass if training-nominated. Publish opportunity increment and lost frequency even when failing.",
        },
        "limitations": ["Current catalog/current real EM2016/current revised factors, not historical PIT reconstruction.",
                        "Raw volume ratios may be affected by share changes; this convention is shared by controls and variants.",
                        "Daily-open proxy, no historical09:25execution/queue proof; slot means are not shared-capital portfolio NAV.",
                        "20/60 and0/50% fixed ex ante; finite multiple hypotheses still permit data snooping. Month-block intervals descriptive.",
                        "2023H2 is warmup only, no returns computed."],
        "sources": sources(), "snapshot_sha256": sha256(DB), "groups_sha256": sha256(GROUPS),
    }


def price_precision(value: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Ten significant digits; much finer than any executable raw cent tick."""
    a = value.to_numpy(dtype=float)
    valid = np.isfinite(a) & (a != 0)
    scale = np.ones_like(a)
    scale[valid] = np.power(10., 9-np.floor(np.log10(np.abs(a[valid]))))
    normalized = np.round(a*scale)/scale
    if isinstance(value, pd.DataFrame):
        return pd.DataFrame(normalized, index=value.index, columns=value.columns)
    return pd.Series(normalized, index=value.index, name=value.name)


def snapshot_factors(store: CutoffMarketStore, raw: pd.DataFrame) -> pd.DataFrame:
    codes = list(map(str, raw.columns))
    placeholders = ",".join("?" for _ in codes)
    rows = store.conn.execute(
        f"SELECT code,trade_date,hfq_factor FROM adjust_factors WHERE code IN ({placeholders}) "
        "AND trade_date<=? ORDER BY code,trade_date", [*codes, str(raw.index[-1])],
    ).fetchall()
    if not rows:
        raise ValueError("No direct snapshot adjustment factors")
    sparse = pd.DataFrame([tuple(row) for row in rows], columns=["code", "trade_date", "factor"])
    wide = sparse.pivot(index="trade_date", columns="code", values="factor")
    factors = wide.reindex(wide.index.union(raw.index)).sort_index().ffill().reindex(index=raw.index, columns=raw.columns)
    quoted = np.isfinite(raw) & raw.gt(0)
    known = np.isfinite(factors) & factors.gt(0)
    if (quoted & ~known).to_numpy().any():
        raise ValueError("Positive raw quote without preceding known direct snapshot factor")
    # Leading non-quoted prelisting cells alone may use1 to satisfy array
    # validation; no actual quote/shape/entry can consume that placeholder.
    return factors.where(known, 1.)


def normalized_economic(raw: dict, factors: pd.DataFrame) -> dict:
    economic = dict(raw)
    for key in ("open", "high", "low", "close"):
        if key not in raw:
            continue
        exact = raw[key]*factors
        precise = price_precision(exact)
        error_ticks = (precise-exact).abs()/(factors*.01)
        maximum = float(np.nanmax(error_ticks.to_numpy()))
        if maximum >= .0001:
            raise AssertionError("Signal normalization is too coarse relative to raw cent tick")
        economic[key] = precise
    return economic


def corrected_inputs(ctx: dict, store: CutoffMarketStore) -> dict:
    p = ctx["panels"]
    factors = snapshot_factors(store, p["close"])
    ctx["execution_panels"] = {**ctx["execution_panels"], "__adjust_factor": factors}
    economic = normalized_economic(p, factors)
    computed = ctx["engine"].compute(economic, {**ctx["resolved_params"], "price_floor": 0.})
    candidates = computed.factors["条件候选"] & p["open"].gt(6)
    baseline = rank_with_groups(candidates, computed.factors["score"], p["__sector_groups__"])[0]
    return {"economic": economic, "origins": computed.factors["历史形态候选"],
            "candidates": candidates, "score": computed.factors["score"].where(candidates), "baseline": baseline}


def full_shape_score(economic: dict, candidates: pd.DataFrame) -> pd.DataFrame:
    o, h, low, c = (economic[key] for key in ("open", "high", "low", "close"))
    floor, ceiling = low.shift(1).rolling(60).min(), h.shift(1).rolling(60).max()
    position = ((o-floor)/(ceiling-floor).where(ceiling.gt(floor))).clip(0, 1)
    distance = pd.DataFrame(np.inf, index=o.index, columns=o.columns)
    for period in (5, 10, 20):
        ma = c.shift(1).rolling(period).mean()
        current = (o/ma.where(ma.gt(0))-1).abs()
        distance = distance.where(~(np.isfinite(current) & current.lt(distance)), current)
    score = (60*(1-position)+40*(1-distance/.03).clip(0, 1)).where(candidates)
    return score.where(np.isfinite(score)).clip(0, 100).round(4)


def regime_features(economic: dict, benchmark: pd.Series, breadth: dict) -> tuple[dict, dict]:
    c = economic["close"]
    benchmark = benchmark.reindex(c.index)
    index_above = (price_precision(benchmark) > price_precision(benchmark.rolling(60).mean())).shift(1).fillna(False).astype(bool)
    wide_close, wide_volume = breadth["close"].reindex(c.index), breadth["volume"].reindex(c.index)
    quoted = np.isfinite(wide_close) & wide_close.gt(0) & np.isfinite(wide_volume) & wide_volume.gt(0)
    eligible = quoted.rolling(20).sum().eq(20)
    denominator = eligible.sum(axis=1)
    above = (wide_close.gt(price_precision(wide_close.rolling(20).mean())) & eligible).sum(axis=1)/denominator.where(denominator.gt(0))
    advancing = (wide_close.gt(wide_close.shift(1)) & eligible).sum(axis=1)/denominator.where(denominator.gt(0))
    ma20, ma60 = price_precision(c.rolling(20).mean()), price_precision(c.rolling(60).mean())
    above60 = c.gt(ma60).shift(2).fillna(False).astype(bool)
    aligned = ma20.gt(ma60).shift(2).fillna(False).astype(bool)
    relative = ((c/c.shift(20)-1).sub(benchmark/benchmark.shift(20)-1, axis=0)*100).round(10).shift(2)
    market = index_above & above.shift(1).ge(.5)
    market_grid = pd.DataFrame(np.broadcast_to(market.to_numpy()[:, None], c.shape), index=c.index, columns=c.columns)
    stock = above60 & aligned & relative.gt(0)
    features = {
        "index_above_ma60": index_above, "breadth_above_ma20": above.shift(1),
        "breadth_advancing": advancing.shift(1), "breadth_denominator": denominator.shift(1),
        "stock_above_ma60": above60, "stock_ma20_above_ma60": aligned,
        "relative_20d_pct": relative,
    }
    return features, {"market_permission": market_grid, "stock_permission": stock,
                      "market_and_stock": market_grid & stock}


def load_environment(store: CutoffMarketStore, index: pd.Index, end: str) -> tuple[pd.Series, dict, dict]:
    rows = list(store.conn.execute("SELECT code FROM instruments WHERE instrument_type='STOCK'"))
    codes = sorted(str(row[0]) for row in rows if len(str(row[0])) == 6 and str(row[0]).isdigit()
                   and str(row[0]).startswith(("00", "60")))
    if "000300" in codes:
        raise AssertionError("CSI300 index must not enter stock breadth")
    wide = store.load_panel(fields=("close", "volume"), codes=codes, start="2023-01-01", end=end,
                            adjust="none", min_bars=20)
    wide = {key: value.reindex(index) for key, value in wide.items()}
    wide = normalized_economic(wide, snapshot_factors(store, wide["close"]))
    benchmark = store.load_panel(fields=("close",), codes=["000300"], start="2023-01-01", end=end,
                                adjust="none", min_bars=60)["close"]["000300"].reindex(index)
    if not (np.isfinite(benchmark) & benchmark.gt(0)).all():
        raise ValueError("CSI300 has missing/nonpositive sessions; no fabricated trend or relative returns")
    sources_b = [dict(row) for row in store.conn.execute(
        "SELECT source,COUNT(*) AS observations,MIN(trade_date) AS first_date,MAX(trade_date) AS last_date "
        "FROM quotes_daily WHERE code=? AND trade_date<=? GROUP BY source", ("000300", end))]
    return benchmark, wide, {"main_stock_catalog_codes": len(codes), "breadth_panel_codes": len(wide["close"].columns),
                              "index_excluded": True, "benchmark_coverage": int(benchmark.notna().sum()),
                              "benchmark_sources": sources_b}


def diagnostic_features(features: dict, masks: dict, candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for day, code in sorted(mask_keys(candidates)):
        record = {"signal_date": day, "code": code}
        for name, value in features.items():
            record[name] = value.at[day, code] if isinstance(value, pd.DataFrame) else value.at[day]
        record.update({name: bool(mask.at[day, code]) for name, mask in masks.items()})
        record["breadth_above_half"] = bool(record["breadth_above_ma20"] >= .5)
        record["advancing_above_half"] = bool(record["breadth_advancing"] >= .5)
        record["relative_positive"] = bool(record["relative_20d_pct"] > 0)
        record["market_stock_cell"] = f"M{int(record['market_permission'])}_S{int(record['stock_permission'])}"
        rows.append(record)
    return pd.DataFrame(rows)


def diagnose(trades: list[Trade], candidates: pd.DataFrame, selected: dict) -> dict:
    frame = pd.DataFrame([{"signal_date": t.signal_date, "code": t.code, "net_return_pct": t.net_return_pct} for t in trades])
    frame = frame.merge(candidates, on=["signal_date", "code"], how="left", validate="one_to_one")
    for name, mask in selected.items():
        keys = mask_keys(mask)
        frame[name] = [(d, c) in keys for d, c in zip(frame.signal_date, frame.code)]
    frame.to_csv(OUTPUT / "train-all-candidate-conditional-outcomes.csv", index=False)
    fields = ["index_above_ma60", "breadth_above_half", "advancing_above_half", "stock_above_ma60",
              "stock_ma20_above_ma60", "relative_positive", "market_stock_cell"]
    outputs = {}
    for scope in ["all_candidates", *CONTROLS]:
        scoped = frame if scope == "all_candidates" else frame[frame[scope]]
        outputs[scope] = {field: {str(group): metric(part.net_return_pct.to_numpy())
                                 for group, part in scoped.groupby(field, dropna=False)} for field in fields}
    return outputs


def evaluate(segment: str, variants: list[str]) -> dict:
    start, end = SPLITS[segment]
    print(f"Prepare {segment}; cutoff={end}", flush=True)
    store = CutoffMarketStore(DB, end)
    try:
        ctx, _, _, _, _, _ = prepare_proxy_context(store, start, end, config(end), GROUPS)
        corrected = corrected_inputs(ctx, store)
        p, economic = ctx["panels"], corrected["economic"]
        full = corrected["origins"] & np.isfinite(p["open"]) & p["open"].gt(6)
        score = full_shape_score(economic, full)
        pd.testing.assert_frame_equal(score.where(corrected["candidates"]), corrected["score"])
        benchmark, wide, environment = load_environment(store, full.index, end)
        features, masks = regime_features(economic, benchmark, wide)
        cutoff = str(full.index[len(full)*2//3])
        prefix_economic = {key: value.loc[:cutoff] if isinstance(value, pd.DataFrame) else value for key, value in economic.items()}
        prefix_features, prefix_masks = regime_features(prefix_economic, benchmark.loc[:cutoff],
                                                        {key: value.loc[:cutoff] for key, value in wide.items()})
        for name, value in features.items():
            if isinstance(value, pd.DataFrame):
                pd.testing.assert_frame_equal(value.loc[:cutoff], prefix_features[name])
            else:
                pd.testing.assert_series_equal(value.loc[:cutoff], prefix_features[name])
        for name in masks:
            pd.testing.assert_frame_equal(masks[name].loc[:cutoff], prefix_masks[name])
        mature = common_maturity_mask(full.index, start, end, entry_timing="open", max_hold=4)
        candidates = full.where(mature, False, axis=0)
        controls = {"corrected_low_open": corrected["baseline"].where(mature, False, axis=0),
                    "full_shape": rank_with_groups(candidates, score, p["__sector_groups__"])[0]}
        selected = dict(controls)
        for name in variants:
            selected[name] = rank_with_groups(candidates & masks[name], score, p["__sector_groups__"])[0]
        observations = diagnostic_features(features, masks, candidates)
        observations["score"] = [float(score.at[d, c]) for d, c in zip(observations.signal_date, observations.code)]
        for name, mask in selected.items():
            observations[f"selected_{name}"] = [bool(mask.at[d, c]) for d, c in zip(observations.signal_date, observations.code)]
        observations.to_csv(OUTPUT / f"{segment}-full-candidates.csv", index=False)
        days = list(map(str, full.index[mature]))
        market_frame = pd.DataFrame({name: value for name, value in features.items() if isinstance(value, pd.Series)}).loc[start:end]
        market_frame.to_csv(OUTPUT / f"{segment}-market-environment.csv", index_label="signal_date")
        data = execution_arrays(ctx)
        runs, daily = {}, {}
        for name, signals in selected.items():
            print(f"Execute {segment}/{name}", flush=True)
            trades, events, accounting = execute(ctx, signals, {"entry": "open", "exit": "fixed"}, {}, data)
            pd.DataFrame([t.to_dict(include_factors=True) for t in trades], columns=list(Trade.__dataclass_fields__)).to_csv(
                OUTPUT / f"{segment}-{name}-trades.csv", index=False)
            pd.DataFrame(events).to_csv(OUTPUT / f"{segment}-{name}-events.csv", index=False)
            daily[name] = daily_budget(events, days, "entry_date")
            censored = sum(e.get("opportunity_net_pct") is None for e in events)
            runs[name] = {"metrics": metrics(trades), "active_months": len({t.entry_date[:7] for t in trades}),
                          "accounting": accounting, "selected_orders": len(events), "censored": censored,
                          "slots": len(days)*2, "slot_mean": None if censored else float(daily[name].net_sum.sum()/(len(days)*2))}
        budget_rows = []
        for name, part in daily.items():
            for control in CONTROLS:
                comparison = part.copy()
                comparison["delta_net_sum"] = part.net_sum-daily[control].net_sum
                comparison["variant"], comparison["control"], comparison["segment"] = name, control, segment
                budget_rows.append(comparison)
                runs[name][f"month_blocks_vs_{control}"] = None if comparison.delta_net_sum.isna().any() else paired_bootstrap(comparison)
        pd.concat(budget_rows, ignore_index=True).to_csv(OUTPUT / f"{segment}-paired-calendar.csv", index=False)
        diagnostics = None
        if segment == "train":
            print("Training fixed conditional diagnostics, full pool only", flush=True)
            all_trades, all_events, all_accounting = execute(ctx, candidates, {"entry": "open", "exit": "fixed"}, {}, data)
            diagnostics = {"groups": diagnose(all_trades, observations, controls), "accounting": all_accounting,
                           "warning": "Overlapping independent full-pool trades for conditional diagnostics, no Top2/capital claim"}
            pd.DataFrame(all_events).to_csv(OUTPUT / "train-all-candidate-events.csv", index=False)
            write_json(OUTPUT / "train-diagnostics.json", diagnostics)
        result = {"segment": segment, "completed_at": now(), "runs": runs,
                  "audit": {"full_candidates": int(candidates.to_numpy().sum()),
                            "corrected_low_open_candidates": int(corrected["candidates"].where(mature, False, axis=0).to_numpy().sum()),
                            "common_days": len(days), "market_gate_days": int(masks["market_permission"].loc[days].iloc[:, 0].sum()),
                            "missing_groups": sum(not p["__sector_groups__"].get(str(code)) for code in candidates.columns[candidates.any(axis=0)]),
                            "full_score_corrected_low_open_parity": "passed", "prefix_feature_causality": "passed",
                            "environment": environment},
                  "training_conditional_diagnostics": diagnostics is not None,
                  "data_snapshot": ctx["data_snapshot"]}
        write_json(OUTPUT / f"{segment}-summary.json", result)
        return result
    finally:
        store.close()


def shortlist(train: dict) -> dict:
    qualified = []
    for name in CANDIDATES:
        controls = [train["runs"][control]["slot_mean"] for control in CONTROLS if control != name]
        run = train["runs"][name]
        m = run["metrics"]["base"]
        stress = run["metrics"]["double_cost_largest_winner_removed"]["avg_net_return"]
        if (not run["censored"] and m["trades"] >= 20 and run["active_months"] >= 6
                and (m["avg_net_return"] or 0) > 0 and (m["profit_factor"] or 0) > 1
                and stress is not None and stress > 0 and all(value is not None and run["slot_mean"] > value for value in controls)):
            qualified.append(name)
    selected = sorted(qualified, key=lambda name: (-train["runs"][name]["slot_mean"],
                      -(train["runs"][name]["metrics"]["base"]["profit_factor"] or 0), name))[:2]
    return {"created_at": now(), "qualified": qualified, "selected": selected,
            "status": "qualified_training_candidates" if selected else "stop_no_training_advantage",
            "train_sha256": sha256(OUTPUT / "train-summary.json"), "plan_sha256": sha256(OUTPUT / "PLAN.json")}


def later_summary(short: dict, stages: dict) -> dict:
    output = {}
    for name in dict.fromkeys(CONTROLS+short["selected"]):
        trades = []
        for segment in ("validation_2025h2", "observed_2026"):
            frame = pd.read_csv(OUTPUT / f"{segment}-{name}-trades.csv", dtype={"code": str})
            trades.extend(Trade(**row) for row in frame.to_dict("records"))
        pooled = metrics(trades)
        conditions = []
        for segment in ("validation_2025h2", "observed_2026"):
            r = stages[segment]["runs"][name]
            m = r["metrics"]["base"]
            conditions.append(not r["censored"] and m["trades"] >= 12 and r["active_months"] >= 4
                              and (m["avg_net_return"] or 0) > 0 and (m["profit_factor"] or 0) > 1)
            if name in short["selected"]:
                conditions.append(r["slot_mean"] is not None and all(stages[segment]["runs"][c]["slot_mean"] is not None and
                                      r["slot_mean"] > stages[segment]["runs"][c]["slot_mean"] for c in CONTROLS if c != name))
        stress = pooled["double_cost_largest_winner_removed"]["avg_net_return"]
        record = {"metrics": pooled, "later_passed": name in short["selected"] and all(conditions)
                  and len(trades) >= 40 and stress is not None and stress > 0}
        daily = pd.concat([pd.read_csv(OUTPUT / f"{s}-paired-calendar.csv") for s in ("validation_2025h2", "observed_2026")])
        for control in CONTROLS:
            part = daily[daily.variant.eq(name) & daily.control.eq(control)]
            record[f"month_blocks_vs_{control}"] = None if part.delta_net_sum.isna().any() else paired_bootstrap(part)
        output[name] = record
    return output


def self_check() -> dict:
    dates = pd.Index(pd.bdate_range("2024-01-01", periods=100).strftime("%Y-%m-%d"))
    values = np.arange(100, dtype=float)+100
    c = pd.DataFrame({"600001": values*1.4, "600002": values*.8}, index=dates)
    economic = {"open": c-.1, "high": c+.5, "low": c-.5, "close": c}
    benchmark = pd.Series(values, index=dates)
    wide = {"close": c.copy(), "volume": pd.DataFrame(100., index=dates, columns=c.columns)}
    wide["close"]["600003"] = np.nan
    wide["volume"]["600003"] = 0.
    wide["close"].loc[dates[-5]:, "600003"] = 500.
    wide["volume"].loc[dates[-5]:, "600003"] = 100.
    features, masks = regime_features(economic, benchmark, wide)
    assert features["breadth_denominator"].iloc[-1] == 2
    assert masks["market_permission"].iloc[-1].all()
    changed_economic = {key: frame.copy() for key, frame in economic.items()}
    for value in changed_economic.values():
        value.iloc[-1] *= 10
    changed_benchmark = benchmark.copy()
    changed_benchmark.iloc[-1] *= .1
    changed_wide = {key: frame.copy() for key, frame in wide.items()}
    changed_wide["close"].iloc[-1] *= .1
    after, gates = regime_features(changed_economic, changed_benchmark, changed_wide)
    for name in features:
        if isinstance(features[name], pd.DataFrame):
            pd.testing.assert_series_equal(features[name].iloc[-1], after[name].iloc[-1])
        else:
            assert features[name].iloc[-1] == after[name].iloc[-1]
    for name in masks:
        pd.testing.assert_series_equal(masks[name].iloc[-1], gates[name].iloc[-1])
    assert np.allclose(features["relative_20d_pct"].iloc[-1], 0., atol=1e-12)
    preceding_stock = {key: value.copy() for key, value in economic.items()}
    for value in preceding_stock.values():
        value.iloc[-2] *= .1
    stock_after, _ = regime_features(preceding_stock, benchmark, wide)
    for name in ("stock_above_ma60", "stock_ma20_above_ma60", "relative_20d_pct"):
        pd.testing.assert_series_equal(features[name].iloc[-1], stock_after[name].iloc[-1])
    preceding_index = benchmark.copy()
    preceding_index.iloc[-2] *= .1
    index_after, market_after = regime_features(economic, preceding_index, wide)
    assert not market_after["market_permission"].iloc[-1].any()
    pd.testing.assert_series_equal(features["relative_20d_pct"].iloc[-1], index_after["relative_20d_pct"].iloc[-1])
    candidates = pd.DataFrame(True, index=dates, columns=c.columns)
    score = full_shape_score(economic, candidates)
    changed_economic = {key: value*2 for key, value in economic.items()}
    pd.testing.assert_frame_equal(score, full_shape_score(changed_economic, candidates))
    prefix = full_shape_score({key: frame.iloc[:-1] for key, frame in economic.items()}, candidates.iloc[:-1])
    pd.testing.assert_frame_equal(score.iloc[:-1], prefix)
    equal_raw = pd.DataFrame({"600001": [9.09, 9.09]})
    equal_factors = pd.DataFrame({"600001": [3.4672447009574, 3.4672447009574]})
    equal_economic = normalized_economic({"low": equal_raw}, equal_factors)["low"]
    assert equal_economic.iloc[0, 0] == equal_economic.iloc[1, 0]
    below_one_tick = price_precision(pd.Series([31.517253332702767, 31.517253332702764]))
    assert below_one_tick.iloc[0] == below_one_tick.iloc[1]
    unit_factor = pd.DataFrame(1., index=dates, columns=c.columns)
    pd.testing.assert_frame_equal(
        full_shape_score(normalized_economic(economic, unit_factor), candidates),
        full_shape_score(normalized_economic(economic, unit_factor*100), candidates),
    )
    import sqlite3
    from types import SimpleNamespace
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE adjust_factors(code TEXT,trade_date TEXT,hfq_factor REAL)")
        connection.executemany("INSERT INTO adjust_factors VALUES(?,?,?)", [
            ("600001", "2024-01-01", 3.4672447009574), ("600001", "2024-01-03", 99.),
            ("600002", "2024-01-02", 2.),
        ])
        probe = pd.DataFrame({"600001": [9.09, 9.09]}, index=["2024-01-01", "2024-01-02"])
        stored = snapshot_factors(SimpleNamespace(conn=connection), probe)
        assert stored.iloc[0, 0] == stored.iloc[1, 0] == 3.4672447009574
        try:
            snapshot_factors(SimpleNamespace(conn=connection), probe.rename(columns={"600001": "600002"}))
        except ValueError:
            pass
        else:
            raise AssertionError("A future factor must not backfill a quoted earlier day")
    finally:
        connection.close()
    return {"status": "passed", "checks": ["breadth_excludes_insufficient_history", "today_index_close_not_used",
            "today_stock_close_not_used", "market_Tminus1_and_stock_Tminus2", "relative_returns_same_endpoints",
            "full_score_economic_scale_invariance", "full_score_prefix_causal", "same_raw_and_factor_equal_price",
            "floating_point_noise_is_not_price_break", "normalized_score_scale_invariance", "factor_cutoff_no_future_backfill"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["self-check", "freeze", "train", "evaluate"])
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.phase == "self-check":
        print(json.dumps(self_check()), flush=True)
        return
    if args.phase == "freeze":
        if (OUTPUT / "PLAN.json").exists():
            raise FileExistsError("Regime plan already frozen")
        check = self_check()
        write_json(OUTPUT / "PLAN.json", plan())
        write_json(OUTPUT / "self-check.json", check)
        print(json.dumps({"frozen": True, "plan_sha256": sha256(OUTPUT / "PLAN.json")}), flush=True)
        return
    frozen = json.loads((OUTPUT / "PLAN.json").read_text(encoding="utf-8"))
    if sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"] or sha256(GROUPS) != frozen["groups_sha256"]:
        raise AssertionError("Frozen source/data/metadata changed")
    if args.phase == "train":
        if (OUTPUT / "training-shortlist.json").exists():
            raise FileExistsError("Training already completed")
        train = evaluate("train", VARIANTS)
        short = shortlist(train)
        write_json(OUTPUT / "training-shortlist.json", short)
        print(json.dumps(short), flush=True)
        return
    short = json.loads((OUTPUT / "training-shortlist.json").read_text(encoding="utf-8"))
    if short["train_sha256"] != sha256(OUTPUT / "train-summary.json") or short["plan_sha256"] != sha256(OUTPUT / "PLAN.json"):
        raise AssertionError("Training shortlist changed")
    if not short["selected"]:
        raise ValueError("No eligible training method: stop this mechanism family")
    stages = {"train": json.loads((OUTPUT / "train-summary.json").read_text(encoding="utf-8"))}
    for segment in ("validation_2025h2", "observed_2026"):
        if (OUTPUT / f"{segment}-summary.json").exists():
            raise FileExistsError("Later period already evaluated")
        stages[segment] = evaluate(segment, [name for name in short["selected"] if name in VARIANTS])
    if sources() != frozen["sources"] or sha256(DB) != frozen["snapshot_sha256"] or sha256(GROUPS) != frozen["groups_sha256"]:
        raise AssertionError("Frozen source/data/metadata changed during evaluation")
    write_json(OUTPUT / "summary.json", {"completed_at": now(), "shortlist": short, "segments": stages,
               "later": later_summary(short, stages), "source_data_groups_unchanged": True})
    print(json.dumps({"completed": True, "selected": short["selected"]}), flush=True)


if __name__ == "__main__":
    main()
