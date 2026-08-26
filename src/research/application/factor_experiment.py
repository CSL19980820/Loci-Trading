"""PTH252 research-only factor experiment and its private execution engine.

The engine deliberately stays out of ``src.strategy``.  It can create an
auditable research card, but cannot change the active strategy catalogue.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, TrainOOSSplit
from src.research.application.backtest_run import (
    ResearchBacktestOutcome,
    run_research_backtest,
)
from src.research.application.factor_analysis import (
    build_quantile_signals,
    compute_pth252_scores,
)
from src.research.domain.run_card import ResearchRunCard
from src.research.infrastructure import (
    MembershipSnapshotStore,
    ResearchRunCardStore,
    ResearchWorkflowStore,
)
from src.strategy import SignalResult


PTH252_FACTOR_ID = "pth252"
PTH252_STRATEGY_SLUG = "research-pth252"
PTH252_WINDOW = 252
PTH252_TOP_QUANTILE = 0.9
PTH252_GROUP_COUNT = 10
PTH252_REBALANCE_EVERY = 20
PTH252_SELECTION_CAPACITY = 20


class Pth252FactorExperimentError(ValueError):
    """The factor task is invalid or cannot provide the requested evidence."""

    def __init__(self, message: str, *, run_id: str = "") -> None:
        super().__init__(message)
        self.run_id = run_id


@dataclass(frozen=True, slots=True)
class Pth252FactorEngine:
    """Private ``StrategyEngine`` shape used only to reuse the execution engine."""

    signal_start: str
    reference: str = "high"
    top_quantile: float = PTH252_TOP_QUANTILE
    rebalance_every: int = PTH252_REBALANCE_EVERY
    selection_capacity: int = PTH252_SELECTION_CAPACITY
    slug: str = PTH252_STRATEGY_SLUG
    name: str = "PTH252 因子实验"
    description: str = "收盘价相对 252 日高点的研究候选，不进入活动策略目录"
    entry_timing: str = "next_open"
    strategy_revision: str = "research-pth252-v1"
    version: str = "research-v1"
    adjust: str = "qfq"
    default_universe: dict[str, Any] | None = None

    def default_params(self) -> dict[str, Any]:
        return {
            "factor_id": PTH252_FACTOR_ID,
            "signal_start": self.signal_start,
            "reference": self.reference,
            "top_quantile": self.top_quantile,
            "rebalance_every": self.rebalance_every,
            "selection_capacity": self.selection_capacity,
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return PTH252_WINDOW

    def rebalance_dates(self, index: pd.Index) -> list[object]:
        eligible = [day for day in index if _day_key(day) >= self.signal_start]
        return eligible[::self.rebalance_every]

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        values = _factor_params(params or self.default_params())
        if values["signal_start"] != self.signal_start:
            raise Pth252FactorExperimentError("PTH252 signal_start 与冻结引擎不一致")
        scores = compute_pth252_scores(
            panels["close"], panels.get("high"),
            reference=values["reference"], window=PTH252_WINDOW,
        )
        quantiles = build_quantile_signals(
            scores,
            group_count=PTH252_GROUP_COUNT,
            rebalance_dates=self.rebalance_dates(scores.index),
        )
        signals = _cap_quantile(
            quantiles.top,
            scores,
            capacity=values["selection_capacity"],
            highest=True,
        )
        return SignalResult(
            signals=signals,
            factors={
                "pth252": scores,
                "quantile_group": quantiles.groups,
                "top_decile": quantiles.top,
                "bottom_decile": quantiles.bottom,
            },
        )


@dataclass(frozen=True, slots=True)
class Pth252FactorExperimentOutcome:
    run_card: ResearchRunCard
    workflow: Any
    factor_summary: Mapping[str, Any]


def pth252_backtest_config() -> BacktestConfig:
    """The preregistered execution convention for this candidate."""
    return BacktestConfig(
        hold_days=20,
        stop_loss_pct=None,
        take_profit_pct=None,
        commission_bps=3.0,
        stamp_duty_bps=10.0,
        slippage_bps=5.0,
        allow_limit_up_entry=False,
        benchmark="000300",
    )


def pth252_engine_from_frozen_params(params: Mapping[str, Any]) -> Pth252FactorEngine:
    """Restore the private engine for frozen replay without registering it."""
    values = _factor_params(params)
    return Pth252FactorEngine(
        signal_start=values["signal_start"],
        reference=values["reference"],
        top_quantile=values["top_quantile"],
        rebalance_every=values["rebalance_every"],
        selection_capacity=values["selection_capacity"],
    )


def run_pth252_factor_experiment(
    store: Any,
    *,
    start: str,
    end: str,
    split: TrainOOSSplit,
    historical_universe_id: str | None,
    strict_pit: bool,
    membership_store: MembershipSnapshotStore | None = None,
    run_card_store: ResearchRunCardStore | None = None,
    workflow_store: ResearchWorkflowStore | None = None,
    random_repeats: int = 200,
    bootstrap_iterations: int = 200,
    monte_carlo_iterations: int = 200,
) -> Pth252FactorExperimentOutcome:
    """Run the fixed candidate and append PTH252-only evidence artifacts.

    The API fixes ``strict_pit`` to true.  The exploratory branch is available
    only to an explicit local caller and remains degraded by the shared run
    workflow; it never creates a production strategy.
    """
    _validate_dates(start=start, end=end, split=split)
    memberships = membership_store or MembershipSnapshotStore()
    cards = run_card_store or ResearchRunCardStore()
    if strict_pit:
        if not historical_universe_id:
            raise Pth252FactorExperimentError("strict_pit=true 时必须提供 historical_universe_id")
        if not memberships.list(universe_id=historical_universe_id):
            raise Pth252FactorExperimentError(
                "严格 PIT 缺少历史股票池快照，任务不会降级为探索性通过"
            )

    engine = Pth252FactorEngine(signal_start=start)
    try:
        base: ResearchBacktestOutcome = run_research_backtest(
            store,
            strategy=engine,
            start=start,
            end=end,
            params=engine.default_params(),
            backtest_config=pth252_backtest_config(),
            split=split,
            initial_capital=200_000.0,
            max_positions=PTH252_SELECTION_CAPACITY,
            lot_size=100,
            seed=0,
            random_repeats=random_repeats,
            bootstrap_iterations=bootstrap_iterations,
            monte_carlo_iterations=monte_carlo_iterations,
            historical_universe_id=historical_universe_id,
            strict_pit=strict_pit,
            membership_store=memberships,
            run_card_store=cards,
            workflow_store=workflow_store,
        )
    except Exception as exc:
        if isinstance(exc, Pth252FactorExperimentError):
            raise
        raise Pth252FactorExperimentError(
            f"PTH252 执行失败：{type(exc).__name__}: {exc}"
        ) from exc

    card = cards.require(base.run_card.run_id)
    try:
        factor_summary = _write_factor_artifacts(store, cards, card)
        card = _annotate_candidate_card(cards, cards.require(card.run_id))
    except Exception as exc:
        raise Pth252FactorExperimentError(
            f"PTH252 因子分析产物失败：{type(exc).__name__}: {exc}",
            run_id=card.run_id,
        ) from exc
    if strict_pit and card.validation.get("status") != "passed":
        reasons = card.validation.get("failures") or ["严格 PIT 验证未通过"]
        raise Pth252FactorExperimentError(
            "严格 PIT 任务失败：" + "；".join(map(str, reasons)),
            run_id=card.run_id,
        )
    return Pth252FactorExperimentOutcome(card, base.workflow, factor_summary)


def _factor_params(params: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(params)
    expected = {
        "factor_id": PTH252_FACTOR_ID,
        "reference": "high",
        "top_quantile": PTH252_TOP_QUANTILE,
        "rebalance_every": PTH252_REBALANCE_EVERY,
        "selection_capacity": PTH252_SELECTION_CAPACITY,
    }
    for key, required in expected.items():
        if values.get(key) != required:
            raise Pth252FactorExperimentError(f"PTH252 参数 {key} 必须固定为 {required!r}")
    signal_start = str(values.get("signal_start") or "")
    if not _is_date(signal_start):
        raise Pth252FactorExperimentError("PTH252 signal_start 必须为 YYYY-MM-DD")
    return {**expected, "signal_start": signal_start}


def _cap_quantile(
    candidates: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    capacity: int,
    highest: bool,
) -> pd.DataFrame:
    selected = pd.DataFrame(False, index=candidates.index, columns=candidates.columns)
    for day in candidates.index:
        allowed = candidates.loc[day].fillna(False).astype(bool)
        row = scores.loc[day, allowed]
        valid = row[np.isfinite(row) & row.gt(0)]
        ordered = sorted(
            valid.index,
            key=lambda code: ((-1 if highest else 1) * float(valid.loc[code]), str(code)),
        )
        selected.loc[day, ordered[:capacity]] = True
    return selected


def _write_factor_artifacts(
    store: Any,
    cards: ResearchRunCardStore,
    card: ResearchRunCard,
) -> dict[str, Any]:
    # Lazy import keeps the private engine available to frozen replay without a
    # module import cycle, while isolating bulky artifact derivation.
    from src.research.application.factor_artifacts import write_pth252_factor_artifacts

    return write_pth252_factor_artifacts(store, cards, card)


def _restricted_signals(
    signals: pd.DataFrame,
    *,
    start: str,
    end: str,
    membership_mask: pd.DataFrame | None,
) -> pd.DataFrame:
    selected = signals.fillna(False).astype(bool).copy()
    in_range = pd.Series([start <= _day_key(day) <= end for day in selected.index], index=selected.index)
    selected.loc[~in_range, :] = False
    if membership_mask is not None:
        mask = membership_mask.reindex(index=selected.index, columns=selected.columns).fillna(False)
        selected &= mask.astype(bool)
    return selected


def _annotate_candidate_card(cards: ResearchRunCardStore, card: ResearchRunCard) -> ResearchRunCard:
    if card.status != "awaiting_human_review":
        return card
    conclusion = dict(card.conclusion) if isinstance(card.conclusion, Mapping) else {}
    conclusion.update({
        "research_kind": "PTH252 factor candidate",
        "production_strategy_registered": False,
        "default_parameters_changed": False,
        "activation": "研究证据不注册为活动战法，需独立授权与复核",
    })
    return cards.save(card.with_updates(conclusion=conclusion))


def _validate_dates(*, start: str, end: str, split: TrainOOSSplit) -> None:
    values = (start, end, split.train_start, split.train_end, split.oos_start, split.oos_end)
    if not all(_is_date(value) for value in values):
        raise Pth252FactorExperimentError("PTH252 日期必须为 YYYY-MM-DD")
    if not (start <= split.train_start <= split.train_end < split.oos_start <= split.oos_end <= end):
        raise Pth252FactorExperimentError("PTH252 train/OOS 必须递增、不重叠并包含在样本区间内")


def _is_date(value: str) -> bool:
    return len(value) == 10 and value[4] == "-" and value[7] == "-" and value.replace("-", "").isdigit()


def _day_key(value: object) -> str:
    return str(value)[:10]


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        return value if isfinite(value) else None
    return value


__all__ = [
    "PTH252_FACTOR_ID",
    "PTH252_REBALANCE_EVERY",
    "PTH252_SELECTION_CAPACITY",
    "PTH252_TOP_QUANTILE",
    "PTH252_WINDOW",
    "Pth252FactorEngine",
    "Pth252FactorExperimentError",
    "Pth252FactorExperimentOutcome",
    "pth252_backtest_config",
    "pth252_engine_from_frozen_params",
    "run_pth252_factor_experiment",
]
