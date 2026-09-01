"""研究工作台 HTTP 接口。"""
from __future__ import annotations
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.market import MarketStore
from src.research.application import (
    ResearchNotFoundError,
    ResearchRunError,
    build_research_catalog,
    build_research_profile,
    create_research_run,
    read_research_run,
    resume_research_run,
)
from src.research.api.backtest_router import build_research_backtest_router
from src.research.api.write_access import require_configured_research_write_access
from src.research.domain.hypothesis import (
    EvidenceLink,
    Hypothesis,
    HypothesisConcurrencyError,
    HypothesisError,
    HypothesisEvidenceError,
    HypothesisMetric,
    HypothesisStatus,
    HypothesisTransitionError,
)
from src.research.infrastructure import (
    HypothesisStorageError,
    HypothesisStore,
    MembershipSnapshotStore,
    ResearchArtifactStore,
    ResearchRunCardStore,
    ResearchWorkflowStore,
    ResearchBacktestJobStore,
    RunCardError,
)


class ResearchRunRequest(BaseModel):
    """显式归档研究 run 的输入；严禁携带外部来源或任意参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=6, max_length=8)
    budget: Literal["lite", "standard", "deep"] = "standard"
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

class HypothesisMetricRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    operator: Literal[">=", ">", "<=", "<", "=="]
    threshold: float

class EvidenceLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    run_id: str = Field(min_length=3, max_length=64)
    artifact_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    summary: str = Field(min_length=1, max_length=2_000)
    observed_metrics: dict[str, float] = Field(default_factory=dict)
    as_of: str = Field(default="", max_length=32)
    hypothesis_id: str | None = Field(default=None, min_length=3, max_length=81)
    hypothesis_revision: int | None = Field(default=None, ge=1)

class CreateHypothesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    hypothesis_id: str = Field(min_length=3, max_length=81)
    title: str = Field(min_length=1, max_length=200)
    thesis: str = Field(min_length=1, max_length=4_000)
    strategy_revision: str = Field(min_length=1, max_length=256)
    metrics: list[HypothesisMetricRequest] = Field(min_length=1, max_length=32)
    failure_conditions: list[str] = Field(min_length=1, max_length=32)
    actor: str = Field(min_length=1, max_length=128)

class HypothesisTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target: Literal["testing", "validated", "rejected", "monitoring"]
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2_000)
    evidence: list[EvidenceLinkRequest] = Field(default_factory=list, max_length=64)
    expected_revision: int = Field(ge=1)

class HumanReviewRequest(BaseModel):
    """人工复核只允许作出通过或否决结论，并要求带上审计依据。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["validated", "rejected"]
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2_000)
    evidence: list[EvidenceLinkRequest] = Field(default_factory=list, max_length=64)
    expected_revision: int = Field(ge=1)

