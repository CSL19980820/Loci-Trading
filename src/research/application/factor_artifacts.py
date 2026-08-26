"""Derive PTH252-only artifacts from the shared frozen research input."""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, BacktestResult
from src.backtest import build_universe_control, execute_backtest_context
from src.research.application.backtest_support import backtest_payload
from src.research.application.factor_analysis import (
    CrossSectionAnalysis,
    QuantileSignals,
    analyze_cross_section,
    build_quantile_signals,
    compute_pth252_scores,
)
from src.research.application.factor_experiment import (
    PTH252_FACTOR_ID,
    PTH252_GROUP_COUNT,
    PTH252_REBALANCE_EVERY,
    PTH252_SELECTION_CAPACITY,
    PTH252_TOP_QUANTILE,
    Pth252FactorEngine,
    Pth252FactorExperimentError,
    _cap_quantile,
    _day_key,
    _json_value,
    _restricted_signals,
    pth252_engine_from_frozen_params,
)
from src.research.domain.run_card import ResearchRunCard
from src.research.infrastructure import ResearchRunCardStore


def write_pth252_factor_artifacts(
    store: Any,
    cards: ResearchRunCardStore,
    card: ResearchRunCard,
) -> dict[str, Any]:
    """Use frozen panels only, so factor diagnostics cannot see newer market data."""
    payload = _read_frozen_payload(cards, card)
    context = _execution_context(payload)
    engine = pth252_engine_from_frozen_params(context["resolved_params"])
    reconstructed = _restricted_signals(
        engine.compute(context["panels"], context["resolved_params"]).signals,
        start=str(context["start"]),
        end=str(context["end"]),
        membership_mask=context.get("universe_control_mask"),
    )
    if not reconstructed.equals(context["signals"]):
        raise Pth252FactorExperimentError("冻结 PTH252 signals 无法由固定规则重建")

    scores = compute_pth252_scores(context["panels"]["close"], context["panels"]["high"])
    quantiles = build_quantile_signals(
        scores,
        group_count=PTH252_GROUP_COUNT,
        rebalance_dates=engine.rebalance_dates(scores.index),
    )
    control = build_universe_control(store, context, use_fast=False)
    active = context["signals"].any(axis=1)
    labels = _execution_labels(control, index=scores.index, columns=scores.columns)
    cross_section = _cross_section(scores, labels, active)

    bottom = _restricted_signals(
        _cap_quantile(
            quantiles.bottom, scores, capacity=PTH252_SELECTION_CAPACITY, highest=False,
        ),
        start=str(context["start"]), end=str(context["end"]),
        membership_mask=context.get("universe_control_mask"),
    )
    close_scores = compute_pth252_scores(context["panels"]["close"], reference="close")
    close_quantiles = build_quantile_signals(
        close_scores,
        group_count=PTH252_GROUP_COUNT,
        rebalance_dates=engine.rebalance_dates(close_scores.index),
    )
    close_top = _restricted_signals(
        _cap_quantile(
            close_quantiles.top, close_scores,
            capacity=PTH252_SELECTION_CAPACITY, highest=True,
        ),
        start=str(context["start"]), end=str(context["end"]),
        membership_mask=context.get("universe_control_mask"),
    )
    bottom_result = _execute_variant(store, context, bottom, engine)
    close_result = _execute_variant(
        store,
        context,
        close_top,
        replace_engine_reference(engine, "close", "research-pth252-close-reference"),
    )
    diagnostics = _signal_diagnostics(
        quantiles,
        primary=context["signals"], bottom=bottom, close_top=close_top,
        start=str(context["start"]), end=str(context["end"]),
    )
    analysis_payload = _json_value({
        "contract_version": "pth252-factor-analysis-v1",
        "factor": {
            "id": PTH252_FACTOR_ID,
            "formula": "close / rolling_max(high, 252)",
            "entry_timing": "next_open",
            "rebalance_every": PTH252_REBALANCE_EVERY,
            "hold_days": 20,
            "top_quantile": PTH252_TOP_QUANTILE,
            "selection_capacity": PTH252_SELECTION_CAPACITY,
            "no_weak_refill": True,
        },
        "signal_diagnostics": diagnostics,
        "execution_labeling": {
            "source": "shared_backtest_execution_engine",
            "timing": "T+1 open with engine limit/suspension/cost rules",
            "active_rebalance_days": int(active.sum()),
            "labelled_events": int(labels.notna().sum().sum()),
            "control_metrics": control.metrics,
        },
        "cross_section": cross_section.to_dict(),
    })
    sensitivity_payload = _json_value({
        "contract_version": "pth252-factor-sensitivity-v1",
        "primary_high_top_decile": card.metrics,
        "bottom_decile": backtest_payload(bottom_result),
        "close_reference_top_decile": backtest_payload(close_result),
    })
    cards.write_artifact(card.run_id, "factor-analysis.json", analysis_payload, artifact_type="factor_analysis")
    cards.write_artifact(card.run_id, "factor-sensitivity.json", sensitivity_payload, artifact_type="factor_sensitivity")
    cards.write_artifact(
        card.run_id,
        "factor-report.md",
        _factor_report(card, analysis_payload, sensitivity_payload),
        artifact_type="factor_report",
    )
    return analysis_payload


