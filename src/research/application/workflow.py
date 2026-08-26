"""研究 DAG 的确定性执行与恢复用例。

该模块只编排调用方提供的纯/外部阶段函数，不生成行情数字，也不负责写入
run card。调用方可将 ``ResearchWorkflow.to_dict()`` 作为阶段事件产物保存。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from src.research.domain.dag import (
    ResearchStage,
    ResearchWorkflow,
    WorkflowError,
)


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """阶段执行器返回的确定性结果。"""

    success: bool
    reason: str = ""
    retryable: bool = True
    failure_code: str = "execution_failed"
    artifact_sha256: str = ""

    @classmethod
    def succeeded(cls, *, artifact_sha256: str = "", detail: str = "") -> StageOutcome:
        return cls(
            success=True,
            reason=str(detail).strip(),
            retryable=False,
            failure_code="",
            artifact_sha256=str(artifact_sha256).strip(),
        )

    @classmethod
    def failed(
        cls,
        reason: str,
        *,
        retryable: bool = True,
        failure_code: str = "execution_failed",
    ) -> StageOutcome:
        return cls(
            success=False,
            reason=str(reason).strip() or "阶段执行失败",
            retryable=retryable,
            failure_code=str(failure_code).strip() or "execution_failed",
        )

    @classmethod
    def data_insufficient(cls, reason: str) -> StageOutcome:
        return cls.failed(reason, retryable=False, failure_code="data_insufficient")

    @classmethod
    def validation_failed(cls, reason: str) -> StageOutcome:
        return cls.failed(reason, retryable=False, failure_code="validation_failed")


StageHandler = Callable[[ResearchStage, ResearchWorkflow], StageOutcome]
WorkflowObserver = Callable[[ResearchWorkflow], None]


def execute_research_workflow(
    workflow: ResearchWorkflow,
    handlers: Mapping[ResearchStage, StageHandler],
    *,
    on_update: WorkflowObserver | None = None,
    stop_before_human_review: bool = False,
) -> ResearchWorkflow:
    """按固定拓扑顺序执行研究阶段，并对临时失败进行有限重试。

    上游数据不足、验证失败和缺失 handler 都是终态失败，会阻断所有下游；
    只有 handler 返回 ``retryable=True`` 且未超过 ``max_retries`` 时才重试。
    """
    current = workflow
    while current.status in {"running", "awaiting_human_review"}:
        if current.status == "awaiting_human_review" and stop_before_human_review:
            break
        ready = current.ready_stages()
        if not ready:
            raise WorkflowError("研究 DAG 没有可执行阶段，且不存在终态失败记录")
        stage = ready[0]
        current = current.start_stage(stage)
        if on_update is not None:
            on_update(current)
        handler = handlers.get(stage)
        if handler is None:
            outcome = StageOutcome.failed(
                f"缺少阶段 handler：{stage.value}",
                retryable=False,
                failure_code="handler_missing",
            )
        else:
            try:
                outcome = handler(stage, current)
                if not isinstance(outcome, StageOutcome):
                    outcome = StageOutcome.failed(
                        f"阶段 {stage.value} 返回了无效结果",
                        retryable=False,
                        failure_code="invalid_outcome",
                    )
            except Exception as exc:  # noqa: BLE001 - 阶段边界需转为可重试事件
                outcome = StageOutcome.failed(
                    f"阶段 {stage.value} 异常：{exc}",
                    retryable=True,
                    failure_code="handler_exception",
                )

        if outcome.success:
            current = current.complete_stage(
                stage,
                artifact_sha256=outcome.artifact_sha256,
                detail=outcome.reason,
            )
        else:
            current = current.fail_stage(
                stage,
                reason=outcome.reason,
                failure_code=outcome.failure_code,
                retryable=outcome.retryable,
            )
        if on_update is not None:
            on_update(current)
    return current


def resume_research_workflow(
    workflow: ResearchWorkflow,
    handlers: Mapping[ResearchStage, StageHandler],
    *,
    from_stage: ResearchStage | str,
    on_update: WorkflowObserver | None = None,
) -> ResearchWorkflow:
    """从指定失败根恢复，复用已完成上游并重新执行受影响阶段。"""
    resumed = workflow.resume_from(from_stage)
    if on_update is not None:
        on_update(resumed)
    return execute_research_workflow(resumed, handlers, on_update=on_update)


__all__ = [
    "StageHandler",
    "StageOutcome",
    "WorkflowObserver",
    "execute_research_workflow",
    "resume_research_workflow",
]
