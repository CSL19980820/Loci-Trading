"""Immutable closed-bar input bundle; no target opening, rank, returns or live job."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.market import resolve_universe  # noqa: E402
from src.market.domain.universe import classify_board, is_st_name, is_delisting_name, _list_age_days  # noqa: E402
from src.strategy.application.double_yin_low_open import DoubleYinLowOpenV1  # noqa: E402
from tools.research_chinext_payoff_exits import CutoffMarketStore, sha256  # noqa: E402
from tools.research_double_yin_regime import DB, GROUPS, normalized_economic, snapshot_factors, price_precision  # noqa: E402

OUTPUT = ROOT / "docs/research/2026-10-04-next-evidence/double-yin-prepared"
SESSION = OUTPUT.parent / "exchange-session-evidence.json"
CLOSED, TARGET = "2026-09-30", "2026-10-08"
PRICE_FIELDS = ["open", "high", "low", "close", "volume"]
GEOMETRY_FACTORS = ["有效历史满足", "前日大涨收阳", "昨日收阴", "昨日倍量", "近期涨幅未超限"]


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_new(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(clean(value), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def csv_new(path, frame):
    with path.open("x", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False)


def protected():
    frozen = read(ROOT / "docs/research/2026-10-04-double-yin-vwap/PLAN.json")
    assert sha256(DB) == frozen["snapshot_sha256"] and sha256(GROUPS) == frozen["groups_sha256"]
    for name, digest in frozen["sources"].items():
        assert sha256(ROOT / name) == digest, name
    session = read(SESSION)
    assert session["as_of_market_date"] == CLOSED and session["planned_next_trade_date"] == TARGET
    assert not session["authorizes_realtime_execution"]
    paths = [Path(__file__), OUTPUT / "PLAN.md", OUTPUT / "existing-raw-pool.json", SESSION, GROUPS,
             ROOT / "docs/research/2026-10-04-double-yin-vwap/PLAN.json",
             ROOT / "src/market/domain/universe.py", ROOT / "src/market/application/double_yin_inputs.py",
             ROOT / "tools/strategy_chinext_review.py"]
    paths.extend(ROOT / name for name in frozen["sources"])
    return dict(snapshot_sha256=frozen["snapshot_sha256"],
                files_sha256={p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(set(paths))})


def align_factors(sparse, days, codes):
    """Only observed past dates; no future bfill or neutral factor for quotes."""
    wide = sparse.pivot(index="trade_date", columns="code", values="hfq_factor")
    union = wide.index.union(pd.Index(days)).sort_values()
    aligned = {}
    for original, output in (("hfq_factor", "factor"), ("source", "factor_source"), ("fetched_at", "factor_fetched_at")):
        part = sparse.pivot(index="trade_date", columns="code", values=original)
        aligned[output] = part.reindex(union).ffill().reindex(index=days, columns=codes)
    stamped = sparse.assign(factor_observation_date=sparse.trade_date).pivot(
        index="trade_date", columns="code", values="factor_observation_date")
    aligned["factor_observation_date"] = stamped.reindex(union).ffill().reindex(index=days, columns=codes)
    return aligned


def append_unknown_target(panels, names):
    result = {}
    for field in PRICE_FIELDS:
        result[field] = panels[field].reindex([*panels[field].index, TARGET]).copy()
        result[field].loc[TARGET] = np.nan
    return {**result, "__instrument_names__": names, "__sector_groups__": {}}


def geometry(computed):
    frame = pd.Series(True, index=computed.factors[GEOMETRY_FACTORS[0]].columns)
    for name in GEOMETRY_FACTORS:
        frame &= computed.factors[name].loc[TARGET].fillna(False)
    return frame.astype(bool)


def identities(catalog, resolved):
    allowed = set(resolved.codes)
    rows = []
    for original in catalog:
        row = dict(original)
        code, name = str(row["code"]), str(row.get("name") or "")
        board, status = classify_board(code), str(row.get("status") or "normal")
        age = _list_age_days(str(row.get("list_date") or ""), CLOSED)
        reasons = []
        if board != "main":
            reasons.append("outside_main_board")
        if is_st_name(name):
            reasons.append("current_name_ST")
        if status == "delisted" or is_delisting_name(name):
            reasons.append("current_delisting_identity")
        if status == "suspended":
            reasons.append("current_status_suspended")
        if age is not None and age < 60:
            reasons.append("current_listing_age_under_60_calendar_days")
        if not name.strip():
            reasons.append("current_name_missing")
        if "退" in name and "current_delisting_identity" not in reasons:
            reasons.append("engine_current_name_contains_delisting_marker")
        assert code in allowed or reasons, f"No exclusion explanation for {code}"
        rows.append({**row, "board_bucket": board, "catalog_row_captured_at": now(),
            "in_resolved_current_universe": code in allowed, "current_identity_exclusions": "|".join(reasons),
            "listing_age_as_of_closed": age, "target_identity_verified": False})
    return pd.DataFrame(rows)


def prepare():
    if (OUTPUT / "manifest.json").exists():
        verify()
        print("Equivalent existing immutable bundle verified; no rebuilding or network requests")
        return
    inputs_before = protected()
    checks = self_check()
    engine = DoubleYinLowOpenV1()
    params = engine.default_params()
    raw_reference = read(OUTPUT / "existing-raw-pool.json")
    reference_payload = raw_reference["public_payload"]
    canonical = json.dumps(reference_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == raw_reference["source_payload_sha256"]
    assert reference_payload["as_of"] == CLOSED and reference_payload["target_trade_date"] == TARGET
    captured_at = now()
    store = CutoffMarketStore(DB, CLOSED)
    try:
        calendar = store.trading_days(end=CLOSED)
        assert calendar[-1] == CLOSED and not store.conn.execute(
            "SELECT 1 FROM quotes_daily WHERE trade_date>? LIMIT 1", (CLOSED,)).fetchone()
        days = calendar[-(engine.history_bars(params)+4):]
        catalog = list(store.list_instruments(instrument_type="STOCK", status=""))
        resolved = resolve_universe(store, engine.default_universe, as_of=CLOSED)
        identity = identities(catalog, resolved)
        codes = sorted(identity.loc[identity.board_bucket.eq("main"), "code"].astype(str))
        assert set(resolved.codes).issubset(codes)
        marks = ",".join("?" for _ in codes)
        fields = ["trade_date", "code", "open", "high", "low", "close", "volume", "amount", "source", "receipt_id", "fetched_at"]
        rows = store.conn.execute(f"SELECT {','.join(fields)} FROM quotes_daily WHERE code IN ({marks}) AND trade_date>=? AND trade_date<=? ORDER BY trade_date,code",
                                  [*codes, days[0], CLOSED]).fetchall()
        observed = pd.DataFrame([dict(row) for row in rows], columns=fields)
        observed["quote_row_present"] = True
        index = pd.MultiIndex.from_product([days, codes], names=["trade_date", "code"])
        history = observed.set_index(["trade_date", "code"]).reindex(index).reset_index()
        history["quote_row_present"] = history.quote_row_present.fillna(False).astype(bool)
        panels = {field: history.pivot(index="trade_date", columns="code", values=field).reindex(index=days, columns=codes) for field in PRICE_FIELDS}
        factor_rows = store.conn.execute(f"SELECT code,trade_date,hfq_factor,source,fetched_at FROM adjust_factors WHERE code IN ({marks}) AND trade_date<=? ORDER BY code,trade_date", [*codes, CLOSED]).fetchall()
        direct_all = pd.DataFrame([dict(row) for row in factor_rows])
        anchors = direct_all[direct_all.trade_date.lt(days[0])].groupby("code", sort=False).tail(1)
        sparse = pd.concat([anchors, direct_all[direct_all.trade_date.ge(days[0])]], ignore_index=True).sort_values(["code", "trade_date"])
        assert not sparse.duplicated(["code", "trade_date"]).any()
        alignment = align_factors(sparse, days, codes)
        factors = alignment["factor"].astype(float)
        quoted = np.isfinite(panels["close"]) & panels["close"].gt(0)
        known_factor = np.isfinite(factors) & factors.gt(0)
        missing_factor = quoted & ~known_factor
        if not missing_factor.to_numpy().any():
            frozen_helper = snapshot_factors(store, panels["close"])
            assert np.allclose(factors.where(quoted).to_numpy(), frozen_helper.where(quoted).to_numpy(), equal_nan=True, rtol=0, atol=0)
        names = {str(row["code"]): str(row.get("name") or "") for row in catalog}
        raw_for_engine = append_unknown_target(panels, names)
        economic_closed = normalized_economic(panels, factors)
        economic_for_engine = append_unknown_target(economic_closed, names)
        raw_result = engine.compute(raw_for_engine, params)
        economic_result = engine.compute(economic_for_engine, {**params, "price_floor": 0.})
        for result in (raw_result, economic_result):
            assert not result.signals.loc[TARGET].any()
            assert result.factors["score"].loc[TARGET].isna().all()
            assert not result.factors["条件候选"].loc[TARGET].any()
        plain_geometry, economic_geometry = geometry(raw_result), geometry(economic_result)
        in_scope = pd.Series({code: code in set(resolved.codes) for code in codes})
        current_raw = raw_result.factors["历史形态候选"].loc[TARGET] & in_scope
        current_economic = economic_result.factors["历史形态候选"].loc[TARGET] & in_scope
        observation_codes = sorted(economic_geometry.index[economic_geometry])
        candidate_codes = sorted(current_economic.index[current_economic])
        identity_review = sorted(set(observation_codes)-set(candidate_codes))
        raw_codes = sorted(current_raw.index[current_raw])
        identity = identity.set_index("code", drop=False)
        for code in identity.index:
            identity.at[code, "raw_geometry_matches"] = bool(plain_geometry.get(code, False))
            identity.at[code, "economic_geometry_matches"] = bool(economic_geometry.get(code, False))
            identity.at[code, "current_identity_shape_candidate"] = code in candidate_codes
            identity.at[code, "shape_requires_target_identity_review"] = code in identity_review
            identity.at[code, "factor_missing_quote_cells"] = int(missing_factor[code].sum()) if code in codes else None
            if code in codes:
                failures = [name for name in GEOMETRY_FACTORS if not bool(economic_result.factors[name].at[TARGET, code])]
                identity.at[code, "economic_geometry_exclusions"] = "|".join(failures)
                for name in GEOMETRY_FACTORS:
                    identity.at[code, f"economic_{name}"] = bool(economic_result.factors[name].at[TARGET, code])
                for name in ("大涨日涨幅(%)", "倍量阴量比", "近期累计涨幅(%)"):
                    identity.at[code, f"economic_{name}"] = economic_result.factors[name].at[TARGET, code]
            else:
                identity.at[code, "economic_geometry_exclusions"] = "not_evaluated_outside_main_board"
        factor_ledger = history[["trade_date", "code"]].copy()
        for key, panel in alignment.items():
            factor_ledger[key] = panel.reindex(index=days, columns=codes).to_numpy().reshape(-1)
        factor_ledger["factor_known"] = known_factor.to_numpy().reshape(-1)
        factor_ledger["uses_future_observation"] = False
        assert not factor_ledger.loc[factor_ledger.factor_observation_date.notna(), "factor_observation_date"].gt(CLOSED).any()
        group_document = read(GROUPS)
        saved_groups = group_document["sector_groups"]
        raw_metadata = {item["code"]: item.get("industry", {}) for item in reference_payload["candidates"]}
        metadata = {}
        for code in observation_codes:
            if saved_groups.get(code):
                supplement = group_document.get("supplement_metadata", {}).get(code)
                metadata[code] = {**(supplement or {}), "groups": saved_groups[code], "source": group_document["source"],
                    "classification": group_document["classification"], "historical_membership": False,
                    "fetched_at": supplement.get("fetched_at") if supplement else group_document.get("base_fetched_at", group_document["fetched_at"]),
                    "evidence_file": GROUPS.relative_to(ROOT).as_posix(), "evidence_file_sha256": sha256(GROUPS)}
            elif raw_metadata.get(code, {}).get("groups"):
                metadata[code] = {**raw_metadata[code], "historical_membership": False,
                    "evidence_file": "existing-raw-pool.json", "evidence_file_sha256": sha256(OUTPUT / "existing-raw-pool.json")}
        missing_industry = sorted(set(observation_codes)-set(metadata))
        industry_request = {"requested_codes": missing_industry, "started_at": now(), "only_actual_missing_codes": True,
                            "network_requested": bool(missing_industry), "does_not_filter_shape_pool": True}
        write_new(OUTPUT / "industry-request.json", industry_request)
        if missing_industry:
            assert len(missing_industry) <= 50, "This task does not authorize broad catalog refresh"
            from src.market.application.double_yin_inputs import fetch_double_yin_industries
            fetched, receipt = fetch_double_yin_industries(missing_industry)
            metadata.update({code: {**value, "historical_membership": False} for code, value in fetched.items()})
            write_new(OUTPUT / "industry-response.json", dict(received_at=now(), metadata=fetched, receipt=receipt))
        else:
            write_new(OUTPUT / "industry-response.json", dict(received_at=now(), metadata={}, receipt={"requested": 0, "network_requested": False}))
        candidate_rows = []
        for code in observation_codes:
            previous = history[(history.trade_date == CLOSED) & (history.code == code)].iloc[0].to_dict()
            amount, volume, low, high = (previous[k] for k in ("amount", "volume", "low", "high"))
            valid_vwap = bool(previous["source"] == "tdx" and np.isfinite([amount, volume, low, high]).all()
                              and min(amount, volume, low) > 0 and high >= low and low-.01-1e-10 <= amount/volume <= high+.01+1e-10)
            day_factor = factor_ledger[(factor_ledger.trade_date == CLOSED) & (factor_ledger.code == code)].iloc[0].to_dict()
            closed_economic = {key: economic_closed[key][code] for key in ("open", "high", "low", "close")}
            candidate_rows.append(dict(code=code, name=names[code], current_identity_eligible=code in candidate_codes,
                identity_review_required=code in identity_review, current_identity_exclusions=identity.at[code, "current_identity_exclusions"],
                historical_shape_factors={name: economic_result.factors[name].at[TARGET, code] for name in GEOMETRY_FACTORS},
                anchor_gain_pct=economic_result.factors["大涨日涨幅(%)"].at[TARGET, code],
                yin_volume_ratio=economic_result.factors["倍量阴量比"].at[TARGET, code],
                recent_gain_pct=economic_result.factors["近期累计涨幅(%)"].at[TARGET, code],
                previous_closed_raw=previous, previous_closed_factor=day_factor, previous_vwap_known=valid_vwap,
                previous_vwap_raw=amount/volume if valid_vwap else None,
                previous_vwap_economic_exact=amount/volume*day_factor["factor"] if valid_vwap else None,
                previous_vwap_economic=float(price_precision(pd.Series([amount/volume*day_factor["factor"]])).iat[0]) if valid_vwap else None,
                industry=metadata.get(code, {"status": "unknown", "groups": [], "historical_membership": False}),
                scoring_inputs=dict(economic_low60=float(closed_economic["low"].iloc[-60:].min()),
                    economic_high60=float(closed_economic["high"].iloc[-60:].max()),
                    economic_MA={str(n): float(closed_economic["close"].iloc[-n:].mean()) for n in (5, 10, 20)},
                    score=None, score_status="unknown_until_target_open_and_factor_and_identity_validated"),
                target_open_raw=None, target_factor=None, target_factor_observation_date=None, target_source_prev_close=None,
                target_identity_verified=False, B_condition=None, selected_rank=None, return_value=None))
        production_codes = sorted(item["code"] for item in reference_payload["candidates"])
        comparisons = []
        lookup = history.set_index(["trade_date", "code"])
        for item in reference_payload["candidates"]:
            code = item["code"]
            mismatches, compared = [], 0
            for bar in item["history"]:
                key = (bar["date"], code)
                if key not in lookup.index:
                    continue
                observed_bar = lookup.loc[key]
                for field in PRICE_FIELDS:
                    a, b = observed_bar[field], bar.get(field)
                    same = (pd.isna(a) and b is None) or (b is not None and np.isfinite(a) and np.isclose(a, b, rtol=1e-12, atol=1e-8))
                    compared += 1
                    if not same:
                        mismatches.append({"date": bar["date"], "field": field, "snapshot_value": a, "production_pool_value": b})
            comparisons.append(dict(code=code, compared_field_cells=compared, mismatch_count=len(mismatches), mismatches=mismatches))
        comparison = dict(raw_snapshot_candidate_codes=raw_codes, economic_snapshot_candidate_codes=candidate_codes,
            raw_only=sorted(set(raw_codes)-set(candidate_codes)), economic_only=sorted(set(candidate_codes)-set(raw_codes)),
            production_raw_candidate_codes=production_codes, snapshot_raw_vs_production_equal=set(raw_codes)==set(production_codes),
            production_public_payload_sha256=raw_reference["source_payload_sha256"],
            universe_size_snapshot=len(resolved.codes), universe_size_production=reference_payload["universe_size"],
            production_full_universe_membership_not_stored=True, overlapping_raw_history_comparisons=comparisons,
            all_field_cells_match=all(row["compared_field_cells"] > 0 and row["mismatch_count"] == 0 for row in comparisons))
        csv_new(OUTPUT / "market-calendar.csv", pd.DataFrame({"trade_date": days}))
        csv_new(OUTPUT / "universe-status.csv", identity.reset_index(drop=True))
        persisted_history = history[history.code.isin(observation_codes)]
        csv_new(OUTPUT / "raw-history.csv", persisted_history)
        csv_new(OUTPUT / "factor-observations.csv", sparse[sparse.code.isin(observation_codes)])
        csv_new(OUTPUT / "daily-factor-alignment.csv", factor_ledger[factor_ledger.code.isin(observation_codes)])
        write_new(OUTPUT / "shape-candidates.json", dict(as_of=CLOSED, planned_target=TARGET, captured_at=captured_at,
            current_identity_candidate_codes=candidate_codes, identity_review_codes=identity_review,
            full_shape_observation_codes=observation_codes, candidates=candidate_rows,
            historical_scope_before_low_open_vwap_or_top2=True, target_inputs_known=False))
        write_new(OUTPUT / "raw-pool-comparison.json", comparison)
        write_new(OUTPUT / "self-check.json", checks)
        assert protected() == inputs_before
        manifest = dict(prepared_at=now(), as_of_market_date=CLOSED, planned_target_trade_date=TARGET,
            status="closed_inputs_prepared_target_validation_pending", authorizes_realtime_execution=False,
            strategy=engine.slug, strategy_revision=engine.strategy_revision, parameters=params, universe=resolved.spec,
            current_universe_funnel=resolved.funnel.to_dict(), scope_identity="current_snapshot_not_historical_or_target_day_identity",
            snapshot_path=DB.relative_to(ROOT).as_posix(), protected_inputs=inputs_before,
            target_session_evidence=SESSION.relative_to(ROOT).as_posix(), complete_market_days=days,
            current_identity_candidate_codes=candidate_codes, candidate_codes=observation_codes,
            candidate_codes_semantics="complete_historical_price_shape_observation_union_including_target_identity_review; not_B_or_Top2",
            full_shape_observation_codes=observation_codes, identity_review_codes=identity_review,
            observation_count=len(observation_codes), current_identity_candidate_count=len(candidate_codes),
            identity_review_count=len(identity_review), full_catalog_count=len(identity), main_board_history_count=len(codes),
            evaluated_history_grid_rows=len(history), evaluated_actual_quote_rows=int(history.quote_row_present.sum()),
            persisted_raw_history_rows=len(persisted_history),
            noncandidate_history_locator=dict(database_path=DB.relative_to(ROOT).as_posix(), database_sha256=inputs_before["snapshot_sha256"],
                all_codes_source="universe-status.csv where board_bucket=main", dates_source="market-calendar.csv",
                price_query="quotes_daily WHERE code IN (complete current main-board codes) AND trade_date BETWEEN first calendar date AND as_of_market_date",
                factor_query="adjust_factors WHERE code IN (same codes) AND trade_date<=as_of_market_date; preserve last observation before window plus all observations within window; forward align only",
                missing_quote_cells="Explicit empty cells on complete market calendar; never fill prices or use future factors"),
            known_factor_missing_quoted_cells=int(missing_factor.to_numpy().sum()),
            prior_vwap_known_count=sum(item["previous_vwap_known"] for item in candidate_rows),
            industry_missing_codes=sorted(set(observation_codes)-set(metadata)), new_industry_request_count=len(missing_industry),
            target_unknown_fields=["open", "high", "low", "close", "volume", "amount", "factor", "source_prev_close", "identity", "score", "B_condition", "Top2"],
            scoring_definition="60*(1-clip((O_econ-low60)/(high60-low60),0,1))+40*clip(1-min(abs(O_econ/MA5_10_20-1))/.03,0,1); round4; target O/factor unknown so not evaluated",
            source_timing="Source fetched_at strings preserved verbatim; availability asserted only at this bundle capture, not at historical close. Target-day freshness and reference bridge remain unchecked.",
            research_shape_geometry="direct past factors only; normalized economic OHLC at10significant digits; unchanged historical predicate; no low-open/VWAP/ranking filter",
            returns_computed=False, B_rankings_computed=False, production_or_calendar_cache_modified=False,
            artifacts_sha256={p.name: sha256(p) for p in sorted(OUTPUT.iterdir()) if p.is_file()})
        write_new(OUTPUT / "manifest.json", manifest)
        print(json.dumps(clean({k: manifest[k] for k in ("planned_target_trade_date", "observation_count", "current_identity_candidate_count", "identity_review_count", "industry_missing_codes", "new_industry_request_count", "known_factor_missing_quoted_cells")}), ensure_ascii=False))
    finally:
        store.close()


def verify():
    manifest = read(OUTPUT / "manifest.json")
    assert manifest["protected_inputs"] == protected()
    assert all(sha256(OUTPUT / name) == digest for name, digest in manifest["artifacts_sha256"].items())
    candidates = read(OUTPUT / "shape-candidates.json")
    assert candidates["full_shape_observation_codes"] == manifest["full_shape_observation_codes"]
    assert set(manifest["current_identity_candidate_codes"]) | set(manifest["identity_review_codes"]) == set(manifest["full_shape_observation_codes"])
    assert not set(manifest["current_identity_candidate_codes"]) & set(manifest["identity_review_codes"])
    assert all(item["target_open_raw"] is None and item["target_factor"] is None and item["B_condition"] is None
               and item["selected_rank"] is None and item["return_value"] is None for item in candidates["candidates"])
    return manifest


def self_check():
    engine = DoubleYinLowOpenV1()
    days = pd.bdate_range(end=CLOSED, periods=65).strftime("%Y-%m-%d")
    panels = {field: pd.DataFrame(value, index=days, columns=["600000"])
              for field, value in dict(open=10., high=10.2, low=9.8, close=10., volume=100.).items()}
    for field, value in dict(open=10., high=11., low=9.9, close=10.9, volume=100.).items():
        panels[field].iloc[-2, 0] = value
    for field, value in dict(open=11., high=11.1, low=10.6, close=10.7, volume=200.).items():
        panels[field].iloc[-1, 0] = value
    computed = engine.compute(append_unknown_target(panels, {"600000": "合成示例"}))
    assert geometry(computed)["600000"] and computed.factors["历史形态候选"].at[TARGET, "600000"]
    assert not computed.signals.loc[TARGET].any() and computed.factors["score"].loc[TARGET].isna().all()
    flagged = engine.compute(append_unknown_target(panels, {"600000": "*ST合成"}))
    assert geometry(flagged)["600000"] and not flagged.factors["历史形态候选"].at[TARGET, "600000"]
    sample = pd.DataFrame([dict(code="600000", trade_date="2026-09-29", hfq_factor=2., source="synthetic", fetched_at="before_target")])
    aligned = align_factors(sample, ["2026-09-28", "2026-09-29", "2026-09-30"], ["600000"])
    assert pd.isna(aligned["factor"].iat[0, 0]) and aligned["factor"].iat[-1, 0] == 2.
    assert TARGET not in aligned["factor"].index
    damaged = {key: value.copy() for key, value in panels.items()}
    damaged["volume"].iloc[-1, 0] = np.nan
    bad = engine.compute(append_unknown_target(damaged, {"600000": "合成示例"}))
    assert not geometry(bad)["600000"]
    return dict(passed=True, synthetic_only=True, cases=["historical_shape_with_unknown_target", "no_target_score_or_selection",
        "ST_price_geometry_preserved_for_identity_review", "no_future_factor_backfill", "no_target_factor_forward_claim", "missing_yin_volume_not_fabricated"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("self-check", "prepare", "verify"))
    phase = parser.parse_args().phase
    if phase == "self-check":
        print(self_check())
    elif phase == "prepare":
        prepare()
    else:
        verify()
        print("Immutable closed-input bundle and protected sources verified")
