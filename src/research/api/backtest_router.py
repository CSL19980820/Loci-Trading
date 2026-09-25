"""研究回测的 HTTP 端点组：提交、查状态、读 run card / workflow / artifact、
发布与重放。

从 `router.py` 拆出来的理由不是行数，是这一组端点自带一份**进程级线程池**
（`_BACKTEST_EXECUTOR`）和围绕它的一整套 job 状态机；而 `router.py` 剩下的
目录 / 剖面 / 研究 run / 假设生命周期都是同步请求，两拨东西的失败模式与
并发约束完全不同。参考同目录 `factor_router.py`，它因为同样的理由更早拆了出去。

仍由 `build_research_router` `include_router` 进来，URL 集合与挂载方式不变；
`build_research_router` 的 store factory 形参也照原样透传，注入点没有变化。

**AST 守卫**：`tests/ai/test_tenant_threads.py::_GUARDED_FILES` 逐文件扫描
`x.submit(...)` / `threading.Thread(...)`。本文件持有线程池，必须留在那份清单里；
再拆分本文件时清单要跟着走，否则守卫出现盲区。
"""
from __future__ import annotations

from collections.abc import Callable
from src.shared.bounded_executor import BoundedExecutor, QueueFull
from src.research.infrastructure.backtest_jobs import DuplicateResearchJob
import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.backtest import TrainOOSSplit
from src.market import MarketStore
from src.research.api.backtest_models import (
    ResearchBacktestPublicationRequest,
    ResearchBacktestRequest,
)
from src.research.api.write_access import require_configured_research_write_access
from src.research.application import (
    ResearchBacktestError,
    ResearchPublicationError,
    ResearchReplayError,
    manifest_sha256,
    publish_research_backtest,
    replay_research_backtest,
    run_research_backtest,
)
from src.research.domain import validate_relative_artifact_path
from src.research.infrastructure import (
    HypothesisStore,
    MembershipSnapshotStore,
    ResearchBacktestJobStore,
    ResearchRunCardStore,
    ResearchWorkflowStore,
    RunCardError,
    RunCardNotFoundError,
    WorkflowStorageError,
)

from src.strategy import StrategyError, get as get_strategy

#: 进程级单线程池；与 factor_router._FACTOR_EXECUTOR 同一条纪律：
#: **工作线程的 Context 停在线程创建那一刻**，投递必须走 submit_with_tenant。
#: execute_job 里的 ResearchBacktestJobStore / RunCardStore 都挂在
#: research_runs_dir()（租户私有目录）下，裸 .submit(...) 会把 B 的回测产物
#: 与 job 状态写进管理员目录，B 只会看到一条永远 queued 的任务。
_BACKTEST_EXECUTOR = BoundedExecutor("research-backtest")