def build_research_router(
    *,
    write_dependency: Callable[..., Any] | None = None,
    market_db: str | None = None,
    market_store_factory: Callable[[str | None], Any] | None = None,
    artifact_store_factory: Callable[[], ResearchArtifactStore] | None = None,
    run_card_store_factory: Callable[[], ResearchRunCardStore] | None = None,
    workflow_store_factory: Callable[[], ResearchWorkflowStore] | None = None,
    hypothesis_store_factory: Callable[[], HypothesisStore] | None = None,
    backtest_job_store_factory: Callable[[], ResearchBacktestJobStore] | None = None,
    membership_store_factory: Callable[[], MembershipSnapshotStore] | None = None,
) -> APIRouter:
    """构造研究路由；写接口必须由组合根注入的权限依赖保护。"""
    router = APIRouter()
    write_guard = Depends(write_dependency or require_configured_research_write_access)

    def _market() -> Any:
        factory = market_store_factory or MarketStore
        return factory(market_db)

    def _artifacts() -> ResearchArtifactStore:
        return artifact_store_factory() if artifact_store_factory else ResearchArtifactStore()

    def _cards() -> ResearchRunCardStore:
        return run_card_store_factory() if run_card_store_factory else ResearchRunCardStore()

    def _hypotheses() -> HypothesisStore:
        return hypothesis_store_factory() if hypothesis_store_factory else HypothesisStore()

    router.include_router(
        build_research_backtest_router(
            write_dependency=write_dependency,
            market_db=market_db,
            market_store_factory=market_store_factory,
            run_card_store_factory=run_card_store_factory,
            workflow_store_factory=workflow_store_factory,
            hypothesis_store_factory=hypothesis_store_factory,
            backtest_job_store_factory=backtest_job_store_factory,
            membership_store_factory=membership_store_factory,
        )
    )

    def _run_error(exc: ResearchRunError) -> HTTPException:
        status = 404 if str(exc).startswith("找不到") else 409
        return HTTPException(status_code=status, detail=str(exc))

    def _evidence(
        values: list[EvidenceLinkRequest], *, hypothesis_id: str, hypothesis_revision: int
    ) -> tuple[EvidenceLink, ...]:
        links: list[EvidenceLink] = []
        for item in values:
            raw = item.model_dump()
            bound_id = raw.get("hypothesis_id") or hypothesis_id
            bound_revision = raw.get("hypothesis_revision") or hypothesis_revision
            if bound_id != hypothesis_id or bound_revision != hypothesis_revision:
                raise HypothesisEvidenceError("证据必须绑定当前 hypothesis id 与 revision")
            card = _cards().require(str(raw["run_id"]))
            if card.status != "completed" or card.validation.get("status") != "passed":
                raise HypothesisEvidenceError("证据 run 必须 completed 且 validation passed")
            if card.hypothesis_id != hypothesis_id or card.hypothesis_revision != hypothesis_revision:
                raise HypothesisEvidenceError("证据 run 未绑定当前 hypothesis revision")
            digest = str(raw["artifact_sha256"]).lower()
            if not any(entry.sha256 == digest for entry in card.artifact_manifest):
                raise HypothesisEvidenceError("证据 artifact hash 不在 run manifest 中")
            observed = dict(raw.get("observed_metrics") or {})
            for name, value in observed.items():
                actual = card.metrics.get(name)
                if actual is None or float(actual) != float(value):
                    raise HypothesisEvidenceError(f"证据指标与 run card 不一致：{name}")
            raw["hypothesis_id"] = bound_id
            raw["hypothesis_revision"] = bound_revision
            links.append(EvidenceLink(**raw))
        return tuple(links)

    def _transition_hypothesis(
        hypothesis_id: str,
        *,
        target: str,
        actor: str,
        reason: str,
        evidence: list[EvidenceLinkRequest],
        expected_revision: int,
    ) -> dict[str, Any]:
        store = _hypotheses()
        try:
            current = store.get(hypothesis_id)
            if current is None:
                raise HTTPException(status_code=404, detail=f"假设不存在：{hypothesis_id}")
            if current.revision != expected_revision:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"假设 {hypothesis_id} 已更新：期望 revision "
                        f"{expected_revision}，实际 {current.revision}"
                    ),
                )
            # 客户端重试同一决策时不重复追加审计事件；不同目标必须重新读取最新 revision。
            if current.status.value == target:
                return {"hypothesis": current.to_dict(), "reused": True}
            updated = store.transition(
                hypothesis_id,
                target,
                actor=actor,
                reason=reason,
                evidence=_evidence(
                    evidence,
                    hypothesis_id=current.hypothesis_id,
                    hypothesis_revision=current.revision,
                ),
            )
            return {"hypothesis": updated.to_dict(), "reused": False}
        except HTTPException:
            raise
        except (HypothesisConcurrencyError, HypothesisTransitionError, RunCardError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (HypothesisError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HypothesisStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/api/research/catalog", tags=["research"])
    def research_catalog() -> dict[str, Any]:
        return build_research_catalog()

    @router.get("/api/research/profile/{code}", tags=["research"])
    def research_profile(
        code: str,
        budget: Literal["lite", "standard", "deep"] = Query(default="standard"),
        as_of: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict[str, Any]:
        try:
            with _market() as store:
                return build_research_profile(store, code, budget=budget, as_of=as_of).to_dict()
        except ResearchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/research/runs", tags=["research"])
    def create_run(
        request: ResearchRunRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            with _market() as store:
                return create_research_run(
                    store,
                    request.code,
                    budget=request.budget,
                    as_of=request.as_of,
                    artifact_store=_artifacts(),
                )
        except ResearchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ResearchRunError as exc:
            raise _run_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/research/runs/{run_id}", tags=["research"])
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            with _market() as store:
                return read_research_run(store, run_id, artifact_store=_artifacts())
        except ResearchRunError as exc:
            raise _run_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/research/runs/{run_id}/resume", tags=["research"])
    def resume_run(
        run_id: str,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            with _market() as store:
                return resume_research_run(store, run_id, artifact_store=_artifacts())
        except ResearchRunError as exc:
            raise _run_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/research/hypotheses", tags=["research"])
    def list_hypotheses(
        status: Literal["exploring", "testing", "validated", "rejected", "monitoring"] | None = None,
    ) -> dict[str, Any]:
        try:
            items = _hypotheses().list(status=status)
            return {"items": [item.to_dict() for item in items], "total": len(items)}
        except (HypothesisStorageError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/api/research/hypotheses", tags=["research"], status_code=201)
    def create_hypothesis(
        request: CreateHypothesisRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            hypothesis = Hypothesis.create(
                hypothesis_id=request.hypothesis_id,
                title=request.title,
                thesis=request.thesis,
                strategy_revision=request.strategy_revision,
                metrics=tuple(HypothesisMetric(**item.model_dump()) for item in request.metrics),
                failure_conditions=tuple(request.failure_conditions),
                actor=request.actor,
            )
            created = _hypotheses().create(hypothesis)
            return {"hypothesis": created.to_dict()}
        except HypothesisStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except HypothesisError as exc:
            status = 409 if "已存在" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.get("/api/research/hypotheses/{hypothesis_id}", tags=["research"])
    def get_hypothesis(hypothesis_id: str) -> dict[str, Any]:
        try:
            hypothesis = _hypotheses().get(hypothesis_id)
        except HypothesisStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if hypothesis is None:
            raise HTTPException(status_code=404, detail=f"假设不存在：{hypothesis_id}")
        return {"hypothesis": hypothesis.to_dict()}

    @router.post("/api/research/hypotheses/{hypothesis_id}/transition", tags=["research"])
    def transition_hypothesis(
        hypothesis_id: str,
        request: HypothesisTransitionRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        return _transition_hypothesis(
            hypothesis_id,
            target=request.target,
            actor=request.actor,
            reason=request.reason,
            evidence=request.evidence,
            expected_revision=request.expected_revision,
        )

    @router.post("/api/research/hypotheses/{hypothesis_id}/review", tags=["research"])
    def review_hypothesis(
        hypothesis_id: str,
        request: HumanReviewRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        return _transition_hypothesis(
            hypothesis_id,
            target=request.decision,
            actor=request.actor,
            reason=request.reason,
            evidence=request.evidence,
            expected_revision=request.expected_revision,
        )

    return router
