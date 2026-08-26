"""行情来源回执的可序列化契约。

回执是研究输入证据，不是供应商配置。它只记录某次请求实际尝试、命中和
覆盖情况，不能被解释为供应商质量评级。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from src.shared.clock import utc_now as utc_now
from typing import Any, Literal


SourceAttemptState = Literal[
    "attempted",
    "succeeded",
    "selected",
    "failed",
    "empty",
    "cancelled",
    "skipped",
]
SourceReceiptState = Literal["selected", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class SourceAttemptRecord:
    """一次数据源调用的结果。"""

    source_id: str
    state: SourceAttemptState
    checked_at: str = ""
    rows: int | None = None
    fields: tuple[str, ...] = ()
    source_url: str = ""
    published_at: str = ""
    publication_status: Literal["observed", "not_observed"] = "not_observed"
    fetched_at: str = ""
    as_of: str = ""
    payload_sha256: str = ""
    parser_revision: str = ""
    available_at: str = ""
    availability_status: Literal["observed", "not_observed"] = "not_observed"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["fields"] = list(self.fields)
        return body


@dataclass(frozen=True, slots=True)
class SourceRouteReceipt:
    """一只标的/一次 lane 请求的来源证据。"""

    code: str
    lane: str
    requested_sources: tuple[str, ...] = ()
    attempts: tuple[SourceAttemptRecord, ...] = ()
    selected_source: str = ""
    fallback_used: bool = False
    unresolved: bool = False
    state: SourceReceiptState = "selected"
    coverage: dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    published_at: str = ""
    publication_status: Literal["observed", "not_observed"] = "not_observed"
    fetched_at: str = ""
    as_of: str = ""
    payload_sha256: str = ""
    parser_revision: str = ""
    available_at: str = ""
    availability_status: Literal["observed", "not_observed"] = "not_observed"
    coverage_start: str = ""
    coverage_end: str = ""
    request_start: str = ""
    request_end: str = ""
    error: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["requested_sources"] = list(self.requested_sources)
        body["attempts"] = [item.to_dict() for item in self.attempts]
        return body