def build_research_backtest_router(
    *,
    write_dependency: Callable[..., Any] | None = None,
    market_db: str | None = None,
    market_store_factory: Callable[[str | None], Any] | None = None,
    run_card_store_factory: Callable[[], ResearchRunCardStore] | None = None,
    workflow_store_factory: Callable[[], ResearchWorkflowStore] | None = None,
    hypothesis_store_factory: Callable[[], HypothesisStore] | None = None,
    backtest_job_store_factory: Callable[[], ResearchBacktestJobStore] | None = None,
    membership_store_factory: Callable[[], MembershipSnapshotStore] | None = None,
) -> APIRouter:
    """构造回测端点组；写接口必须由组合根注入的权限依赖保护。"""
    router = APIRouter()
    write_guard = Depends(write_dependency or require_configured_research_write_access)

    def _market() -> Any:
        factory = market_store_factory or MarketStore
        return factory(market_db)

    def _cards() -> ResearchRunCardStore:
        return run_card_store_factory() if run_card_store_factory else ResearchRunCardStore()

    def _workflows() -> ResearchWorkflowStore:
        return workflow_store_factory() if workflow_store_factory else ResearchWorkflowStore(_cards().root)

    def _hypotheses() -> HypothesisStore:
        return hypothesis_store_factory() if hypothesis_store_factory else HypothesisStore()

    def _jobs() -> ResearchBacktestJobStore:
        return backtest_job_store_factory() if backtest_job_store_factory else ResearchBacktestJobStore()

    def _memberships() -> MembershipSnapshotStore:
        return membership_store_factory() if membership_store_factory else MembershipSnapshotStore()

    if backtest_job_store_factory:
        _jobs().recover_interrupted()

    def _execute_backtest(request: ResearchBacktestRequest) -> str:
        split = TrainOOSSplit(**request.split.model_dump()) if request.split else None
        from src.backtest import resolve_backtest_config
        from src.strategy import StrategyError, get as get_strategy

        try:
            engine = get_strategy(request.strategy)
            template = getattr(engine, "backtest_config", None) or {}
            config = resolve_backtest_config(engine, request.backtest_config.model_dump(
                include=request.backtest_config.model_fields_set,
            ))
        except (StrategyError, ValueError) as exc:
            raise ResearchBacktestError(str(exc)) from exc
        positions = request.max_positions if "max_positions" in request.model_fields_set else template.get("max_positions", request.max_positions)
        account_model = request.account_model if "account_model" in request.model_fields_set else template.get("account_model", request.account_model)
        if request.hypothesis_id is not None:
            hypothesis = _hypotheses().get(request.hypothesis_id)
            if hypothesis is None:
                raise ResearchBacktestError(f"假设不存在：{request.hypothesis_id}")
            if request.hypothesis_revision != hypothesis.revision:
                raise ResearchBacktestError("hypothesis revision 已变化或未提供")
        with _market() as store:
            outcome = run_research_backtest(
                store, strategy=request.strategy, start=request.start, end=request.end,
                params=request.params, backtest_config=config, universe=request.universe,
                split=split, hypothesis_id=request.hypothesis_id,
                hypothesis_revision=request.hypothesis_revision,
                initial_capital=request.initial_capital, max_positions=positions,
                lot_size=request.lot_size, account_model=account_model,
                seed=request.seed, random_repeats=request.random_repeats,
                bootstrap_iterations=request.bootstrap_iterations,
                monte_carlo_iterations=request.monte_carlo_iterations,
                 historical_universe_id=request.historical_universe_id, strict_pit=request.strict_pit,
                 membership_store=_memberships(),
                 run_card_store=_cards(), workflow_store=_workflows(),
            )
        # 后台完成只需要ID，不复制run card里的全量冻结来源详情。
        return str(outcome.run_card.run_id)

    def _submit_backtest_job(request: ResearchBacktestRequest) -> dict[str, Any]:
        try:
            with _BACKTEST_EXECUTOR.reserve() as submit:
                job_store = _jobs()
                job = job_store.create(request.model_dump(mode="json"))

                def execute_job() -> None:
                    try:
                        job_store.update(job["id"], status="running")
                        run_id = _execute_backtest(request)
                        job_store.update(
                            job["id"],
                            status="completed",
                            run_id=run_id,
                        )
                    except Exception as exc:
                        job_store.update(
                            job["id"], status="failed", error=f"{type(exc).__name__}: {exc}"
                        )

                try:
                    # 见 _BACKTEST_EXECUTOR 上方注释；别改回 _BACKTEST_EXECUTOR.submit(...)。
                    submit(execute_job, on_cancel=lambda: job_store.update(job["id"], status="failed", error="interrupted: 服务关闭取消排队任务"))
                except Exception as exc:
                    job_store.update(job["id"], status="failed", error=f"submit_failed: {exc}")
                    raise ResearchBacktestError("研究回测后台任务提交失败") from exc
                return job
        except DuplicateResearchJob as exc:
            raise HTTPException(409, str(exc)) from exc
        except QueueFull as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "5"}) from exc


    def _current_market_revision() -> str | None:
        try:
            with _market() as store:
                value = store.market_revision()
        except (AttributeError, OSError, ValueError):
            return None
        return str(value) if value else None

    def _current_strategy_revision(strategy_slug: str) -> str | None:
        try:
            return str(getattr(get_strategy(strategy_slug), "strategy_revision", "")) or None
        except StrategyError:
            return None

    def _card_response(card: Any) -> dict[str, Any]:
        digest = manifest_sha256(card)
        return {
            **card.to_dict(),
            "artifact_manifest_sha256": digest,
            "manifest_sha256": digest,
        }

    def _require_card(run_id: str) -> Any:
        try:
            stored = _cards()
            existing = stored.require(run_id)
            card = stored.require(
                run_id,
                current_strategy_revision=_current_strategy_revision(existing.strategy_slug),
                current_market_revision=_current_market_revision(),
            )
        except (RunCardNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RunCardError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return card

    @router.post("/api/research/backtest-runs", tags=["research"], status_code=202)
    def create_backtest_run(
        request: ResearchBacktestRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            return {"job": _submit_backtest_job(request)}
        except ResearchBacktestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RunCardError, WorkflowStorageError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/research/backtest-jobs", tags=["research"], status_code=202)
    def submit_backtest_job(
        request: ResearchBacktestRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            return {"job": _submit_backtest_job(request)}
        except ResearchBacktestError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/api/research/backtest-jobs/{job_id}", tags=["research"])
    def get_backtest_job(job_id: str) -> dict[str, Any]:
        job = _jobs().get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"研究回测任务不存在：{job_id}")
        return {"job": job}

    @router.get("/api/research/backtest-runs", tags=["research"])
    def list_backtest_runs() -> dict[str, Any]:
        try:
            cards = _cards()
            market_revision = _current_market_revision()
            items = [
                _card_response(cards.require(
                    card.run_id,
                    current_strategy_revision=_current_strategy_revision(card.strategy_slug),
                    current_market_revision=market_revision,
                ))
                for card in cards.list()
            ]
            return {"items": items, "total": len(items)}
        except RunCardError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/api/research/backtest-runs/{run_id}", tags=["research"])
    def get_backtest_run(run_id: str) -> dict[str, Any]:
        return _card_response(_require_card(run_id))

    @router.get("/api/research/backtest-runs/{run_id}/workflow", tags=["research"])
    def get_backtest_workflow(run_id: str) -> dict[str, Any]:
        _require_card(run_id)
        try:
            workflow = _workflows().load(run_id)
        except (WorkflowStorageError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if workflow is None:
            raise HTTPException(status_code=404, detail=f"找不到研究工作流：{run_id}")
        return workflow.to_dict()

    @router.post("/api/research/backtest-runs/{run_id}/publish", tags=["research"])
    def publish_backtest_run(
        run_id: str,
        request: ResearchBacktestPublicationRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            outcome = publish_research_backtest(
                run_id,
                reviewer=request.reviewer,
                reason=request.reason,
                manifest_digest=request.manifest_sha256,
                run_card_store=_cards(),
                workflow_store=_workflows(),
            )
            outcome["run_card"] = _card_response(_cards().require(run_id))
            return outcome
        except ResearchPublicationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RunCardError, WorkflowStorageError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/research/backtest-runs/{run_id}/replay", tags=["research"])
    def replay_backtest_run(run_id: str, _write: None = write_guard) -> Response:
        try:
            with _market() as store:
                replay = replay_research_backtest(store, run_id, run_card_store=_cards(),
                                                  include_execution_details=False)
            receipt = replay["receipt"]
            del replay
            card = _cards().require(run_id)
            workflow = _workflows().load(run_id)
            from src.research.api.replay_response import replay_json_response

            return replay_json_response(
                root=_cards().root, run_id=run_id, run_card=_card_response(card),
                workflow=workflow.to_dict() if workflow else {}, receipt=receipt,
            )
        except ResearchReplayError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RunCardError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/research/backtest-runs/{run_id}/artifact", tags=["research"])
    def get_backtest_artifact(
        run_id: str,
        path: str = Query(min_length=1, max_length=240),
    ) -> Response:
        card = _require_card(run_id)
        try:
            relative_path = validate_relative_artifact_path(path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        entry = next((item for item in card.artifact_manifest if item.path == relative_path), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"artifact 不存在：{relative_path}")
        root = Path(_cards().root).resolve()
        target = (root / card.run_id / relative_path).resolve()
        if root not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail=f"artifact 不存在：{relative_path}")
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"artifact 读取失败：{relative_path}") from exc
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != entry.sha256:
            raise HTTPException(status_code=409, detail=f"artifact 完整性校验失败：{relative_path}")
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{Path(relative_path).name}"',
                "X-Research-Artifact-SHA256": entry.sha256,
            },
        )

    return router


__all__ = ["build_research_backtest_router"]
