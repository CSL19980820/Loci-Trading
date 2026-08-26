"""确定性研究 DAG 的纯领域状态机。"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from src.shared.clock import utc_now as _now
from enum import Enum
from typing import Any, Mapping


class WorkflowError(ValueError):
    """研究工作流领域错误。"""


class WorkflowTransitionError(WorkflowError):
    """工作流阶段转换不符合依赖或当前状态。"""


class ResearchStage(str, Enum):
    CAPTURE_INPUT = "capture_input"
    CALCULATE = "calculate"
    VALIDATE = "validate"
    RENDER = "render"
    REVIEW = "review"
    PUBLISH = "publish"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


STAGE_DEPENDENCIES: dict[ResearchStage, tuple[ResearchStage, ...]] = {
    ResearchStage.CAPTURE_INPUT: (),
    ResearchStage.CALCULATE: (ResearchStage.CAPTURE_INPUT,),
    ResearchStage.VALIDATE: (ResearchStage.CALCULATE,),
    ResearchStage.RENDER: (ResearchStage.VALIDATE,),
    ResearchStage.REVIEW: (ResearchStage.RENDER,),
    ResearchStage.PUBLISH: (ResearchStage.REVIEW,),
}


def _stage(value: ResearchStage | str) -> ResearchStage:
    if isinstance(value, ResearchStage):
        return value
    try:
        return ResearchStage(str(value))
    except ValueError as exc:
        raise WorkflowTransitionError(f"未知研究阶段：{value!r}") from exc


@dataclass(frozen=True, slots=True)
class StageState:
    """一个 DAG 阶段的当前状态及最后一次执行摘要。"""

    status: StageStatus = StageStatus.PENDING
    attempts: int = 0
    error: str = ""
    failure_code: str = ""
    blocked_by: tuple[str, ...] = ()
    artifact_sha256: str = ""

    def __post_init__(self) -> None:
        if int(self.attempts) < 0:
            raise WorkflowError("阶段 attempts 不能为负")
        status = self.status if isinstance(self.status, StageStatus) else StageStatus(str(self.status))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "attempts", int(self.attempts))
        object.__setattr__(self, "blocked_by", tuple(dict.fromkeys(self.blocked_by)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "attempts": self.attempts,
            "error": self.error,
            "failure_code": self.failure_code,
            "blocked_by": list(self.blocked_by),
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    """工作流的追加式阶段事件。"""

    action: str
    occurred_at: str
    stage: str = ""
    detail: str = ""
    attempt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "occurred_at": self.occurred_at,
            "stage": self.stage,
            "detail": self.detail,
            "attempt": self.attempt,
        }


@dataclass(frozen=True, slots=True)
class ResearchWorkflow:
    """研究流程的可序列化状态，领域层不执行 IO 或回测。"""

    workflow_id: str
    run_id: str
    max_retries: int = 0
    stages: Mapping[ResearchStage, StageState] = field(default_factory=dict)
    events: tuple[WorkflowEvent, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.workflow_id).strip() or not str(self.run_id).strip():
            raise WorkflowError("workflow_id 和 run_id 不能为空")
        if int(self.max_retries) < 0:
            raise WorkflowError("max_retries 不能为负")
        normalized = {
            stage: self.stages.get(stage, StageState())
            for stage in ResearchStage
        }
        object.__setattr__(self, "max_retries", int(self.max_retries))
        object.__setattr__(self, "stages", normalized)
        object.__setattr__(self, "events", tuple(self.events))

    @classmethod
    def create(
        cls,
        run_id: str,
        *,
        workflow_id: str | None = None,
        max_retries: int = 0,
        occurred_at: str | None = None,
    ) -> ResearchWorkflow:
        """创建初始 DAG，所有阶段均为 pending。"""
        timestamp = occurred_at or _now()
        resolved_id = workflow_id or f"WF-{run_id}"
        return cls(
            workflow_id=resolved_id,
            run_id=run_id,
            max_retries=max_retries,
            events=(WorkflowEvent("workflow_created", timestamp),),
        )

    @property
    def status(self) -> str:
        states = tuple(self.stages.values())
        if all(state.status is StageStatus.COMPLETED for state in states):
            return "completed"
        if any(state.status is StageStatus.FAILED for state in states):
            return "failed"
        if (
            self.stages[ResearchStage.RENDER].status is StageStatus.COMPLETED
            and self.stages[ResearchStage.REVIEW].status is StageStatus.PENDING
            and self.stages[ResearchStage.PUBLISH].status is StageStatus.PENDING
        ):
            return "awaiting_human_review"
        return "running"

    def ready_stages(self) -> tuple[ResearchStage, ...]:
        """返回满足全部依赖、可确定性执行的 pending 阶段。"""
        return tuple(
            stage
            for stage in ResearchStage
            if self.stages[stage].status is StageStatus.PENDING
            and all(
                self.stages[dependency].status is StageStatus.COMPLETED
                for dependency in STAGE_DEPENDENCIES[stage]
            )
        )

    def start_stage(
        self,
        stage: ResearchStage | str,
        *,
        occurred_at: str | None = None,
    ) -> ResearchWorkflow:
        """开始一个已满足依赖的阶段，并增加其尝试次数。"""
        resolved = _stage(stage)
        current = self.stages[resolved]
        if current.status is not StageStatus.PENDING:
            raise WorkflowTransitionError(f"阶段 {resolved.value} 当前不可启动")
        missing = [
            dependency.value
            for dependency in STAGE_DEPENDENCIES[resolved]
            if self.stages[dependency].status is not StageStatus.COMPLETED
        ]
        if missing:
            raise WorkflowTransitionError(
                f"阶段 {resolved.value} 的上游尚未完成：{', '.join(missing)}"
            )
        state = replace(
            current,
            status=StageStatus.RUNNING,
            attempts=current.attempts + 1,
            error="",
            failure_code="",
            blocked_by=(),
        )
        return self._with_stage(
            resolved,
            state,
            WorkflowEvent(
                "stage_started",
                occurred_at or _now(),
                stage=resolved.value,
                attempt=state.attempts,
            ),
        )

    def complete_stage(
        self,
        stage: ResearchStage | str,
        *,
        artifact_sha256: str = "",
        detail: str = "",
        occurred_at: str | None = None,
    ) -> ResearchWorkflow:
        """标记当前 running 阶段成功。"""
        resolved = _stage(stage)
        current = self.stages[resolved]
        if current.status is not StageStatus.RUNNING:
            raise WorkflowTransitionError(f"阶段 {resolved.value} 当前不可完成")
        state = replace(
            current,
            status=StageStatus.COMPLETED,
            error="",
            failure_code="",
            artifact_sha256=str(artifact_sha256).strip(),
        )
        return self._with_stage(
            resolved,
            state,
            WorkflowEvent(
                "stage_completed",
                occurred_at or _now(),
                stage=resolved.value,
                detail=str(detail).strip(),
                attempt=state.attempts,
            ),
        )

    def fail_stage(
        self,
        stage: ResearchStage | str,
        *,
        reason: str,
        failure_code: str = "execution_failed",
        retryable: bool = True,
        occurred_at: str | None = None,
    ) -> ResearchWorkflow:
        """记录失败；可重试失败回到 pending，否则阻断所有下游。"""
        resolved = _stage(stage)
        current = self.stages[resolved]
        if current.status is not StageStatus.RUNNING:
            raise WorkflowTransitionError(f"阶段 {resolved.value} 当前不可失败")
        detail = str(reason).strip() or "阶段执行失败"
        timestamp = occurred_at or _now()
        can_retry = retryable and current.attempts <= self.max_retries
        if can_retry:
            state = replace(
                current,
                status=StageStatus.PENDING,
                error=detail,
                failure_code=str(failure_code).strip() or "execution_failed",
            )
            return self._with_stage(
                resolved,
                state,
                WorkflowEvent(
                    "stage_retry_scheduled",
                    timestamp,
                    stage=resolved.value,
                    detail=detail,
                    attempt=current.attempts,
                ),
            )

        failed = replace(
            current,
            status=StageStatus.FAILED,
            error=detail,
            failure_code=str(failure_code).strip() or "execution_failed",
        )
        stages = dict(self.stages)
        stages[resolved] = failed
        events = [
            *self.events,
            WorkflowEvent(
                "stage_failed",
                timestamp,
                stage=resolved.value,
                detail=detail,
                attempt=current.attempts,
            ),
        ]
        for dependent in self._downstream(resolved):
            state = stages[dependent]
            if state.status is StageStatus.COMPLETED:
                continue
            stages[dependent] = replace(
                state,
                status=StageStatus.BLOCKED,
                blocked_by=(resolved.value,),
                error=f"上游 {resolved.value} 失败：{detail}",
                failure_code=failed.failure_code,
            )
            events.append(
                WorkflowEvent(
                    "stage_blocked",
                    timestamp,
                    stage=dependent.value,
                    detail=resolved.value,
                )
            )
        return replace(self, stages=stages, events=tuple(events))

    def resume_from(
        self,
        stage: ResearchStage | str,
        *,
        occurred_at: str | None = None,
    ) -> ResearchWorkflow:
        """显式重开失败根及其下游，已完成上游保持不变。"""
        resolved = _stage(stage)
        current = self.stages[resolved]
        if any(state.status is StageStatus.RUNNING for state in self.stages.values()):
            raise WorkflowTransitionError("存在运行中的阶段，不能恢复")
        if current.status not in {StageStatus.FAILED, StageStatus.BLOCKED}:
            raise WorkflowTransitionError(f"阶段 {resolved.value} 不是可恢复的失败根")
        unfinished_upstreams = [
            dependency.value
            for dependency in STAGE_DEPENDENCIES[resolved]
            if self.stages[dependency].status is not StageStatus.COMPLETED
        ]
        if unfinished_upstreams:
            raise WorkflowTransitionError(
                f"不能从 {resolved.value} 恢复；上游未完成：{', '.join(unfinished_upstreams)}"
            )

        stages = dict(self.stages)
        for affected in (resolved, *self._downstream(resolved)):
            stages[affected] = StageState(
                status=StageStatus.PENDING,
                attempts=0,
                artifact_sha256="",
            )
        timestamp = occurred_at or _now()
        return replace(
            self,
            stages=stages,
            events=(*self.events, WorkflowEvent("workflow_resumed", timestamp, stage=resolved.value)),
        )

    def _downstream(self, root: ResearchStage) -> tuple[ResearchStage, ...]:
        descendants: list[ResearchStage] = []
        frontier = [root]
        while frontier:
            parent = frontier.pop(0)
            for stage, dependencies in STAGE_DEPENDENCIES.items():
                if parent in dependencies and stage not in descendants:
                    descendants.append(stage)
                    frontier.append(stage)
        return tuple(descendants)

    def _with_stage(
        self,
        stage: ResearchStage,
        state: StageState,
        event: WorkflowEvent,
    ) -> ResearchWorkflow:
        stages = dict(self.stages)
        stages[stage] = state
        return replace(self, stages=stages, events=(*self.events, event))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "research-workflow-v1",
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "max_retries": self.max_retries,
            "status": self.status,
            "stages": {stage.value: state.to_dict() for stage, state in self.stages.items()},
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ResearchWorkflow:
        stages: dict[ResearchStage, StageState] = {}
        raw_stages = raw.get("stages")
        if isinstance(raw_stages, Mapping):
            for name, body in raw_stages.items():
                if not isinstance(body, Mapping):
                    continue
                stage = _stage(str(name))
                stages[stage] = StageState(
                    status=StageStatus(str(body.get("status") or "pending")),
                    attempts=int(body.get("attempts") or 0),
                    error=str(body.get("error") or ""),
                    failure_code=str(body.get("failure_code") or ""),
                    blocked_by=tuple(str(item) for item in body.get("blocked_by", [])),
                    artifact_sha256=str(body.get("artifact_sha256") or ""),
                )
        events = tuple(
            WorkflowEvent(
                action=str(item.get("action") or ""),
                occurred_at=str(item.get("occurred_at") or ""),
                stage=str(item.get("stage") or ""),
                detail=str(item.get("detail") or ""),
                attempt=int(item.get("attempt") or 0),
            )
            for item in raw.get("events", [])
            if isinstance(item, Mapping)
        )
        return cls(
            workflow_id=str(raw.get("workflow_id") or ""),
            run_id=str(raw.get("run_id") or ""),
            max_retries=int(raw.get("max_retries") or 0),
            stages=stages,
            events=events,
        )


__all__ = [
    "ResearchStage",
    "ResearchWorkflow",
    "STAGE_DEPENDENCIES",
    "StageState",
    "StageStatus",
    "WorkflowError",
    "WorkflowEvent",
    "WorkflowTransitionError",
]
