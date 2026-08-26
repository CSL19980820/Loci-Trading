"""Asynchronous HTTP entrypoints for fixed research-only factor candidates."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.backtest import TrainOOSSplit
from src.market import MarketStore
from src.research.api.factor_models import Pth252FactorJobRequest
from src.research.api.write_access import require_configured_research_write_access
from src.research.application.factor_experiment import (
    Pth252FactorExperimentError,
    run_pth252_factor_experiment,
)
from src.research.infrastructure import (
    MembershipSnapshotStore,
    ResearchBacktestJobStore,
    ResearchRunCardStore,
    ResearchWorkflowStore,
)
from src.shared.paths import research_runs_dir


_FACTOR_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-factor")


def build_research_factor_router(
    *,
    write_dependency: Callable[..., Any] | None = None,
    market_db: str | None = None,
    market_store_factory: Callable[[str | None], Any] | None = None,
    run_card_store_factory: Callable[[], ResearchRunCardStore] | None = None,
    workflow_store_factory: Callable[[], ResearchWorkflowStore] | None = None,
    backtest_job_store_factory: Callable[[], ResearchBacktestJobStore] | None = None,
    membership_store_factory: Callable[[], MembershipSnapshotStore] | None = None,
) -> APIRouter:
    """Build factor endpoints without exposing arbitrary strategy parameters."""
    router = APIRouter()
    write_guard = Depends(write_dependency or require_configured_research_write_access)

    def _market() -> Any:
        factory = market_store_factory or MarketStore
        return factory(market_db)

    def _cards() -> ResearchRunCardStore:
        return run_card_store_factory() if run_card_store_factory else ResearchRunCardStore()

    def _workflows() -> ResearchWorkflowStore:
        return workflow_store_factory() if workflow_store_factory else ResearchWorkflowStore(_cards().root)

    def _memberships() -> MembershipSnapshotStore:
        return membership_store_factory() if membership_store_factory else MembershipSnapshotStore()

    def _jobs() -> ResearchBacktestJobStore:
        if backtest_job_store_factory:
            return backtest_job_store_factory()
        return ResearchBacktestJobStore(research_runs_dir() / "factor_jobs.json")

    _jobs().recover_interrupted()

    def _execute(request: Pth252FactorJobRequest) -> Any:
        split = TrainOOSSplit(**request.split.model_dump())
        with _market() as store:
            return run_pth252_factor_experiment(
                store,
                start=request.start,
                end=request.end,
                split=split,
                historical_universe_id=request.historical_universe_id,
                strict_pit=True,
                membership_store=_memberships(),
                run_card_store=_cards(),
                workflow_store=_workflows(),
            )

    def _submit(request: Pth252FactorJobRequest) -> dict[str, Any]:
        jobs = _jobs()
        job = jobs.create(request.model_dump(mode="json"))

        def execute_job() -> None:
            try:
                jobs.update(job["id"], status="running")
                outcome = _execute(request)
                jobs.update(
                    job["id"],
                    status="completed",
                    run_id=outcome.run_card.run_id,
                    error="",
                )
            except Pth252FactorExperimentError as exc:
                jobs.update(
                    job["id"],
                    status="failed",
                    run_id=exc.run_id,
                    error=str(exc),
                )
            except Exception as exc:
                jobs.update(
                    job["id"],
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )

        try:
            _FACTOR_EXECUTOR.submit(execute_job)
        except Exception as exc:
            jobs.update(job["id"], status="failed", error=f"submit_failed: {exc}")
            raise Pth252FactorExperimentError("PTH252 后台任务提交失败") from exc
        return job

    @router.post("/api/research/factor-jobs", tags=["research"], status_code=202)
    def submit_factor_job(
        request: Pth252FactorJobRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            return {"job": _submit(request)}
        except Pth252FactorExperimentError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/api/research/factor-jobs/{job_id}", tags=["research"])
    def get_factor_job(job_id: str) -> dict[str, Any]:
        job = _jobs().get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"PTH252 因子任务不存在：{job_id}")
        return {"job": job}

    return router


__all__ = ["build_research_factor_router"]
