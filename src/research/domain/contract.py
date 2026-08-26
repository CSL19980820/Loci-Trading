"""研究产物的稳定数据契约。

研究结果是可解释的中间产物，不是行情仓或账本的第二套真相。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Quality = Literal["full", "partial", "missing", "error"]
IssueSeverity = Literal["critical", "warning", "info"]
SourceState = Literal[
    "registered", "probed", "selected", "failed", "skipped", "cancelled", "not_probed", "not_observed"
]
SourceObservationKind = Literal["route_receipt", "route_attempt", "legacy_row", "local_snapshot"]


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """能回溯到一次取数或本地事实的引用。"""

    source_id: str
    source_url: str = ""
    title: str = ""
    observed_at: str = ""
    as_of: str = ""
    payload_sha256: str = ""
    quote: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceAttempt:
    """来源回执、单次尝试或本地快照的类型化投影。"""

    source_id: str
    state: SourceState
    checked_at: str = ""
    rtt_ms: float | None = None
    row_sources: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    error: str = ""
    kind: SourceObservationKind = "route_attempt"
    receipt_id: str = ""
    code: str = ""
    lane: str = ""
    unresolved: bool = False
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["row_sources"] = list(self.row_sources)
        body["fields"] = list(self.fields)
        return body


@dataclass(frozen=True, slots=True)
class DimensionResult:
    """单个维度的事实、质量和缺口。"""

    key: str
    name: str
    quality: Quality
    source: str
    retrieved_at: str
    as_of: str
    data_gaps: tuple[str, ...] = ()
    values: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["data_gaps"] = list(self.data_gaps)
        body["evidence"] = [item.to_dict() for item in self.evidence]
        return body


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    """研究终稿门禁发现的问题。"""

    severity: IssueSeverity
    code: str
    message: str
    dimension: str = ""
    evidence: tuple[str, ...] = ()
    suggested_fix: str = ""
    rule_version: str = "research-review-v1"

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["evidence"] = list(self.evidence)
        return body


@dataclass(frozen=True, slots=True)
class QualitySnapshot:
    """一次研究剖面的质量快照。"""

    overall: Quality
    blocked: bool
    completeness_ratio: float
    market_revision: str
    generated_at: str
    findings: tuple[ReviewIssue, ...] = ()
    market_health: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["findings"] = [item.to_dict() for item in self.findings]
        return body


@dataclass(frozen=True, slots=True)
class ResearchInputSnapshot:
    """研究计算所需的不可变输入；用于 resume 和 point-in-time 回放。"""

    code: str
    budget: str
    requested_as_of: str
    as_of: str
    adjust: str
    generated_at: str
    market_revision: str
    market_snapshot: dict[str, Any]
    market_health: dict[str, Any]
    instrument: dict[str, Any]
    latest: dict[str, Any]
    history: tuple[dict[str, Any], ...]
    source_attempts: tuple[SourceAttempt, ...]
    input_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "research-input-v1",
            "code": self.code,
            "budget": self.budget,
            "requested_as_of": self.requested_as_of,
            "as_of": self.as_of,
            "adjust": self.adjust,
            "generated_at": self.generated_at,
            "market_revision": self.market_revision,
            "market_snapshot": self.market_snapshot,
            "market_health": self.market_health,
            "instrument": self.instrument,
            "latest": self.latest,
            "history": list(self.history),
            "source_attempts": [item.to_dict() for item in self.source_attempts],
            "input_sha256": self.input_sha256,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ResearchInputSnapshot:
        attempts = tuple(
            SourceAttempt(
                source_id=str(item.get("source_id") or ""),
                state=str(item.get("state") or "failed"),  # type: ignore[arg-type]
                checked_at=str(item.get("checked_at") or ""),
                rtt_ms=item.get("rtt_ms"),
                row_sources=tuple(str(value) for value in item.get("row_sources", [])),
                fields=tuple(str(value) for value in item.get("fields", [])),
                error=str(item.get("error") or ""),
                kind=str(item.get("kind") or "route_attempt"),  # type: ignore[arg-type]
                receipt_id=str(item.get("receipt_id") or ""),
                code=str(item.get("code") or ""),
                lane=str(item.get("lane") or ""),
                unresolved=bool(item.get("unresolved", False)),
                fallback_used=bool(item.get("fallback_used", False)),
            )
            for item in raw.get("source_attempts", [])
            if isinstance(item, dict)
        )
        return cls(
            code=str(raw.get("code") or ""),
            budget=str(raw.get("budget") or "standard"),
            requested_as_of=str(raw.get("requested_as_of") or ""),
            as_of=str(raw.get("as_of") or ""),
            adjust=str(raw.get("adjust") or "qfq"),
            generated_at=str(raw.get("generated_at") or ""),
            market_revision=str(raw.get("market_revision") or ""),
            market_snapshot=dict(raw.get("market_snapshot") or {}),
            market_health=dict(raw.get("market_health") or {}),
            instrument=dict(raw.get("instrument") or {}),
            latest=dict(raw.get("latest") or {}),
            history=tuple(
                dict(item) for item in raw.get("history", []) if isinstance(item, dict)
            ),
            source_attempts=attempts,
            input_sha256=str(raw.get("input_sha256") or ""),
        )


@dataclass(frozen=True, slots=True)
class ResearchProfile:
    """个股研究剖面，绑定行情版本和运行预算。"""

    code: str
    subject: dict[str, Any]
    budget: str
    generated_at: str
    market_snapshot: dict[str, Any]
    dimensions: tuple[DimensionResult, ...]
    quality: QualitySnapshot
    requested_as_of: str = ""
    source_attempts: tuple[SourceAttempt, ...] = ()
    artifact_id: str = ""
    artifact_status: str = "transient"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "subject": self.subject,
            "budget": self.budget,
            "generated_at": self.generated_at,
            "market_snapshot": self.market_snapshot,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "quality": self.quality.to_dict(),
            "requested_as_of": self.requested_as_of,
            "source_attempts": [item.to_dict() for item in self.source_attempts],
            "artifact_id": self.artifact_id,
            "artifact_status": self.artifact_status,
            "contract": {
                "quality_values": ["full", "partial", "missing", "error"],
                "evidence_required": True,
                "production_signal": False,
            },
        }
