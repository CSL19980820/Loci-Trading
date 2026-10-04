"""Offline daily-opening proxy inputs for double-yin scoring research.

This module does not make the live strategy backtestable: the original engine's
``requires_realtime_inputs`` flag remains True. Daily OHLC openings do not prove
09:25 quote availability, exact auction execution, or historical industry labels.
Callers own the frozen scoring variants, execution assumptions, and reporting.
All supplied OHLC panels must use the original unadjusted-price convention.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategy.application.double_yin_low_open import DoubleYinLowOpenV1  # noqa: E402

LOAD_START = "2023-01-01"
RESEARCH_CUTOFF = "2026-09-30"


def _groups(codes: pd.Index, supplied: Mapping[str, Any]) -> dict[Any, tuple[str, ...]]:
    """Use exactly the production contract: missing/invalid groups stay empty."""
    result = {}
    for code in codes:
        value = supplied.get(str(code))
        valid = isinstance(value, (list, tuple)) and bool(value) and all(
            isinstance(group, str) and bool(group.strip()) for group in value
        )
        result[code] = tuple(sorted({group.strip() for group in value})) if valid else ()
    return result


def rank_with_groups(
    candidates: pd.DataFrame,
    score: pd.DataFrame,
    sector_groups: Mapping[str, Any],
    *,
    top_n: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return selected, known-group eligible, and pre-group candidate ranks.

Match live greedy selection, including the union of every selected stock's
groups, deterministic code ties, and skipping missing industries. The second
frame is only a diagnostic eligibility mask; it does not waive group conflicts.
Group conflicts can make the final quota depend on ordering.
"""
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise ValueError("top_n must be a positive integer")
    if not score.index.is_unique or not score.columns.is_unique:
        raise ValueError("Scoring proxy requires unique dates and codes")
    groups = _groups(score.columns, sector_groups)
    candidate_mask = candidates.reindex_like(score).fillna(False).astype(bool)
    ranked_score = score.where(candidate_mask & np.isfinite(score)).clip(0, 100).round(4)
    rawrank = ranked_score.reindex(columns=sorted(score.columns, key=str)).rank(
        axis=1, ascending=False, method="first",
    ).reindex(columns=score.columns)
    known = pd.Series({code: bool(groups[code]) for code in score.columns})
    eligible = (ranked_score.notna() & known).fillna(False).astype(bool)
    selected = pd.DataFrame(False, index=score.index, columns=score.columns)
    for day in score.index:
        used: set[str] = set()
        picked = 0
        codes = ranked_score.loc[day].dropna().index.tolist()
        codes.sort(key=lambda code: (-ranked_score.at[day, code], str(code)))
        for code in codes:
            if not groups[code] or used.intersection(groups[code]):
                continue
            if picked >= top_n:
                break
            selected.at[day, code] = True
            used.update(groups[code])
            picked += 1
    return selected, eligible, rawrank


