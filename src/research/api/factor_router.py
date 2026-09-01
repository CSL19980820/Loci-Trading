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
from src.shared.tenancy import submit_with_tenant


#: 进程级单线程池：PTH252 实验一次跑满 CPU，串行是有意的。
#:
#: **它的工作线程是进程共享的，Context 停在线程创建那一刻**，与提交任务的请求
#: 无关。投递一律走 submit_with_tenant（见下方 _submit），别写 .submit(...)：
#: execute_job 里 _jobs() / _cards() / _workflows() 全部基于 research_runs_dir()，
#: 那是**租户私有**目录，丢了上下文就会把 B 的因子实验产物写进管理员的目录。
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
            # 见 _FACTOR_EXECUTOR 上方注释：这里改成裸 submit 会让 job 状态与 run card
            # 落到主租户的 research_runs 目录，发起人轮询到的永远是 queued。
            submit_with_tenant(_FACTOR_EXECUTOR, execute_job)
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
