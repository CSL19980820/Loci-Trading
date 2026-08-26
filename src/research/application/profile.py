"""个股研究剖面用例。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.research.application.snapshot import (
    Budget,
    ResearchNotFoundError,
    capture_research_input,
)
from src.research.application.technical import build_basic_dimension, build_kline_dimension
from src.research.domain.contract import (
    DimensionResult,
    ResearchInputSnapshot,
    ResearchProfile,
)
from src.research.domain.dimensions import list_dimension_specs
from src.research.domain.review import build_quality_snapshot


def build_research_profile(
    store: Any,
    code: str,
    *,
    budget: Budget = "standard",
    as_of: str | None = None,
) -> ResearchProfile:
    """从本地行情仓构造不触网的临时研究剖面。"""
    snapshot = capture_research_input(store, code, budget=budget, as_of=as_of)
    return build_research_profile_from_snapshot(snapshot)


def build_research_profile_from_snapshot(
    snapshot: ResearchInputSnapshot,
    *,
    artifact_id: str = "",
    artifact_status: str = "transient",
) -> ResearchProfile:
    """只使用已保存输入重建 profile，不重新读取当前行情仓。"""
    frame = pd.DataFrame(list(snapshot.history))
    dimensions = [
        build_basic_dimension(
            snapshot.instrument,
            snapshot.latest,
            observed_at=snapshot.generated_at,
        ),
        build_kline_dimension(
            frame,
            observed_at=snapshot.generated_at,
            market_revision=snapshot.market_revision,
        ),
    ]
    dimensions.extend(
        _missing_dimension(spec.key, observed_at=snapshot.generated_at)
        for spec in list_dimension_specs()
        if spec.key not in {"0_basic", "2_kline"}
    )
    quality = build_quality_snapshot(
        dimensions,
        market_revision=snapshot.market_revision,
        market_health=snapshot.market_health,
        generated_at=snapshot.generated_at,
        cutoff_as_of=snapshot.as_of,
        source_attempts=snapshot.source_attempts,
    )
    subject = dict(snapshot.instrument)
    subject["code"] = snapshot.code
    if snapshot.latest:
        subject["latest"] = {
            key: snapshot.latest.get(key)
            for key in ("trade_date", "close", "pct", "turnover", "volume")
            if snapshot.latest.get(key) is not None
        }
    return ResearchProfile(
        code=snapshot.code,
        subject=subject,
        budget=snapshot.budget,
        generated_at=snapshot.generated_at,
        market_snapshot=dict(snapshot.market_snapshot),
        dimensions=tuple(dimensions),
        quality=quality,
        requested_as_of=snapshot.requested_as_of,
        source_attempts=snapshot.source_attempts,
        artifact_id=artifact_id,
        artifact_status=artifact_status,
    )


def _missing_dimension(key: str, *, observed_at: str) -> DimensionResult:
    spec = next(item for item in list_dimension_specs() if item.key == key)
    return DimensionResult(
        key=spec.key,
        name=spec.name,
        quality="missing",
        source="",
        retrieved_at=observed_at,
        as_of="",
        data_gaps=("本仓尚未接入该维度的可信、可回放来源",),
    )


__all__ = [
    "Budget",
    "ResearchNotFoundError",
    "build_research_profile",
    "build_research_profile_from_snapshot",
]