def build_proxy_inputs(
    panels: dict[str, Any],
    *,
    sector_groups: Mapping[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    group_source: str = "explicit_static_groups_not_verified_historical",
) -> dict[str, Any]:
    """Compute original candidates and scores without mutating source panels.

``sector_groups`` must identify genuine observed labels or a separately declared
proxy. Empty/missing evidence never becomes one synthetic group per stock.
Use the returned ranker for every variant; a plain Top2 changes the strategy.
The returned original engine deliberately retains its ordinary-backtest ban.
"""
    engine = DoubleYinLowOpenV1()
    resolved = engine._params(params)
    supplied = sector_groups if sector_groups is not None else panels.get("__sector_groups__", {})
    if not isinstance(supplied, Mapping):
        raise ValueError("sector_groups must be a mapping")
    groups = _groups(panels["open"].columns, supplied)
    proxy_panels = {**panels, "__sector_groups__": groups}
    computed = engine.compute(proxy_panels, resolved)
    candidates = computed.factors["条件候选"]
    oldscore = computed.factors["score"]
    baseline, eligible, rawrank = rank_with_groups(
        candidates, oldscore, groups, top_n=resolved["top_n"],
    )
    pd.testing.assert_frame_equal(baseline, computed.signals)
    pd.testing.assert_frame_equal(rawrank, computed.factors["候选名次"])
    if not engine.requires_realtime_inputs:
        raise AssertionError("The production realtime-input guard must remain enabled")
    candidate_codes = candidates.columns[candidates.any(axis=0)]
    missing_codes = sorted(str(code) for code in candidate_codes if not groups[code])
    missing_group = pd.Series({code: not bool(groups[code]) for code in candidates.columns})
    return {
        "engine": engine,
        "resolved_params": resolved,
        "result": computed,
        "panels": proxy_panels,
        "candidates": candidates,
        "historical_candidates": computed.factors["历史形态候选"],
        "oldscore": oldscore,
        "rawrank": rawrank,
        "baseline": baseline,
        "eligible": eligible,
        "groups": groups,
        "evidence": {
            "mode": "offline_daily_opening_proxy",
            "canonical_realtime_required": True,
            "historical_0925_quote_coverage_verified": False,
            "historical_industry_membership_verified": False,
            "group_source": group_source,
            "candidate_codes": len(candidate_codes),
            "candidate_codes_missing_groups": missing_codes,
            "candidate_events": int(candidates.to_numpy().sum()),
            "candidate_events_missing_groups": int((candidates & missing_group).to_numpy().sum()),
            "candidate_events_missing_score": int((candidates & oldscore.isna()).to_numpy().sum()),
            "industry_rule": "greedy TopN with all supplied group intersections excluded",
            "price_convention": "caller_supplied_unadjusted_OHLC",
        },
    }


def catalog_proxy_groups(
    metadata: Mapping[str, Any],
) -> tuple[dict[str, tuple[str, ...]], dict[str, Any]]:
    """Explicit coarse-catalog alternative, NEVER an EM2016-equivalent fallback.

The stored catalog uses broad names such as manufacturing. It cannot recover
the production EM2016 first level or the consumer-family overlap. This optional
proxy retains equality-based sector exclusion but changes sector semantics;
results must be labelled accordingly. Missing labels still exclude a stock.
"""
    groups = {}
    for code, record in metadata.items():
        label = str(record.get("industry") or "").strip() if isinstance(record, Mapping) else ""
        groups[str(code)] = (f"catalog_coarse_proxy:{label}",) if label else ()
    return groups, {
        "source": "current_instruments_industry_coarse_proxy",
        "historical_membership": False,
        "em2016_equivalent": False,
        "consumer_family_exclusion_reproduced": False,
        "limitation": "Coarse catalog equality exclusion changes production sector semantics",
        "codes": len(groups),
        "codes_with_label": sum(bool(value) for value in groups.values()),
    }


def _load_raw_panels(store: Any, end: str) -> tuple[Any, dict[str, Any]]:
    from src.market import resolve_universe

    engine = DoubleYinLowOpenV1()
    resolved = resolve_universe(store, engine.default_universe, as_of=end)
    if not resolved.codes:
        raise ValueError("The original double-yin main-board universe is empty")
    panels = store.load_panel(
        fields=engine.required_fields(), codes=resolved.codes,
        start=LOAD_START, end=end, adjust="none", min_bars=engine.min_bars(),
    )
    if panels["close"].empty:
        raise ValueError("No raw daily bars in the proxy research window")
    calendar = store.trading_days(start=str(panels["close"].index[0]), end=end)
    if list(panels["close"].index) != calendar:
        raise ValueError("Raw proxy panels omit market sessions; holding periods would change")
    panels["__instrument_names__"] = {
        code: str(record.get("name") or "") for code, record in resolved.meta.items()
    }
    return resolved, panels


def _economic_factors(raw: pd.DataFrame, adjusted: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    quoted = np.isfinite(raw) & raw.gt(0)
    adjusted_ok = np.isfinite(adjusted) & adjusted.gt(0)
    if bool((quoted & ~adjusted_ok).to_numpy().any()):
        raise ValueError("Quoted raw close has no valid hfq close; economic factors cannot be guessed")
    factors = (adjusted / raw).where(quoted & adjusted_ok)
    if bool((quoted & ~(np.isfinite(factors) & factors.gt(0))).to_numpy().any()):
        raise ValueError("Quoted daily price has an invalid economic factor ratio")
    # Only no-price calendar gaps inherit the last observed factor. Leading
    # no-price cells use 1 solely because the execution engine validates the
    # whole matrix; no valid quote or actual fill can consume that placeholder.
    carried = factors.ffill()
    leading_empty = carried.isna() & ~quoted
    completed = factors.where(quoted, carried).where(~leading_empty, 1.0)
    if not bool((np.isfinite(completed) & completed.gt(0)).to_numpy().all()):
        raise ValueError("Unresolved economic factor outside quoted daily prices")
    return completed, {
        "quoted_factor_observations": int(quoted.to_numpy().sum()),
        "no_price_forward_carried_cells": int((~quoted & carried.notna()).to_numpy().sum()),
        "leading_no_price_neutral_placeholders": int(leading_empty.to_numpy().sum()),
    }


def prepare_proxy_context(
    store: Any, start: str, end: str, config: Any, groups_path: str | Path,
) -> tuple[dict[str, Any], Any, pd.DataFrame, pd.DataFrame, pd.DataFrame, Any]:
    """Manually prepare the explicitly labelled daily-opening proxy context.

    Never call prepare_backtest_context or disable the live realtime guard.
    Sector evidence is required; coarse catalog fallback is deliberately absent.
    Returns ctx, computed, candidates, oldscore, original-rank-score, ranker.
    """
    if not config.strict_limit_prices or not config.economic_returns:
        raise ValueError("Proxy execution requires strict raw limits and economic returns")
    if start > end or start < LOAD_START:
        raise ValueError("Proxy research dates must be ordered and start no earlier than 2023-01-01")
    path = Path(groups_path).resolve(strict=True)
    content = path.read_bytes()
    payload = json.loads(content)
    groups = payload.get("sector_groups") if isinstance(payload, dict) else None
    if not isinstance(groups, dict) or not groups:
        raise ValueError("Industry evidence JSON must contain a non-empty sector_groups mapping")
    resolved, panels = _load_raw_panels(store, end)
    proxy = build_proxy_inputs(
        panels, sector_groups=groups,
        group_source=str(payload.get("source") or "supplied_current_EM2016_not_historical"),
    )
    if not bool(proxy["eligible"].loc[start:end].to_numpy().any()):
        raise ValueError("No candidate in this research segment has usable industry groups; "
                         "complete candidate-level sector evidence before evaluating returns")
    adjusted = store.load_panel(
        fields=("close",), codes=resolved.codes, start=LOAD_START, end=end,
        adjust="hfq", min_bars=proxy["engine"].min_bars(),
    )["close"].reindex_like(panels["close"])
    factors, factor_evidence = _economic_factors(panels["close"], adjusted)
    execution = {**proxy["panels"], "__adjust_factor": factors}
    snapshot = store.data_snapshot(
        codes=resolved.codes, start=LOAD_START, end=end,
        include_source_details=False, source_evidence_mode="compact",
    )
    industry_keys = ("source", "fetched_at", "classification", "coverage", "requested",
                     "returned", "rejected", "rejects", "candidate_code_count", "candidate_event_count",
                     "historical_membership", "limitation", "industry_snapshot")
    snapshot = {**snapshot, "research_proxy": {
        **proxy["evidence"],
        "sector_groups_path": str(path),
        "sector_groups_sha256": hashlib.sha256(content).hexdigest(),
        "industry_evidence": {key: payload[key] for key in industry_keys if key in payload},
        "economic_factors": factor_evidence,
        "entry_assumption": "stored daily opening proxy, not verified 09:25 obtainable execution",
        "exit_assumption": "caller-frozen research exit; original live selector has no exit rule",
    }}
    ctx = {
        "engine": proxy["engine"], "config": config,
        "resolved_params": proxy["resolved_params"], "resolved": resolved,
        "fields": proxy["engine"].required_fields(), "effective_adjust": "none",
        "history_mode": "fixed_research_origin", "load_start": LOAD_START, "load_end": end,
        "start": start, "end": end, "panels": proxy["panels"],
        "execution_panels": execution, "execution_adjust": "none",
        "entry_price_panel": None, "signals": proxy["baseline"], "benchmark_close": None,
        "data_snapshot": snapshot,
    }
    candidates, old = proxy["candidates"], proxy["oldscore"]

    def ranker(score: pd.DataFrame) -> pd.DataFrame:
        return rank_with_groups(candidates, score, proxy["groups"],
                                top_n=proxy["resolved_params"]["top_n"])[0]

    return ctx, proxy["result"], candidates, old, old, ranker


def export_candidate_groups(db_path: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    """Count first; if output requested, fetch current industries for candidate codes only.

    Daily prices are read-only and no returns/exits are computed. A count-only
    call never contacts the industry provider. Returned classifications are
    current observations, deliberately not historical point-in-time evidence.
    """
    from tools.research_chinext_payoff_exits import CutoffMarketStore

    if output_path is not None and Path(output_path).exists():
        raise FileExistsError("Industry evidence output already exists; choose a new receipt path")
    store = CutoffMarketStore(Path(db_path), RESEARCH_CUTOFF)
    try:
        days = store.trading_days(start=LOAD_START, end=RESEARCH_CUTOFF)
        if not days:
            raise ValueError("No market sessions in the fixed research window")
        end = str(days[-1])
        resolved, panels = _load_raw_panels(store, end)
        proxy = build_proxy_inputs(panels, sector_groups={}, group_source="not_yet_fetched")
        candidates = proxy["candidates"]
        # Include every valid historical condition candidate, before ranking or
        # industry availability. Do not use price outcomes to choose this set.
        codes = sorted(str(code) for code in candidates.columns[candidates.any(axis=0)])
        evidence = {
            "mode": "current_industry_for_historical_daily_opening_proxy",
            "load_start": LOAD_START, "load_end": end, "universe_codes": len(resolved.codes),
            "candidate_code_count": len(codes), "candidate_event_count": int(candidates.to_numpy().sum()),
            "candidate_codes": codes,
            "historical_membership": False,
            "limitation": "Current EM2016 classifications are not historical industry memberships",
        }
    finally:
        store.close()
    print(json.dumps({"candidate_code_count": len(codes),
                      "candidate_event_count": evidence["candidate_event_count"],
                      "network_requested": output_path is not None}, ensure_ascii=False), flush=True)
    if output_path is None:
        return evidence
    from src.market.application.double_yin_inputs import fetch_double_yin_industries

    metadata, receipt = fetch_double_yin_industries(codes) if codes else ({}, {
        "source": "eastmoney_orginfo", "requested": 0, "returned": 0, "rejected": 0,
        "coverage": 1.0, "rejects": {},
    })
    payload = {**evidence, "source": "eastmoney_orginfo", "classification": "EM2016",
               "fetched_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
               "sector_groups": {code: list(item.get("groups") or ()) for code, item in metadata.items()},
               "industry_snapshot": receipt,
               "coverage": receipt.get("coverage"), "requested": receipt.get("requested"),
               "returned": receipt.get("returned"), "rejected": receipt.get("rejected"),
               "rejects": receipt.get("rejects", {})}
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Do not silently replace a previously frozen classification receipt.
    with output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return payload


def self_check() -> dict[str, Any]:
    """Small synthetic causality/ranking checks; no DB reads or network access."""
    dates = pd.bdate_range("2025-01-01", periods=133).strftime("%Y-%m-%d")
    codes = ["600004", "600003", "600002", "600001"]
    panels: dict[str, Any] = {
        field: pd.DataFrame(value, index=dates, columns=codes)
        for field, value in {"open": 10.0, "close": 10.0, "high": 10.2,
                             "low": 9.8, "volume": 100.0}.items()
    }
    for offset, values in {
        -3: {"open": 10.0, "close": 11.0, "high": 11.2, "low": 9.9, "volume": 100.0},
        -2: {"open": 11.2, "close": 10.6, "high": 11.5, "low": 10.5, "volume": 200.0},
        -1: {"open": 10.5, "close": 10.6, "high": 10.8, "low": 10.3, "volume": 120.0},
    }.items():
        for field, value in values.items():
            panels[field].iloc[offset] = value
    panels["__instrument_names__"] = {code: f"股票{code}" for code in codes}
    groups = {"600001": ("industry:A", "family:consumer"),
              "600002": ("industry:B", "family:consumer"),
              "600003": ("industry:C",), "600004": ()}
    proxy = build_proxy_inputs(panels, sector_groups=groups, group_source="synthetic_self_check")
    last = dates[-1]
    assert set(proxy["baseline"].loc[last].index[proxy["baseline"].loc[last]]) == {"600001", "600003"}
    assert int(proxy["candidates"].loc[last].sum()) == 4
    assert not proxy["eligible"].loc[last, "600004"]
    changed = {key: value.copy() if isinstance(value, pd.DataFrame) else value for key, value in panels.items()}
    for field in ("close", "high", "low", "volume"):
        changed[field].loc[last] = np.nan
    changed_proxy = build_proxy_inputs(changed, sector_groups=groups)
    for key in ("candidates", "oldscore", "rawrank", "baseline"):
        pd.testing.assert_frame_equal(proxy[key], changed_proxy[key])
    truncated = {key: value.iloc[:-1] if isinstance(value, pd.DataFrame) else value for key, value in panels.items()}
    prefix = build_proxy_inputs(truncated, sector_groups=groups)
    for key in ("candidates", "oldscore", "rawrank", "baseline"):
        pd.testing.assert_frame_equal(proxy[key].iloc[:-1], prefix[key])
    altered_score = proxy["oldscore"].copy()
    altered_score.loc[last, "600002"] = 100
    reranked, _, _ = rank_with_groups(proxy["candidates"], altered_score, groups)
    assert set(reranked.loc[last].index[reranked.loc[last]]) == {"600002", "600003"}
    return {"status": "passed", "checks": ["canonical_baseline_rank_parity", "code_ties",
            "multi_group_consumer_exclusion", "missing_group_rejection", "today_HLCV_independence",
            "prefix_causality", "variant_group_preservation", "live_guard_unchanged"]}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--self-check"]:
        print(json.dumps(self_check(), ensure_ascii=False, indent=2))
    elif len(args) == 2 and args[0] == "--candidate-groups-count":
        print(json.dumps(export_candidate_groups(args[1]), ensure_ascii=False, indent=2))
    elif len(args) == 3 and args[0] == "--export-candidate-groups":
        receipt = export_candidate_groups(args[1], args[2])
        print(json.dumps({key: receipt[key] for key in (
            "candidate_code_count", "candidate_event_count", "coverage", "returned", "rejected",
        )}, ensure_ascii=False, indent=2))
    else:
        raise SystemExit("Usage: --self-check | --candidate-groups-count DB_PATH | "
                         "--export-candidate-groups DB_PATH OUTPUT_JSON")
