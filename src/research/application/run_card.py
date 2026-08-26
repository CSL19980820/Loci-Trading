"""research run card 用例入口；不参与回测计算。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from src.research.domain.run_card import ResearchRunCard, RunCardStatus
from src.research.infrastructure.run_cards import ResearchRunCardStore


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return result
    raise TypeError("run card 配置必须是 mapping 或可序列化配置对象")


def create_run_card(
    *,
    strategy_slug: str = "",
    strategy_revision: str = "",
    version: str = "",
    hypothesis_id: str | None = None,
    requested_as_of: str = "",
    actual_as_of: str = "",
    market_revision: str = "",
    universe: Mapping[str, Any] | None = None,
    universe_funnel: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
    backtest_config: Any = None,
    data_snapshot: Mapping[str, Any] | None = None,
    source_evidence: tuple[Any, ...] | list[Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    validation: Mapping[str, Any] | None = None,
    risk_xray: Mapping[str, Any] | None = None,
    conclusion: Any = "",
    status: RunCardStatus = "running",
    run_id: str | None = None,
    store: ResearchRunCardStore | None = None,
) -> ResearchRunCard:
    """创建并持久化一张 run card。

    ``backtest_config`` 可以直接传 ``BacktestConfig``，application 只负责把
    它转成配置快照，不依赖回测模块的内部实现。
    """
    cards = store or ResearchRunCardStore()
    return cards.create(
        run_id=run_id,
        strategy_slug=strategy_slug,
        strategy_revision=strategy_revision,
        version=version,
        hypothesis_id=hypothesis_id,
        requested_as_of=requested_as_of,
        actual_as_of=actual_as_of,
        market_revision=market_revision,
        universe=universe or {},
        universe_funnel=universe_funnel or {},
        params=params or {},
        backtest_config=_mapping(backtest_config),
        data_snapshot=data_snapshot or {},
        source_evidence=tuple(source_evidence or ()),
        metrics=metrics or {},
        validation=validation or {},
        risk_xray=risk_xray or {},
        conclusion=conclusion,
        status=status,
    )


create_research_run_card = create_run_card


def save_run_card(
    card: ResearchRunCard | Mapping[str, Any],
    *,
    store: ResearchRunCardStore | None = None,
) -> ResearchRunCard:
    return (store or ResearchRunCardStore()).save(card)


def read_run_card(
    run_id: str,
    *,
    current_strategy_revision: str | None = None,
    current_market_revision: str | None = None,
    store: ResearchRunCardStore | None = None,
) -> ResearchRunCard | None:
    return (store or ResearchRunCardStore()).load(
        run_id,
        current_strategy_revision=current_strategy_revision,
        current_market_revision=current_market_revision,
    )


load_run_card = read_run_card


def update_run_card_status(
    run_id: str,
    status: RunCardStatus,
    *,
    error: str = "",
    store: ResearchRunCardStore | None = None,
) -> ResearchRunCard:
    return (store or ResearchRunCardStore()).update_status(run_id, status, error=error)


def mark_run_card_stale(
    run_id: str,
    *,
    current_strategy_revision: str | None = None,
    current_market_revision: str | None = None,
    store: ResearchRunCardStore | None = None,
) -> ResearchRunCard:
    return (store or ResearchRunCardStore()).mark_stale(
        run_id,
        current_strategy_revision=current_strategy_revision,
        current_market_revision=current_market_revision,
    )


__all__ = [
    "create_research_run_card",
    "create_run_card",
    "load_run_card",
    "mark_run_card_stale",
    "read_run_card",
    "save_run_card",
    "update_run_card_status",
]
