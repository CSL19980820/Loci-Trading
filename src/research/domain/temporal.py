"""研究数据的时点与历史股票池契约。

这些对象只描述输入可见性，不负责取数。没有足够的时点证据时，调用方必须
保留 degraded 标记或阻断研究，不得把当前值静默回填到历史日期。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import re
from typing import Any, Iterable, Literal, Mapping


class TemporalDataError(ValueError):
    """时点数据不满足研究契约。"""


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _iso(value: str | date) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise TemporalDataError(f"日期格式无效：{text}") from exc
    return text


def _timestamp(value: str) -> str:
    """校验外部事实的实际抓取时刻，保留原始 ISO 文本用于审计。"""
    text = str(value).strip()
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TemporalDataError(f"抓取时间格式无效：{text}") from exc
    return text


def _payload_digest(value: str) -> str:
    text = str(value).strip().lower()
    if text and not _SHA256.fullmatch(text):
        raise TemporalDataError("payload_sha256 必须是 64 位十六进制摘要")
    return text


@dataclass(frozen=True, slots=True)
class PointInTimeObservation:
    """一条带可见时间的外部/本地事实。"""

    observation_id: str
    entity_id: str
    observed_on: str
    available_at: str
    values: dict[str, Any] = field(default_factory=dict)
    source_id: str = ""
    source_url: str = ""
    published_at: str = ""
    revision: str = ""
    fetched_at: str = ""
    payload_sha256: str = ""
    parser_revision: str = ""
    restated: bool = False
    fact_type: Literal["financial", "event", "other"] = "other"

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_on", _iso(self.observed_on))
        object.__setattr__(self, "available_at", _iso(self.available_at))
        if self.published_at:
            object.__setattr__(self, "published_at", _iso(self.published_at))
        object.__setattr__(self, "fetched_at", _timestamp(self.fetched_at))
        object.__setattr__(self, "payload_sha256", _payload_digest(self.payload_sha256))
        if self.fact_type not in {"financial", "event", "other"}:
            raise TemporalDataError("fact_type 仅支持 financial/event/other")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PointInTimeObservation:
        return cls(
            observation_id=str(raw.get("observation_id") or ""),
            entity_id=str(raw.get("entity_id") or ""),
            observed_on=str(raw.get("observed_on") or ""),
            available_at=str(raw.get("available_at") or ""),
            values=dict(raw.get("values") or {}),
            source_id=str(raw.get("source_id") or ""),
            source_url=str(raw.get("source_url") or ""),
            published_at=str(raw.get("published_at") or ""),
            revision=str(raw.get("revision") or ""),
            fetched_at=str(raw.get("fetched_at") or ""),
            payload_sha256=str(raw.get("payload_sha256") or ""),
            parser_revision=str(raw.get("parser_revision") or ""),
            restated=bool(raw.get("restated", False)),
            fact_type=str(raw.get("fact_type") or "other"),  # type: ignore[arg-type]
        )


def select_point_in_time(
    observations: Iterable[PointInTimeObservation],
    *,
    as_of: str | date,
    entity_id: str | None = None,
) -> PointInTimeObservation | None:
    """选择截止 ``as_of`` 已经可见的最新观察值。

    同一可见日有多条修订时，revision/observation_id 只用于稳定排序；调用者
    仍应在研究结果中保留被选中的 observation_id。
    """
    cutoff = _iso(as_of)
    eligible = [
        item
        for item in observations
        if item.available_at <= cutoff and (entity_id is None or item.entity_id == entity_id)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (item.available_at, item.revision, item.observation_id),
    )


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    """某个生效日的指数/股票池成分快照及其实际可见日期。"""

    universe_id: str
    as_of: str
    members: tuple[str, ...]
    available_at: str = ""
    source_id: str = ""
    source_url: str = ""
    snapshot_revision: str = ""
    fetched_at: str = ""
    payload_sha256: str = ""
    parser_revision: str = ""
    pit_membership: bool = False
    survivorship_bias: bool = False
    degraded: bool = False
    missing_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _iso(self.as_of))
        if self.available_at:
            object.__setattr__(self, "available_at", _iso(self.available_at))
        object.__setattr__(self, "fetched_at", _timestamp(self.fetched_at))
        object.__setattr__(self, "payload_sha256", _payload_digest(self.payload_sha256))
        object.__setattr__(self, "members", tuple(sorted({str(item).strip() for item in self.members if str(item).strip()})))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MembershipSnapshot:
        return cls(
            universe_id=str(raw.get("universe_id") or ""),
            as_of=str(raw.get("as_of") or ""),
            members=tuple(str(item) for item in raw.get("members", ()) if str(item)),
            available_at=str(raw.get("available_at") or ""),
            source_id=str(raw.get("source_id") or ""),
            source_url=str(raw.get("source_url") or ""),
            snapshot_revision=str(raw.get("snapshot_revision") or ""),
            fetched_at=str(raw.get("fetched_at") or ""),
            payload_sha256=str(raw.get("payload_sha256") or ""),
            parser_revision=str(raw.get("parser_revision") or ""),
            pit_membership=bool(raw.get("pit_membership", False)),
            survivorship_bias=bool(raw.get("survivorship_bias", False)),
            degraded=bool(raw.get("degraded", False)),
            missing_reason=str(raw.get("missing_reason") or ""),
        )


def resolve_membership(
    snapshots: Iterable[MembershipSnapshot],
    *,
    universe_id: str,
    as_of: str | date,
) -> MembershipSnapshot:
    """按截止日选择当时已可见的最近成分快照。"""
    cutoff = _iso(as_of)
    effective = [
        snapshot
        for snapshot in snapshots
        if snapshot.universe_id == universe_id and snapshot.as_of <= cutoff
    ]
    eligible = [
        snapshot
        for snapshot in effective
        if snapshot.available_at and snapshot.available_at <= cutoff
    ]
    if not eligible:
        reason = (
            "缺少该日期以前的历史成分快照"
            if not effective
            else "历史成分快照在该日期尚不可见或缺少 available_at"
        )
        return MembershipSnapshot(
            universe_id=universe_id,
            as_of=cutoff,
            members=(),
            pit_membership=False,
            survivorship_bias=True,
            degraded=True,
            missing_reason=reason,
        )
    return max(
        eligible,
        key=lambda snapshot: (snapshot.as_of, snapshot.available_at, snapshot.snapshot_revision),
    )


def assert_strict_membership(snapshot: MembershipSnapshot) -> None:
    """严格回测禁止使用降级/生存者偏差股票池。"""
    if snapshot.degraded or snapshot.survivorship_bias or not snapshot.pit_membership:
        reason = snapshot.missing_reason or "股票池不是 point-in-time 快照"
        raise TemporalDataError(f"严格回测拒绝历史股票池：{reason}")
    if not snapshot.members:
        raise TemporalDataError("严格回测拒绝空的历史股票池快照")
    if not snapshot.available_at:
        raise TemporalDataError("严格回测要求历史股票池含 available_at")
    if not snapshot.source_id or not snapshot.source_url or not snapshot.snapshot_revision:
        raise TemporalDataError("严格回测要求历史股票池含来源、链接和版本")
    missing = [
        field
        for field, value in (
            ("fetched_at", snapshot.fetched_at),
            ("payload_sha256", snapshot.payload_sha256),
            ("parser_revision", snapshot.parser_revision),
        )
        if not value
    ]
    if missing:
        raise TemporalDataError(
            "严格回测要求历史股票池含原始载荷证据：" + ",".join(missing)
        )