def replace_engine_reference(engine: Pth252FactorEngine, reference: str, slug: str) -> Pth252FactorEngine:
    """Keep the sensitivity run self-describing without registering a strategy."""
    return Pth252FactorEngine(
        signal_start=engine.signal_start,
        reference=reference,
        top_quantile=engine.top_quantile,
        rebalance_every=engine.rebalance_every,
        selection_capacity=engine.selection_capacity,
        slug=slug,
    )


def _execution_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    panels = _decode_panels(payload.get("panels"))
    execution = _decode_panels(payload.get("execution_panels")) or panels
    if not {"open", "high", "low", "close"} <= set(panels):
        raise Pth252FactorExperimentError("冻结输入缺少 PTH252 所需 OHLC 面板")
    signals = _decode_panel(payload.get("signals"), boolean=True)
    if not signals.index.equals(panels["close"].index) or not signals.columns.equals(panels["close"].columns):
        raise Pth252FactorExperimentError("冻结 signals 与 OHLC 面板未对齐")
    resolved_raw = payload.get("resolved")
    if not isinstance(resolved_raw, Mapping):
        raise Pth252FactorExperimentError("冻结输入缺少股票池")
    funnel = dict(resolved_raw.get("funnel") or {})
    resolved = SimpleNamespace(
        codes=list(resolved_raw.get("codes") or []),
        spec=dict(resolved_raw.get("spec") or {}),
        meta=dict(resolved_raw.get("meta") or {}),
        funnel=SimpleNamespace(to_dict=lambda: dict(funnel)),
    )
    return {
        "engine": pth252_engine_from_frozen_params(dict(payload.get("resolved_params") or {})),
        "config": BacktestConfig(**dict(payload.get("config") or {})),
        "resolved_params": dict(payload.get("resolved_params") or {}),
        "resolved": resolved,
        "fields": tuple(panels),
        "effective_adjust": "qfq",
        "execution_adjust": "qfq",
        "load_start": payload.get("load_start"),
        "load_end": payload.get("load_end"),
        "start": payload.get("start"),
        "end": payload.get("end"),
        "panels": panels,
        "execution_panels": execution,
        "signals": signals,
        "entry_price_panel": _decode_optional_panel(payload.get("entry_price_panel")),
        "benchmark_close": _decode_series(payload.get("benchmark_close")),
        "universe_control_mask": _decode_optional_panel(payload.get("universe_control_mask"), boolean=True),
        "data_snapshot": dict(payload.get("data_snapshot") or {}),
    }


def _read_frozen_payload(cards: ResearchRunCardStore, card: ResearchRunCard) -> dict[str, Any]:
    entry = next((item for item in card.artifact_manifest if item.path == "frozen_input.json"), None)
    if entry is None:
        raise Pth252FactorExperimentError("研究 run 缺少 frozen_input.json")
    raw = (Path(cards.root) / card.run_id / entry.path).read_bytes()
    if sha256(raw).hexdigest() != entry.sha256:
        raise Pth252FactorExperimentError("frozen_input.json 的 manifest hash 不一致")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Pth252FactorExperimentError("frozen_input.json 不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise Pth252FactorExperimentError("frozen_input.json 根节点必须是对象")
    return payload


def _decode_panels(raw: object) -> dict[str, pd.DataFrame]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(name): _decode_panel(value) for name, value in raw.items() if isinstance(value, Mapping)}


