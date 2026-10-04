"""Prepare one immutable next-session T-1 research pool; never fetch or rank T.

Run through tools/isolated_check.py. Uses the already-frozen past_features;
prepare writes a new local evidence directory, verify replays its input pool.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.market import is_st_name  # noqa: E402
from src.market.domain.exchange_schedule import HOLIDAYS, scheduled_trading_days  # noqa: E402
from tools import research_contraction_intraday_prepool as prepool  # noqa: E402

AS_OF = "2026-09-30"
OUTPUT = ROOT / "docs/research/2026-10-04-next-evidence/contraction-prepared"
OFFICIAL = OUTPUT.parent / "exchange-session-evidence.json"
CALENDAR = ROOT / "data/exchange_calendar.json"
FEATURE_COLUMNS = ["eligible", "valid_previous13", "bars_asof", "prior_impulse_count", "prior_finite_growth",
    "two_day_pullback", "two_day_contraction", "prior_high5_economic", "previous_close_economic",
    "close_Tminus3_economic", "momentum_denominator_Tminus10", "previous_volume", "previous_ma5_volume",
    "volume_Tminus2", "ma5_volume_Tminus2", "contraction_ratio", "pullback_depth_pct", "contraction_score15",
    "pullback_depth_score15"]


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def bindings():
    old = read(prepool.OUTPUT / "PLAN.json")
    assert prepool.sources() == old["sources"], "Frozen past-feature sources changed"
    assert sha(prepool.DB) == old["snapshot_sha256"]
    paths = {ROOT / p for p in old["sources"]}
    paths.update([Path(__file__), prepool.OUTPUT / "PLAN.json", prepool.OUTPUT / "potential-code-days.csv",
        prepool.DB.parent / "export-manifest.json", OFFICIAL, CALENDAR,
        ROOT / "src/market/domain/exchange_schedule.py"])
    return dict(database_path=prepool.DB.relative_to(ROOT).as_posix(), database_sha256=sha(prepool.DB),
                files_sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)})


def calendar_evidence():
    saved = read(CALENDAR)
    official = read(OFFICIAL)
    years = {int(k): v for k, v in saved["years"].items()}
    first = (date.fromisoformat(AS_OF) + timedelta(days=1)).isoformat()
    last = (date.fromisoformat(AS_OF) + timedelta(days=31)).isoformat()
    builtin = scheduled_trading_days(first, last, holidays=HOLIDAYS)
    existing = scheduled_trading_days(first, last, holidays=years)
    assert builtin and existing and builtin[0] == existing[0] == official["planned_next_trade_date"]
    assert official["as_of_market_date"] == AS_OF and official["authorizes_realtime_execution"] is False
    checked = datetime.fromtimestamp(saved["checked_at"], ZoneInfo("Asia/Shanghai")).isoformat()
    return dict(planned_target_date=existing[0], as_of=AS_OF, planning_only=True,
        official_fact_extraction=official, saved_calendar_checked_at=checked,
        saved_calendar_older_than72h=(datetime.now().timestamp() - saved["checked_at"] > 72 * 3600),
        builtin_and_saved_schedule_agree=True, no_calendar_refresh=True, realtime_execution_ready=False)


def prepare_data():
    store = prepool.CutoffMarketStore(prepool.DB, AS_OF)
    try:
        metadata = {str(r["code"]): dict(r) for r in store.conn.execute("SELECT * FROM instruments WHERE instrument_type='STOCK'")
            if len(str(r["code"])) == 6 and str(r["code"]).isascii() and str(r["code"]).isdigit()
            and str(r["code"]).startswith(("300", "301"))}
        codes = sorted(metadata)
        first_quote = store.conn.execute("SELECT MIN(trade_date) FROM quotes_daily").fetchone()[0]
        dates = pd.Index(store.trading_days(start=first_quote, end=AS_OF), name="trade_date")
        assert dates[-1] == AS_OF
        raw = store.load_panel(fields=("open", "high", "low", "close", "volume"), codes=codes,
                               start=first_quote, end=AS_OF, adjust="none", min_bars=0)
        raw = {k: frame.reindex(index=dates, columns=codes) for k, frame in raw.items()}
        factors = prepool.snapshot_factors(store, raw["close"])
        economic = prepool.normalized_economic(raw, factors)
        features = prepool.past_features(economic)
        # New Sep30 input may not alter Sep29's already-frozen past features.
        previous = str(dates[-2])
        prefix = prepool.past_features({k: frame.loc[:previous] for k, frame in economic.items()})
        for key in FEATURE_COLUMNS:
            pd.testing.assert_series_equal(features[key].loc[previous], prefix[key].loc[previous], check_exact=True)
        previous_keys = set(features["eligible"].columns[features["eligible"].loc[previous]])
        old = pd.read_csv(prepool.OUTPUT / "potential-code-days.csv", usecols=["target_date", "code"], dtype={"code": str})
        assert previous_keys == set(old.loc[old.target_date.eq(AS_OF), "code"])
        window = list(map(str, dates[-13:]))
        q = {(r["trade_date"], r["code"]): dict(r) for r in store.conn.execute(
            "SELECT trade_date,code,open,high,low,close,volume,amount,source,receipt_id,fetched_at FROM quotes_daily WHERE trade_date>=? AND trade_date<=?",
            (window[0], AS_OF)) if r["code"] in metadata}
        fr = {}
        for r in store.conn.execute("SELECT code,trade_date,hfq_factor,source,fetched_at FROM adjust_factors WHERE trade_date<=? ORDER BY code,trade_date", (AS_OF,)):
            if r["code"] in metadata:
                fr.setdefault(r["code"], []).append(dict(r))
        ledger, inputs = [], []
        for code in codes:
            source_factors = fr.get(code, [])
            factor_days = [r["trade_date"] for r in source_factors]
            f = {k: features[k].at[AS_OF, code].item() for k in FEATURE_COLUMNS}
            finite_past = bool(f["prior_finite_growth"] and all(np.isfinite(f[k]) for k in
                ("contraction_ratio", "pullback_depth_pct", "prior_high5_economic", "momentum_denominator_Tminus10"))
                and f["prior_high5_economic"] > 0 and f["momentum_denominator_Tminus10"] > 0)
            reasons = [reason for passed, reason in (
                (f["valid_previous13"], "incomplete_or_invalid_previous13"), (f["bars_asof"] >= 30, "fewer_than30_prior_positive_closes"),
                (f["prior_impulse_count"] > 0, "no_prior_strong_bull"), (f["two_day_pullback"], "two_day_pullback_not_met"),
                (f["two_day_contraction"], "two_day_volume_contraction_not_met"), (finite_past, "past_reference_or_ratio_unknown")) if not passed]
            assert bool(f["eligible"]) == (not reasons)
            meta = metadata[code]
            name, status = str(meta["name"] or ""), str(meta["status"] or "")
            static_clean = bool(name.strip() and not is_st_name(name) and "退" not in name and status not in ("delisted", "suspended"))
            asof_factor = source_factors[-1]["hfq_factor"] if source_factors else np.nan
            ledger.append({**meta, **f, "as_of": AS_OF, "raw_previous_close": raw["close"].at[AS_OF, code],
                "factor_asof_for_past_coordinate": asof_factor, "current_static_clean": static_clean,
                "static_filter_applied": False, "target_identity_recheck_pending": True,
                "capture_requested_by_necessary_pool": bool(f["eligible"]),
                "preparation_class": "necessary_pool" if f["eligible"] else "past_data_incomplete" if not f["valid_previous13"] or not finite_past else "past_conditions_failed",
                "exclusion_reasons": json.dumps(reasons, ensure_ascii=False)})
            for day in window:
                row = q.get((day, code), {})
                fi = bisect_right(factor_days, day) - 1
                factor = source_factors[fi] if fi >= 0 else {}
                quote_values = {k: row.get(k) for k in ("open", "high", "low", "close", "volume", "amount", "source", "receipt_id", "fetched_at")}
                inputs.append(dict(code=code, trade_date=day, quote_row_present=bool(row), **quote_values,
                    hfq_factor=factor.get("hfq_factor"), factor_effective_date=factor.get("trade_date"),
                    factor_source=factor.get("source"), factor_fetched_at=factor.get("fetched_at"),
                    factor_missing_no_backfill=not bool(factor)))
        full = pd.DataFrame(ledger).sort_values("code").reset_index(drop=True)
        pool = full[full.eligible].reset_index(drop=True)
        observed = pd.DataFrame(inputs).sort_values(["trade_date", "code"]).reset_index(drop=True)
        assert len(full) == len(codes) and not full.code.duplicated().any() and len(observed) == len(codes) * 13
        assert observed.trade_date.max() == AS_OF and all(frame.index.max() == AS_OF for frame in raw.values())
        assert not any("rank" in col or "return" in col for col in full.columns)
        evidence = dict(catalog_codes=len(codes), necessary_pool_codes=len(pool),
            necessary_pool_current_static_clean=int(pool.current_static_clean.sum()),
            necessary_pool_identity_recheck_codes=int((~pool.current_static_clean).sum()),
            excluded_by_past_conditions_or_quality=int((~full.eligible).sum()),
            past_data_incomplete_codes=int(full.preparation_class.eq("past_data_incomplete").sum()),
            raw_input_rows=len(observed), raw_input_market_days=13, first_quote=first_quote,
            first_exported_quote_date=window[0], latest_input_date=AS_OF,
            previous_asof_prefix_exact=previous, prefix_fields_checked=len(FEATURE_COLUMNS),
            frozen_previous_target_pool_keys_match=len(previous_keys), all_catalog_rows_accounted_for=True,
            static_identity_filter_not_applied=True, target_rows_read=0, target_rank_available=False,
            source_catalog_updated_at_max=max(str(m["updated_at"] or "") for m in metadata.values()))
        return full, pool, observed, evidence
    finally:
        store.close()


def verify(output):
    manifest = read(output / "manifest.json")
    assert bindings() == manifest["bindings"]
    for name, expected in manifest["artifacts_sha256"].items():
        assert sha(output / name) == expected
    full, pool, observed, evidence = prepare_data()
    for name, current in (("all-codes.csv", full), ("necessary-pool.csv", pool)):
        saved = pd.read_csv(output / name, dtype={"code": str}, float_precision="round_trip")
        assert list(saved.code) == list(current.code)
        pd.testing.assert_frame_equal(saved[["code", *FEATURE_COLUMNS]], current[["code", *FEATURE_COLUMNS]], check_dtype=False, check_exact=True)
        assert saved.current_static_clean.tolist() == current.current_static_clean.tolist()
    saved_inputs = pd.read_csv(output / "daily-inputs.csv", dtype={"code": str}, float_precision="round_trip")
    keys = ["code", "trade_date", "quote_row_present", "open", "high", "low", "close", "volume", "amount", "hfq_factor", "factor_missing_no_backfill"]
    pd.testing.assert_frame_equal(saved_inputs[keys], observed[keys], check_dtype=False, check_exact=True)
    assert evidence == manifest["preparation_evidence"]
    assert manifest["planned_target_date"] == calendar_evidence()["planned_target_date"]
    return dict(verified_at=now(), verified=True, source_database_and_code_hashes_unchanged=True,
        replayed_all_catalog_rows=len(full), replayed_necessary_pool_rows=len(pool), replayed_input_rows=len(observed),
        no_future_prices_or_factors=True, no_ranking_or_returns=True, manifest_sha256=sha(output / "manifest.json"))


def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError("Prepare requires a new empty evidence directory; never overwrite a prior manifest")
    before = bindings()
    calendar = calendar_evidence()
    prepared_at = now()
    plan = dict(created_at=prepared_at, as_of=AS_OF, planned_target_date=calendar["planned_target_date"],
        bindings=before, no_network=True, no_production_write=True, no_target_inputs=True,
        no_target_scores_or_returns=True, reuse_frozen_past_features=True, current_static_filter_applied=False)
    write_new(output / "PLAN.json", plan)
    full, pool, observed, evidence = prepare_data()
    full.to_csv(output / "all-codes.csv", index=False)
    pool.to_csv(output / "necessary-pool.csv", index=False)
    observed.to_csv(output / "daily-inputs.csv", index=False)
    write_new(output / "calendar-evidence.json", calendar)
    assert bindings() == before
    manifest = dict(prepared_at=prepared_at, completed_at=now(), status="prepared_inputs_only_not_execution_ready",
        as_of=AS_OF, planned_target_date=calendar["planned_target_date"], bindings=before,
        preparation_evidence=evidence,
        candidate_codes=pool.code.tolist(), candidate_code_contract="All pure T-1 necessary-pool codes including any current ST/identity warnings; no Top2 or current_static_clean filter",
        artifacts_sha256={p.name: sha(p) for p in output.iterdir() if p.is_file()},
        purpose="One next-session complete T-1 necessary-pool evidence bundle; not a strategy enhancement or trade recommendation",
        identity_contract="Full snapshot STOCK300/301 catalog preserved. Current names/statuses are snapshot-observed metadata, not Sep30 PIT. Do not apply current_static_clean to the necessary pool; recheck T identity.",
        factor_contract="Only asof and earlier direct effective factors are inputs. T adjustment factor and the T raw previous-close bridge are NOT observed and are NOT forward-filled.",
        pending_target_inputs=["target_session_validation", "target_identity", "target_adjustment_factor_and_previous_close_bridge",
            "full_pool_live_prices_and_cumulative_volume", "per_code_source_time_and_acceptance", "decision_after_input_completion", "prices_observed_after_decision"],
        input_availability="Prepared on the timestamp above from the existing read-only snapshot; stored source fetched_at is retained verbatim. Not an assertion of availability at Sep30 close.",
        full_history_replay="Resolve the bound read-only SQLite snapshot by SHA256; daily-inputs.csv materializes the last13 session fields with quote/factor provenance. Whole-history positive-close counts are replayed from the snapshot.",
        cannot_rank=True, no_signals_or_orders_created=True, historical_failed_candidates_not_renominated=True)
    write_new(output / "manifest.json", manifest)
    verification = verify(output)
    write_new(output / "verification.json", verification)
    print(json.dumps(dict(target=manifest["planned_target_date"], **evidence, **verification), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.output.resolve())
    else:
        print(json.dumps(verify(args.output.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
