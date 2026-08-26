"""研究假设的纯领域模型。

假设不是策略参数的别名。它记录一个可证伪的论断、预注册门槛、关联 run
及其审计历史；只有满足门槛的证据才能从 testing 进入 validated。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from src.shared.clock import utc_now as _now
from enum import Enum
import math
import re
from typing import Any, Mapping


class HypothesisError(ValueError):
    """假设领域的基础错误。"""


class HypothesisEvidenceError(HypothesisError):
    """证据不完整、不可审计或未满足预注册门槛。"""


class HypothesisTransitionError(HypothesisError):
    """生命周期状态转换不合法。"""


class HypothesisConcurrencyError(HypothesisError):
    """持久化时发现调用方基于过期版本写入。"""


class HypothesisStatus(str, Enum):
    EXPLORING = "exploring"
    TESTING = "testing"
    VALIDATED = "validated"
    REJECTED = "rejected"
    MONITORING = "monitoring"


HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.EXPLORING: frozenset({
        HypothesisStatus.TESTING,
        HypothesisStatus.REJECTED,
    }),
    HypothesisStatus.TESTING: frozenset({
        HypothesisStatus.VALIDATED,
        HypothesisStatus.REJECTED,
    }),
    HypothesisStatus.VALIDATED: frozenset({
        HypothesisStatus.MONITORING,
        HypothesisStatus.REJECTED,
    }),
    HypothesisStatus.MONITORING: frozenset({
        HypothesisStatus.TESTING,
        HypothesisStatus.REJECTED,
    }),
    HypothesisStatus.REJECTED: frozenset(),
}

_HYPOTHESIS_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,80}$")
_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
_METRIC_OPERATORS = {">=", ">", "<=", "<", "=="}


def _required(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise HypothesisEvidenceError(f"{field_name} 不能为空")
    return normalized


def _status(value: HypothesisStatus | str) -> HypothesisStatus:
    if isinstance(value, HypothesisStatus):
        return value
    try:
        return HypothesisStatus(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in HypothesisStatus)
        raise HypothesisTransitionError(f"未知假设状态 {value!r}；允许：{allowed}") from exc


@dataclass(frozen=True, slots=True)
class HypothesisMetric:
    """一个预注册指标阈值。"""

    name: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        name = _required(self.name, "指标名")
        operator = str(self.operator).strip()
        if operator not in _METRIC_OPERATORS:
            raise HypothesisEvidenceError("指标比较符必须是 >=、>、<=、< 或 ==")
        threshold = float(self.threshold)
        if not math.isfinite(threshold):
            raise HypothesisEvidenceError("指标阈值必须是有限数值")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "threshold", threshold)

    def accepts(self, value: float) -> bool:
        """判断一个可核验观测值是否满足预注册阈值。"""
        observed = float(value)
        if not math.isfinite(observed):
            return False
        if self.operator == ">=":
            return observed >= self.threshold
        if self.operator == ">":
            return observed > self.threshold
        if self.operator == "<=":
            return observed <= self.threshold
        if self.operator == "<":
            return observed < self.threshold
        return observed == self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "operator": self.operator, "threshold": self.threshold}


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """与一个不可变研究 run 绑定的证据回执。"""

    run_id: str
    artifact_sha256: str
    summary: str
    observed_metrics: Mapping[str, float] = field(default_factory=dict)
    as_of: str = ""
    hypothesis_id: str = ""
    hypothesis_revision: int | None = None

    def __post_init__(self) -> None:
        run_id = _required(self.run_id, "run_id")
        artifact_sha256 = str(self.artifact_sha256).strip()
        if not _SHA256.fullmatch(artifact_sha256):
            raise HypothesisEvidenceError("证据 artifact_sha256 必须是 SHA-256")
        summary = _required(self.summary, "证据摘要")
        metrics: dict[str, float] = {}
        for name, value in dict(self.observed_metrics).items():
            metric_name = _required(str(name), "观测指标名")
            observed = float(value)
            if not math.isfinite(observed):
                raise HypothesisEvidenceError(f"观测指标 {metric_name} 必须是有限数值")
            metrics[metric_name] = observed
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "artifact_sha256", artifact_sha256.lower())
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "observed_metrics", metrics)
        object.__setattr__(self, "as_of", str(self.as_of).strip())
        object.__setattr__(self, "hypothesis_id", str(self.hypothesis_id).strip())
        if self.hypothesis_revision is not None:
            object.__setattr__(self, "hypothesis_revision", int(self.hypothesis_revision))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_sha256": self.artifact_sha256,
            "summary": self.summary,
            "observed_metrics": dict(self.observed_metrics),
            "as_of": self.as_of,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_revision": self.hypothesis_revision,
        }


@dataclass(frozen=True, slots=True)
class HypothesisAuditEvent:
    """一条追加式领域审计事件。"""

    action: str
    actor: str
    occurred_at: str
    reason: str = ""
    from_status: str = ""
    to_status: str = ""
    evidence_run_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _required(self.action, "审计动作"))
        object.__setattr__(self, "actor", _required(self.actor, "操作者"))
        object.__setattr__(self, "occurred_at", _required(self.occurred_at, "审计时间"))
        object.__setattr__(self, "reason", str(self.reason).strip())
        object.__setattr__(self, "from_status", str(self.from_status).strip())
        object.__setattr__(self, "to_status", str(self.to_status).strip())
        object.__setattr__(
            self,
            "evidence_run_ids",
            tuple(dict.fromkeys(_required(item, "evidence run_id") for item in self.evidence_run_ids)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "actor": self.actor,
            "occurred_at": self.occurred_at,
            "reason": self.reason,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "evidence_run_ids": list(self.evidence_run_ids),
        }


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """带有预注册和审计历史的研究假设聚合。"""

    hypothesis_id: str
    title: str
    thesis: str
    strategy_revision: str
    metrics: tuple[HypothesisMetric, ...]
    failure_conditions: tuple[str, ...]
    status: HypothesisStatus = HypothesisStatus.EXPLORING
    run_ids: tuple[str, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    audit_log: tuple[HypothesisAuditEvent, ...] = ()
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        hypothesis_id = _required(self.hypothesis_id, "hypothesis_id")
        if not _HYPOTHESIS_ID.fullmatch(hypothesis_id):
            raise HypothesisEvidenceError("hypothesis_id 只能包含字母、数字、下划线和连字符")
        title = _required(self.title, "标题")
        thesis = _required(self.thesis, "论断")
        strategy_revision = _required(self.strategy_revision, "strategy_revision")
        metrics = tuple(self.metrics)
        if not metrics:
            raise HypothesisEvidenceError("假设必须预注册至少一个指标阈值")
        metric_names = [item.name for item in metrics]
        if len(metric_names) != len(set(metric_names)):
            raise HypothesisEvidenceError("预注册指标名不能重复")
        conditions = tuple(
            dict.fromkeys(_required(item, "失败条件") for item in self.failure_conditions)
        )
        if not conditions:
            raise HypothesisEvidenceError("假设必须声明至少一个失败条件")
        evidence_links = _dedupe_evidence(self.evidence_links)
        run_ids = tuple(dict.fromkeys((*self.run_ids, *(item.run_id for item in evidence_links))))
        revision = int(self.revision)
        if revision < 1:
            raise HypothesisEvidenceError("假设 revision 必须从 1 开始")
        object.__setattr__(self, "hypothesis_id", hypothesis_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "thesis", thesis)
        object.__setattr__(self, "strategy_revision", strategy_revision)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "failure_conditions", conditions)
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "run_ids", run_ids)
        object.__setattr__(self, "evidence_links", evidence_links)
        object.__setattr__(self, "audit_log", tuple(self.audit_log))
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "created_at", str(self.created_at or _now()))
        object.__setattr__(self, "updated_at", str(self.updated_at or self.created_at or _now()))

    @classmethod
    def create(
        cls,
        *,
        hypothesis_id: str,
        title: str,
        thesis: str,
        strategy_revision: str,
        metrics: tuple[HypothesisMetric, ...],
        failure_conditions: tuple[str, ...],
        actor: str,
        occurred_at: str | None = None,
    ) -> Hypothesis:
        """创建处于 exploring 的预注册假设。"""
        timestamp = occurred_at or _now()
        event = HypothesisAuditEvent(
            action="created",
            actor=actor,
            occurred_at=timestamp,
            to_status=HypothesisStatus.EXPLORING.value,
        )
        return cls(
            hypothesis_id=hypothesis_id,
            title=title,
            thesis=thesis,
            strategy_revision=strategy_revision,
            metrics=metrics,
            failure_conditions=failure_conditions,
            audit_log=(event,),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def attach_evidence(
        self,
        evidence: EvidenceLink,
        *,
        actor: str,
        occurred_at: str | None = None,
    ) -> Hypothesis:
        """追加与 run/artifact 绑定的审计证据。"""
        links = _dedupe_evidence((*self.evidence_links, evidence))
        if links == self.evidence_links:
            return self
        timestamp = occurred_at or _now()
        event = HypothesisAuditEvent(
            action="evidence_attached",
            actor=actor,
            occurred_at=timestamp,
            evidence_run_ids=(evidence.run_id,),
        )
        return self._changed(
            evidence_links=links,
            run_ids=tuple(dict.fromkeys((*self.run_ids, evidence.run_id))),
            audit_log=(*self.audit_log, event),
            updated_at=timestamp,
        )

    def transition(
        self,
        target: HypothesisStatus | str,
        *,
        actor: str,
        reason: str,
        evidence: tuple[EvidenceLink, ...] = (),
        occurred_at: str | None = None,
    ) -> Hypothesis:
        """执行合法状态迁移，并将依据写入不可变审计历史。"""
        target_status = _status(target)
        if target_status not in HYPOTHESIS_TRANSITIONS[self.status]:
            raise HypothesisTransitionError(
                f"不能从 {self.status.value} 转换到 {target_status.value}"
            )
        normalized_reason = _required(reason, "状态迁移原因")
        all_evidence = _dedupe_evidence((*self.evidence_links, *evidence))
        if target_status is HypothesisStatus.VALIDATED:
            # 已附着的测试资料可包含失败实验；进入 validated 时必须明确给出
            # 本次作为结论依据的 run，避免从历史链接中挑选有利指标而不留痕。
            self._validate_registered_metrics(tuple(evidence))

        timestamp = occurred_at or _now()
        event = HypothesisAuditEvent(
            action="transitioned",
            actor=actor,
            occurred_at=timestamp,
            reason=normalized_reason,
            from_status=self.status.value,
            to_status=target_status.value,
            evidence_run_ids=tuple(item.run_id for item in evidence),
        )
        return self._changed(
            status=target_status,
            evidence_links=all_evidence,
            run_ids=tuple(dict.fromkeys((*self.run_ids, *(item.run_id for item in all_evidence)))),
            audit_log=(*self.audit_log, event),
            updated_at=timestamp,
        )

    def _validate_registered_metrics(self, evidence: tuple[EvidenceLink, ...]) -> None:
        if not evidence:
            raise HypothesisEvidenceError("进入 validated 必须关联可核验证据")
        missing: list[str] = []
        failed: list[str] = []
        for metric in self.metrics:
            values = [
                float(link.observed_metrics[metric.name])
                for link in evidence
                if metric.name in link.observed_metrics
            ]
            if not values:
                missing.append(metric.name)
            elif not all(metric.accepts(value) for value in values):
                failed.append(metric.name)
        if missing or failed:
            details: list[str] = []
            if missing:
                details.append(f"缺少指标：{', '.join(missing)}")
            if failed:
                details.append(f"未达阈值：{', '.join(failed)}")
            raise HypothesisEvidenceError("；".join(details))

    def _changed(self, **changes: Any) -> Hypothesis:
        return replace(self, revision=self.revision + 1, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "research-hypothesis-v1",
            "hypothesis_id": self.hypothesis_id,
            "title": self.title,
            "thesis": self.thesis,
            "strategy_revision": self.strategy_revision,
            "metrics": [item.to_dict() for item in self.metrics],
            "failure_conditions": list(self.failure_conditions),
            "status": self.status.value,
            "run_ids": list(self.run_ids),
            "evidence_links": [item.to_dict() for item in self.evidence_links],
            "audit_log": [item.to_dict() for item in self.audit_log],
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Hypothesis:
        """从 JSON 产物恢复领域对象，并重新验证所有不变量。"""
        metrics = tuple(
            HypothesisMetric(
                name=str(item.get("name") or ""),
                operator=str(item.get("operator") or ""),
                threshold=float(item.get("threshold")),
            )
            for item in raw.get("metrics", [])
            if isinstance(item, Mapping)
        )
        evidence = tuple(
            EvidenceLink(
                run_id=str(item.get("run_id") or ""),
                artifact_sha256=str(item.get("artifact_sha256") or ""),
                summary=str(item.get("summary") or ""),
                observed_metrics=dict(item.get("observed_metrics") or {}),
                as_of=str(item.get("as_of") or ""),
                hypothesis_id=str(item.get("hypothesis_id") or ""),
                hypothesis_revision=(int(item["hypothesis_revision"]) if item.get("hypothesis_revision") is not None else None),
            )
            for item in raw.get("evidence_links", [])
            if isinstance(item, Mapping)
        )
        audit_log = tuple(
            HypothesisAuditEvent(
                action=str(item.get("action") or ""),
                actor=str(item.get("actor") or ""),
                occurred_at=str(item.get("occurred_at") or ""),
                reason=str(item.get("reason") or ""),
                from_status=str(item.get("from_status") or ""),
                to_status=str(item.get("to_status") or ""),
                evidence_run_ids=tuple(str(value) for value in item.get("evidence_run_ids", [])),
            )
            for item in raw.get("audit_log", [])
            if isinstance(item, Mapping)
        )
        return cls(
            hypothesis_id=str(raw.get("hypothesis_id") or ""),
            title=str(raw.get("title") or ""),
            thesis=str(raw.get("thesis") or ""),
            strategy_revision=str(raw.get("strategy_revision") or ""),
            metrics=metrics,
            failure_conditions=tuple(str(value) for value in raw.get("failure_conditions", [])),
            status=_status(str(raw.get("status") or HypothesisStatus.EXPLORING.value)),
            run_ids=tuple(str(value) for value in raw.get("run_ids", [])),
            evidence_links=evidence,
            audit_log=audit_log,
            revision=int(raw.get("revision") or 1),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )


def _dedupe_evidence(values: tuple[EvidenceLink, ...] | list[EvidenceLink]) -> tuple[EvidenceLink, ...]:
    unique: dict[tuple[str, str], EvidenceLink] = {}
    for evidence in values:
        unique.setdefault((evidence.run_id, evidence.artifact_sha256), evidence)
    return tuple(unique.values())


__all__ = [
    "EvidenceLink",
    "HYPOTHESIS_TRANSITIONS",
    "Hypothesis",
    "HypothesisAuditEvent",
    "HypothesisConcurrencyError",
    "HypothesisError",
    "HypothesisEvidenceError",
    "HypothesisMetric",
    "HypothesisStatus",
    "HypothesisTransitionError",
]
