"""Offline T-1 necessary-condition superset for full-pool intraday feasibility.

No execution, return labels, models, strategy mutations or network requests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.market import is_st_name  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore  # noqa: E402
from tools.research_double_yin_regime import normalized_economic, snapshot_factors  # noqa: E402
from tools.research_impulse_scoring import now  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

DB = ROOT/".local/chinext-payoff-20261004/market.db"
OUTPUT = ROOT/"docs/research/2026-10-04-contraction-intraday-feasibility/prepool"
SPLITS = {"train": ("2024-01-01", "2025-06-30"),
          "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}
OLD = ROOT/"docs/research/2026-10-04-contraction-vwap"


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            result.update(block)
    return result.hexdigest()


def sources():
    paths = ["tools/research_contraction_intraday_prepool.py", "src/strategy/application/contraction_rebreakout.py",
        "tools/research_double_yin_regime.py", "src/market/infrastructure/store_panel.py",
        "src/market/domain/universe.py", "src/formula/domain/functions.py"]
    return {p: sha(ROOT/p) for p in paths}


def past_features(economic: dict) -> dict:
    """Every row is observed at S close and applies only to the NEXT market day.

    At S=T-1, impulse.rolling(10).sum().shift(2) spans T-12..T-3.
    The function does not know T prices, candidate keys, returns or metadata.
    """
    o, h, low, c, v = (economic[k] for k in ("open", "high", "low", "close", "volume"))
    positive_c = np.isfinite(c) & c.gt(0)
    bars = positive_c.cumsum()
    valid = (positive_c & np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(v)
        & o.gt(0) & low.gt(0) & v.gt(0) & h.ge(c) & h.ge(o) & low.le(c) & low.le(o))
    valid13 = valid.rolling(13).sum().eq(13)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        growth = c/c.shift(1)
        impulse = growth.ge(1.05) & c.gt(o)
        impulse_count = impulse.rolling(10).sum().shift(2)
        finite_growth = np.isfinite(growth).astype(float).rolling(10).sum().shift(2).eq(10)
        ma5 = v.rolling(5).mean()
        contraction = v.lt(ma5) & v.shift(1).lt(ma5.shift(1))
        pullback = c.lt(c.shift(1)) & c.shift(1).lt(c.shift(2))
        contraction_ratio = (v/ma5 + v.shift(1)/ma5.shift(1))/2
        pullback_depth = 1-c/c.shift(2)
        prior_high = h.rolling(5).max()
        momentum_denominator = c.shift(9)  # T-10 at S=T-1.
    finite_past = (finite_growth & np.isfinite(contraction_ratio) & np.isfinite(pullback_depth)
        & np.isfinite(prior_high) & prior_high.gt(0) & np.isfinite(momentum_denominator) & momentum_denominator.gt(0))
    eligible = (valid13 & bars.ge(30) & impulse_count.gt(0) & pullback & contraction & finite_past).fillna(False)
    return dict(eligible=eligible, valid_previous13=valid13, bars_asof=bars, prior_impulse_count=impulse_count,
        prior_finite_growth=finite_growth, two_day_pullback=pullback, two_day_contraction=contraction,
        prior_high5_economic=prior_high, previous_close_economic=c, close_Tminus3_economic=c.shift(2),
        momentum_denominator_Tminus10=momentum_denominator, previous_volume=v, previous_ma5_volume=ma5,
        volume_Tminus2=v.shift(1), ma5_volume_Tminus2=ma5.shift(1), contraction_ratio=contraction_ratio,
        pullback_depth_pct=pullback_depth*100,
        contraction_score15=((1-contraction_ratio)/.5).clip(0, 1)*15,
        pullback_depth_score15=(1-pullback_depth/.10).clip(0, 1)*15)


def prepare():
    store = CutoffMarketStore(DB, "2026-09-30")
    try:
        metadata = {str(row["code"]): dict(row) for row in store.conn.execute("SELECT * FROM instruments WHERE instrument_type='STOCK'")
            if len(str(row["code"])) == 6 and str(row["code"]).isascii() and str(row["code"]).isdigit()
            and str(row["code"]).startswith(("300", "301"))}
        first_quote = str(store.conn.execute("SELECT MIN(trade_date) FROM quotes_daily").fetchone()[0])
        dates = [str(d) for d in store.trading_days(start=first_quote, end="2026-09-30")]
        if len(dates) < 2 or dates[-1] != "2026-09-30":
            raise AssertionError("Unexpected market calendar endpoint")
        index = pd.Index(dates[:-1], name="trade_date")
        codes = sorted(metadata)
        raw = store.load_panel(fields=("open", "high", "low", "close", "volume"), codes=codes,
            start=first_quote, end=dates[-2], adjust="none", min_bars=0)
        raw = {k: v.reindex(index=index, columns=codes) for k, v in raw.items()}
        factors = snapshot_factors(store, raw["close"])
        economic = normalized_economic(raw, factors)
        return dict(raw=raw, factors=factors, economic=economic, dates=dates, metadata=metadata,
            first_quote=first_quote, last_quote_read=dates[-2])
    finally:
        store.close()


def summarize_daily(daily: pd.DataFrame, pool: pd.DataFrame) -> dict:
    values = daily.potential_codes
    return dict(market_days=len(daily), active_days=int(values.gt(0).sum()), empty_days=int(values.eq(0).sum()),
        potential_code_days=int(values.sum()), distinct_codes=int(pool.code.nunique()),
        mean_per_market_day=float(values.mean()), median=float(values.median()),
        p90=float(values.quantile(.9)), p95=float(values.quantile(.95)), max_per_day=int(values.max()),
        max_dates=daily.loc[values.eq(values.max()), "target_date"].tolist())


def coverage_check(pool: pd.DataFrame, output: Path):
    keys = set(zip(pool.target_date, pool.code))
    result, missing = {}, []
    for segment in SPLITS:
        path = OLD/segment/"all-candidate-qualifications.csv"
        # Only keys and candidate-membership flags, read AFTER prepool receipt.
        frame = pd.read_csv(path, usecols=["signal_date", "code", "corrected_candidate", "legacy_candidate"], dtype={"code": str})
        result[segment] = dict(input_sha256=sha(path))
        for version in ("corrected_candidate", "legacy_candidate"):
            expected = set(frame.loc[frame[version], ["signal_date", "code"]].itertuples(index=False, name=None))
            absent = sorted(expected-keys)
            result[segment][version] = dict(candidate_keys=len(expected), covered=len(expected)-len(absent), missing=len(absent))
            missing.extend(dict(segment=segment, kind=version, target_date=d, code=c) for d, c in absent)
    pd.DataFrame(missing, columns=["segment", "kind", "target_date", "code"]).to_csv(output/"coverage-missing-keys.csv", index=False)
    return dict(all_known_daily_candidates_covered=not missing, segments=result,
        future_candidate_keys_used_only_after_prepool_persisted=True)


def prefix_check(prepared: dict, whole: dict) -> dict:
    dates = prepared["dates"]
    previous = dict(zip(dates[1:], dates[:-1]))
    tests = []
    for start, end in SPLITS.values():
        target_dates = [d for d in dates if start <= d <= end]
        for target in (target_dates[0], target_dates[-1]):
            asof = previous[target]
            raw = {k: v.loc[:asof] for k, v in prepared["raw"].items()}
            factor = prepared["factors"].loc[:asof]
            prefix = past_features(normalized_economic(raw, factor))
            for key, frame in prefix.items():
                pd.testing.assert_frame_equal(frame, whole[key].loc[:asof], check_exact=True)
            tests.append(dict(target_date=target, last_input_date=asof, fields_checked=len(prefix), exact_prefix_equal=True))
    return dict(passed=True, actual_prefix_tests=tests, current_target_bar_never_required=True)


def self_check():
    dates = pd.Index([f"d{i:02d}" for i in range(45)])
    codes = ["300001"]
    raw = {k: pd.DataFrame(10., index=dates, columns=codes) for k in ("open", "high", "low", "close")}
    raw["volume"] = pd.DataFrame(100., index=dates, columns=codes)
    raw["close"].iloc[33:36, 0] = [10.6, 10.4, 10.2]
    raw["open"].iloc[33:36, 0] = [10., 10.6, 10.4]
    raw["high"].iloc[33:36, 0] = [10.7, 10.6, 10.4]
    raw["low"].iloc[33:36, 0] = [10., 10.3, 10.1]
    raw["volume"].iloc[33:36, 0] = [400., 50., 40.]
    full = past_features(raw)
    assert full["eligible"].iloc[35, 0]
    assert not full["eligible"].iloc[:29, 0].any()
    for s in range(13, 45):
        c, o = raw["close"].iloc[:, 0], raw["open"].iloc[:, 0]
        expected = sum(c.iloc[j]/c.iloc[j-1] >= 1.05 and c.iloc[j] > o.iloc[j] for j in range(s-11, s-1))
        assert full["prior_impulse_count"].iloc[s, 0] == expected
    prefix = past_features({k: value.iloc[:36] for k, value in raw.items()})
    poisoned = {k: value.copy() for k, value in raw.items()}
    for value in poisoned.values():
        value.iloc[36:] = np.nan
    future_changed = past_features(poisoned)
    for key, frame in prefix.items():
        pd.testing.assert_frame_equal(frame, full[key].iloc[:36], check_exact=True)
        pd.testing.assert_frame_equal(frame, future_changed[key].iloc[:36], check_exact=True)
    missing = {k: value.copy() for k, value in raw.items()}
    missing["volume"].iloc[23, 0] = np.nan  # T-13 for T36.
    assert not past_features(missing)["eligible"].iloc[35, 0]
    return dict(passed=True, synthetic_only=True, checks=["T-12..T-3 exact impulse window", "T-13 growth origin and valid13",
        "at least30 prior closes", "two-day shrink/pullback", "future poisoning cannot alter current prepool", "exact prefix equality"])


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    if (output/"PLAN.json").exists():
        raise FileExistsError("Preserve frozen feasibility output")
    before = sources()
    dbhash = sha(DB)
    checks = self_check()
    plan = dict(created_at=now(), sources=before, snapshot_sha256=dbhash, contract_sha256=sha(output/"PLAN.md"),
        splits=SPLITS, no_returns=True, no_network=True, no_today_input=True,
        scope="All snapshot STOCK300/301, current catalog identity only; necessary-condition superset, no Top2.")
    write_json(output/"PLAN.json", plan)
    write_json(output/"freeze-receipt.json", dict(created_at=now(), plan_sha256=sha(output/"PLAN.json")))
    prepared = prepare()
    features = past_features(prepared["economic"])
    dates = prepared["dates"]
    next_day = dict(zip(dates[:-1], dates[1:]))
    target_dates = [d for d in dates if "2024-01-01" <= d <= "2026-09-30"]
    target_set = set(target_dates)
    rows = []
    for row, col in zip(*np.nonzero(features["eligible"].to_numpy())):
        asof = str(features["eligible"].index[row])
        target = next_day[asof]
        if target not in target_set:
            continue
        code = str(features["eligible"].columns[col])
        meta = prepared["metadata"][code]
        name, status = str(meta.get("name") or ""), str(meta.get("status") or "")
        rows.append(dict(target_date=target, asof_date=asof, code=code,
            current_name=name, current_status=status, current_list_date=str(meta.get("list_date") or ""),
            current_static_clean=bool(name.strip() and not is_st_name(name) and "退" not in name and status not in ("delisted", "suspended")),
            raw_previous_close=float(prepared["raw"]["close"].iat[row, col]), factor_asof=float(prepared["factors"].iat[row, col]),
            **{key: frame.iat[row, col].item() for key, frame in features.items() if key != "eligible"}))
    pool = pd.DataFrame(rows).sort_values(["target_date", "code"]).reset_index(drop=True)
    pool.to_csv(output/"potential-code-days.csv", index=False)
    counts = pool.groupby("target_date").size()
    static_counts = pool[pool.current_static_clean].groupby("target_date").size()
    daily = pd.DataFrame([dict(target_date=d, potential_codes=int(counts.get(d, 0)), current_static_clean_codes=int(static_counts.get(d, 0))) for d in target_dates])
    daily.to_csv(output/"daily-counts.csv", index=False)
    write_json(output/"prepool-receipt-before-coverage.json", dict(created_at=now(), pool_sha256=sha(output/"potential-code-days.csv"),
        daily_sha256=sha(output/"daily-counts.csv"), final_candidate_keys_not_yet_read=True, returns_never_read=True))
    prefix = prefix_check(prepared, features)
    coverage = coverage_check(pool, output)
    segments, samples = {}, []
    for segment, (start, end) in SPLITS.items():
        subset = pool[pool.target_date.between(start, end)]
        segments[segment] = summarize_daily(daily[daily.target_date.between(start, end)], subset)
        if len(subset):
            samples.append(dict(segment=segment, **subset.iloc[0][["target_date", "asof_date", "code"]].to_dict(),
                selection="lexical first(date,code) from complete T-1 pool, no returns/current-day outcome selection"))
    annual = {str(year): summarize_daily(daily[daily.target_date.str.startswith(str(year))], pool[pool.target_date.str.startswith(str(year))]) for year in (2024, 2025, 2026)}
    months = []
    for month, days in daily.groupby(daily.target_date.str[:7]):
        months.append(dict(month=month, **summarize_daily(days, pool[pool.target_date.str.startswith(month)])))
    pd.DataFrame(months).to_csv(output/"monthly-counts.csv", index=False)
    write_json(output/"deterministic-probe-samples.json", samples)
    if sources() != before or sha(DB) != dbhash:
        raise AssertionError("Frozen inputs changed")
    summary = dict(completed_at=now(), catalog_codes=len(prepared["metadata"]), first_quote=prepared["first_quote"],
        last_quote_read=prepared["last_quote_read"], full=summarize_daily(daily, pool), segments=segments, years=annual,
        current_static_clean_potential_code_days=int(pool.current_static_clean.sum()),
        current_static_filter_not_applied=True, no_return_or_network_calls=True, frozen_inputs_unchanged=True,
        plan_sha256=sha(output/"PLAN.json"), synthetic_checks=checks, prefix_checks=prefix,
        daily_candidate_coverage=coverage, deterministic_samples=samples)
    write_json(output/"summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("self-check", "run"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "self-check":
        print(json.dumps(self_check()))
    else:
        run(args.output.resolve())