def _decode_panel(raw: object, *, boolean: bool = False) -> pd.DataFrame:
    if not isinstance(raw, Mapping):
        raise Pth252FactorExperimentError("冻结面板格式无效")
    frame = pd.DataFrame(raw.get("values") or [], index=raw.get("index") or [], columns=raw.get("columns") or [])
    return frame.fillna(False).astype(bool) if boolean else frame.apply(pd.to_numeric, errors="coerce")


def _decode_optional_panel(raw: object, *, boolean: bool = False) -> pd.DataFrame | None:
    return _decode_panel(raw, boolean=boolean) if isinstance(raw, Mapping) else None


def _decode_series(raw: object) -> pd.Series | None:
    if not isinstance(raw, Mapping):
        return None
    return pd.Series(raw.get("values") or [], index=raw.get("index") or [], dtype="float64")


def _execution_labels(result: BacktestResult, *, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    labels = pd.DataFrame(np.nan, index=index, columns=columns, dtype=float)
    for trade in result.trades:
        if trade.exit_reason == "data_end":
            continue
        day, code = str(trade.signal_date), str(trade.code)
        value = float(trade.net_return_pct) / 100.0
        if day in labels.index and code in labels.columns and isfinite(value):
            labels.at[day, code] = value
    return labels


def _cross_section(scores: pd.DataFrame, labels: pd.DataFrame, active: pd.Series) -> CrossSectionAnalysis:
    days = active.index[active.astype(bool)]
    if len(days) == 0:
        empty = pd.DataFrame(index=days)
        return CrossSectionAnalysis(empty, empty, {"days": 0, "evaluated_days": 0})
    return analyze_cross_section(scores.loc[days], labels.loc[days], group_count=PTH252_GROUP_COUNT)


def _execute_variant(
    store: Any,
    context: Mapping[str, Any],
    signals: pd.DataFrame,
    engine: Pth252FactorEngine,
) -> BacktestResult:
    variant = dict(context)
    variant.update(engine=engine, signals=signals, resolved_params=engine.default_params())
    return execute_backtest_context(store, variant, use_fast=False)


def _signal_diagnostics(
    quantiles: QuantileSignals,
    *,
    primary: pd.DataFrame,
    bottom: pd.DataFrame,
    close_top: pd.DataFrame,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in quantiles.status.index:
        day_key = _day_key(day)
        if not start <= day_key <= end or quantiles.status.loc[day] != "selected":
            continue
        rows.append({
            "date": day_key,
            "top_decile_candidates": int(quantiles.top.loc[day].sum()),
            "primary_selected": int(primary.loc[day].sum()),
            "bottom_selected": int(bottom.loc[day].sum()),
            "close_reference_selected": int(close_top.loc[day].sum()),
        })
    return rows


def _factor_report(
    card: ResearchRunCard,
    analysis: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
) -> str:
    summary = dict(dict(analysis.get("cross_section") or {}).get("summary") or {})
    bottom_metrics = dict(dict(sensitivity.get("bottom_decile") or {}).get("metrics") or {})
    return "\n".join([
        f"# PTH252 Factor Experiment {card.run_id}",
        "",
        "- Formula: close / rolling_max(high, 252)",
        "- Execution: signal after close, T+1 open, 20 trading-day hold",
        "- Selection: top decile, score-ranked cap of 20, no weak refill",
        f"- Validation: {dict(card.validation).get('status')}",
        f"- RankIC mean: {summary.get('rank_ic_mean')}",
        f"- RankIC IR: {summary.get('rank_icir')}",
        f"- Primary PF: {dict(card.metrics).get('profit_factor')}",
        f"- Bottom sensitivity PF: {bottom_metrics.get('profit_factor')}",
        "",
        "This is a research candidate only. It does not alter or register a production strategy.",
        "",
    ])


__all__ = ["write_pth252_factor_artifacts"]
