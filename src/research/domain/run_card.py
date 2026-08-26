"""研究运行卡与 artifact manifest 的纯领域契约。

Run card 是一次研究计算的审计索引，不替代行情、账本或回测结果本身。
输入部分由 ``input_sha256`` 绑定；结果可以追加状态和 artifact，但不能静默
修改已经完成 run 的计算输入。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from src.shared.clock import utc_now as _utc_now
import hashlib
import json
from pathlib import PurePath
import re
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence


RunCardStatus = Literal[
    "running",
    "awaiting_human_review",
    "completed",
    "stale",
    "failed",
    "rejected",
]
RUN_CARD_STATUSES: tuple[RunCardStatus, ...] = (
    "running",
    "awaiting_human_review",
    "completed",
    "stale",
    "failed",
    "rejected",
)
RUN_CARD_CONTRACT_VERSION = "research-run-card-v1"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _json_value(value: Any) -> Any:
    """将常见配置对象转为可稳定序列化的普通 JSON 值。"""
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, PurePath):
        return value.as_posix()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_value(value.model_dump(mode="json"))
    return value


def _freeze(value: Any) -> Any:
    """深冻结输入，避免冻结 dataclass 后仍可通过嵌套 dict 修改。"""
    value = _json_value(value)
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _thaw(asdict(value))
    return value


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _thaw(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_run_id(run_id: str) -> str:
    """校验 run id 可作为单一目录名使用。"""
    value = str(run_id or "")
    if not _SAFE_RUN_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError("研究 run id 无效")
    return value


def validate_relative_artifact_path(path: str) -> str:
    """校验 artifact manifest 中的相对路径，拒绝绝对路径和目录穿越。"""
    value = str(path or "").replace("\\", "/")
    raw_parts = value.split("/")
    candidate = PurePath(value)
    if (
        not value
        or not candidate.parts
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise ValueError("artifact 路径必须是非空相对路径")
    if any(part.endswith(":") for part in candidate.parts):
        raise ValueError("artifact 路径不得包含盘符")
    return "/".join(candidate.parts)


@dataclass(frozen=True, slots=True)
class ArtifactManifestEntry:
    """run 目录内一个产物的内容寻址记录。"""

    path: str
    sha256: str
    created_at: str = field(default_factory=_utc_now)
    size_bytes: int | None = None
    artifact_type: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_relative_artifact_path(self.path))
        digest = str(self.sha256 or "").lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError("artifact sha256 无效")
        object.__setattr__(self, "sha256", digest)
        if self.size_bytes is not None and int(self.size_bytes) < 0:
            raise ValueError("artifact size_bytes 不得为负")
        object.__setattr__(self, "metadata", _freeze(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "artifact_type": self.artifact_type,
            "metadata": _thaw(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ArtifactManifestEntry:
        return cls(
            path=str(raw.get("path") or ""),
            sha256=str(raw.get("sha256") or raw.get("hash") or ""),
            created_at=str(raw.get("created_at") or _utc_now()),
            size_bytes=(int(raw["size_bytes"]) if raw.get("size_bytes") is not None else None),
            artifact_type=str(raw.get("artifact_type") or ""),
            metadata=dict(raw.get("metadata") or {}),
        )


ArtifactManifestItem = ArtifactManifestEntry
ArtifactRef = ArtifactManifestEntry


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """方便独立传递的 manifest 值对象。"""

    entries: tuple[ArtifactManifestEntry, ...] = ()

    def __post_init__(self) -> None:
        normalized: list[ArtifactManifestEntry] = []
        for item in self.entries:
            if isinstance(item, ArtifactManifestEntry):
                normalized.append(item)
            elif isinstance(item, Mapping):
                normalized.append(ArtifactManifestEntry.from_dict(item))
            else:
                raise TypeError("artifact manifest 条目无效")
        object.__setattr__(self, "entries", tuple(normalized))

    @property
    def artifacts(self) -> tuple[ArtifactManifestEntry, ...]:
        return self.entries

    def to_dict(self) -> dict[str, Any]:
        return {"artifacts": [item.to_dict() for item in self.entries]}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> ArtifactManifest:
        if isinstance(raw, Mapping):
            values = raw.get("artifacts", raw.get("artifact_manifest", []))
        else:
            values = raw
        return cls(tuple(ArtifactManifestEntry.from_dict(item) for item in values if isinstance(item, Mapping)))


def _evidence_value(item: Any) -> Any:
    if isinstance(item, Mapping):
        return _freeze(item)
    if is_dataclass(item) and not isinstance(item, type):
        return _freeze(asdict(item))
    return _freeze(item)


@dataclass(frozen=True, slots=True)
class ResearchRunCard:
    """一次研究计算的不可变输入 + 可追加结果记录。"""

    run_id: str
    strategy_slug: str = ""
    strategy_revision: str = ""
    version: str = ""
    hypothesis_id: str | None = None
    hypothesis_revision: int | None = None
    requested_as_of: str = ""
    actual_as_of: str = ""
    market_revision: str = ""
    universe: Mapping[str, Any] = field(default_factory=dict)
    universe_funnel: Mapping[str, Any] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)
    backtest_config: Mapping[str, Any] = field(default_factory=dict)
    data_snapshot: Mapping[str, Any] = field(default_factory=dict)
    source_evidence: tuple[Any, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    validation: Mapping[str, Any] = field(default_factory=dict)
    risk_xray: Mapping[str, Any] = field(default_factory=dict)
    conclusion: Any = ""
    artifact_manifest: tuple[ArtifactManifestEntry, ...] = ()
    status: RunCardStatus = "running"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = ""
    input_sha256: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        if self.status not in RUN_CARD_STATUSES:
            raise ValueError(f"研究 run 状态无效：{self.status}")

        for name in (
            "universe",
            "universe_funnel",
            "params",
            "backtest_config",
            "data_snapshot",
            "metrics",
            "validation",
            "risk_xray",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name) or {}))
        object.__setattr__(
            self,
            "source_evidence",
            tuple(_evidence_value(item) for item in (self.source_evidence or ())),
        )

        manifest: list[ArtifactManifestEntry] = []
        for item in self.artifact_manifest or ():
            if isinstance(item, ArtifactManifestEntry):
                manifest.append(item)
            elif isinstance(item, Mapping):
                manifest.append(ArtifactManifestEntry.from_dict(item))
            else:
                raise TypeError("artifact manifest 条目无效")
        object.__setattr__(self, "artifact_manifest", tuple(manifest))
        object.__setattr__(self, "conclusion", _freeze(self.conclusion) if isinstance(self.conclusion, Mapping) else self.conclusion)
        if not self.updated_at:
            object.__setattr__(self, "updated_at", self.created_at)

        computed = _canonical_hash(self.input_payload())
        provided = str(self.input_sha256 or "")
        if provided and provided != computed:
            raise ValueError("input_sha256 与研究输入不一致")
        object.__setattr__(self, "input_sha256", computed)

    @property
    def id(self) -> str:
        """兼容现有 ResearchArtifactStore 的 ``id`` 字段。"""
        return self.run_id

    @property
    def artifacts(self) -> tuple[ArtifactManifestEntry, ...]:
        return self.artifact_manifest

    def input_payload(self) -> dict[str, Any]:
        """返回参与输入指纹的字段；结果字段不在其中。"""
        return {
            "strategy_slug": self.strategy_slug,
            "strategy_revision": self.strategy_revision,
            "version": self.version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_revision": self.hypothesis_revision,
            "requested_as_of": self.requested_as_of,
            "actual_as_of": self.actual_as_of,
            "market_revision": self.market_revision,
            "universe": _thaw(self.universe),
            "universe_funnel": _thaw(self.universe_funnel),
            "params": _thaw(self.params),
            "backtest_config": _thaw(self.backtest_config),
            "data_snapshot": _thaw(self.data_snapshot),
            "source_evidence": [_thaw(item) for item in self.source_evidence],
        }

    def with_updates(self, **changes: Any) -> ResearchRunCard:
        """返回新值对象；存储层仍会阻止已写入 run 的输入变化。"""
        input_fields = {
            "strategy_slug",
            "strategy_revision",
            "version",
            "hypothesis_id",
            "hypothesis_revision",
            "requested_as_of",
            "actual_as_of",
            "market_revision",
            "universe",
            "universe_funnel",
            "params",
            "backtest_config",
            "data_snapshot",
            "source_evidence",
        }
        if input_fields.intersection(changes):
            # 让新值对象自行计算新 hash，随后由 store 与已落盘 hash 比较并
            # 抛出 RunCardImmutableError；不要在这里把冲突伪装成旧 hash。
            changes["input_sha256"] = ""
        changes.setdefault("updated_at", _utc_now())
        return replace(self, **changes)

    def with_status(self, status: RunCardStatus, *, error: str = "") -> ResearchRunCard:
        return self.with_updates(status=status, error=error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": RUN_CARD_CONTRACT_VERSION,
            "run_id": self.run_id,
            "strategy_slug": self.strategy_slug,
            "strategy_revision": self.strategy_revision,
            "version": self.version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_revision": self.hypothesis_revision,
            "requested_as_of": self.requested_as_of,
            "actual_as_of": self.actual_as_of,
            "market_revision": self.market_revision,
            "universe": _thaw(self.universe),
            "universe_funnel": _thaw(self.universe_funnel),
            "params": _thaw(self.params),
            "backtest_config": _thaw(self.backtest_config),
            "data_snapshot": _thaw(self.data_snapshot),
            "source_evidence": [_thaw(item) for item in self.source_evidence],
            "metrics": _thaw(self.metrics),
            "validation": _thaw(self.validation),
            "risk_xray": _thaw(self.risk_xray),
            "conclusion": _thaw(self.conclusion),
            "artifact_manifest": [item.to_dict() for item in self.artifact_manifest],
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_sha256": self.input_sha256,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ResearchRunCard:
        manifest = raw.get("artifact_manifest", raw.get("artifacts", []))
        entries = tuple(
            ArtifactManifestEntry.from_dict(item)
            for item in manifest
            if isinstance(item, Mapping)
        )
        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in raw.items() if key in known}
        values["run_id"] = str(raw.get("run_id") or raw.get("id") or "")
        values["artifact_manifest"] = entries
        values["source_evidence"] = tuple(raw.get("source_evidence") or raw.get("evidence") or ())
        values["status"] = str(raw.get("status") or "running")
        return cls(**values)  # type: ignore[arg-type]


RunCard = ResearchRunCard

__all__ = [
    "ArtifactManifest",
    "ArtifactManifestEntry",
    "ArtifactManifestItem",
    "ArtifactRef",
    "RUN_CARD_CONTRACT_VERSION",
    "RUN_CARD_STATUSES",
    "ResearchRunCard",
    "RunCard",
    "RunCardStatus",
    "validate_relative_artifact_path",
    "validate_run_id",
]
