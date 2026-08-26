"""账本写入请求模型。所有写入拒绝额外字段。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WriteModel(BaseModel):
    """所有账本写入仅接受声明字段，拒绝额外字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateInput(WriteModel):
    code: str = Field(pattern=r"^\d{6}$")
    name: str = ""
    decision: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=500)
    occurred_on: str | None = None
    pool_id: str = ""
    score: float | None = Field(default=None, ge=0, le=100)
    timing: str = ""
    rule_version: str = "潜龙"
    evidence: dict[str, Any] = Field(default_factory=dict)
    source: str = "web"


class CandidateBatchDeleteInput(WriteModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class PlanInput(WriteModel):
    code: str = Field(pattern=r"^\d{6}$")
    title: str = Field(min_length=1, max_length=80)
    scenario: str = Field(min_length=1, max_length=500)
    occurred_on: str | None = None
    entry_zone: str = ""
    stop_price: float | None = Field(default=None, ge=0)
    target_price: float | None = Field(default=None, ge=0)
    layers: float | None = Field(default=None, gt=0, le=10)
    invalidation: str = ""
    rule_version: str = "潜龙"
    supersedes_id: str | None = None
    note: str = ""
    source: str = "web"


class ReviewInput(WriteModel):
    entity_type: Literal["plan", "candidate", "trade"]
    entity_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1, max_length=500)
    reviewed_on: str | None = None
    strategy_tag: str = "潜龙"
    return_pct: float | None = None
    max_favorable_pct: float | None = None
    max_adverse_pct: float | None = None
    lesson: str = ""
    next_rule: str = ""
    source: str = "web"
