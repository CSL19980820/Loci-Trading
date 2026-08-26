"""历史股票池与 PIT 事实的 HTTP 请求契约。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from src.research.domain.temporal import MembershipSnapshot, PointInTimeObservation


class PointInTimeFactRequest(BaseModel):
    """一条可追加的、带披露可见时间的事实。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    observation_id: str = Field(min_length=1, max_length=160)
    entity_id: str = Field(min_length=1, max_length=64)
    observed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    available_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    values: dict[str, Any] = Field(default_factory=dict, max_length=256)
    source_id: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2_000)
    published_at: str = Field(default="", max_length=10)
    revision: str = Field(min_length=1, max_length=128)
    fetched_at: str = Field(min_length=1, max_length=64)
    payload_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    parser_revision: str = Field(min_length=1, max_length=128)
    restated: bool = False
    fact_type: Literal["financial", "event", "other"] = "other"

    def to_domain(self) -> PointInTimeObservation:
        return PointInTimeObservation(**self.model_dump())


class PointInTimeFactImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[PointInTimeFactRequest] = Field(min_length=1, max_length=10_000)


class MembershipSnapshotRequest(BaseModel):
    """一份日期化历史股票池快照，来源和版本不可省略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    universe_id: str = Field(min_length=1, max_length=128)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    available_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    members: list[StrictStr] = Field(max_length=20_000)
    source_id: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2_000)
    snapshot_revision: str = Field(min_length=1, max_length=128)
    fetched_at: str = Field(min_length=1, max_length=64)
    payload_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    parser_revision: str = Field(min_length=1, max_length=128)
    pit_membership: bool = False
    survivorship_bias: bool = False
    degraded: bool = False
    missing_reason: str = Field(default="", max_length=2_000)

    def to_domain(self) -> MembershipSnapshot:
        return MembershipSnapshot(
            **{**self.model_dump(), "members": tuple(self.members)}
        )


class MembershipSnapshotImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshots: list[MembershipSnapshotRequest] = Field(min_length=1, max_length=10_000)


__all__ = [
    "MembershipSnapshotImportRequest",
    "MembershipSnapshotRequest",
    "PointInTimeFactImportRequest",
    "PointInTimeFactRequest",
]
