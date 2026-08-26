"""人工研究结论的独立 HTTP 路由。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.research.api.backtest_models import ResearchBacktestRejectionRequest
from src.research.api.write_access import require_configured_research_write_access
from src.research.application import (
    ResearchPublicationError,
    manifest_sha256,
    reject_research_backtest,
)
from src.research.infrastructure import (
    ResearchRunCardStore,
    ResearchWorkflowStore,
    RunCardError,
    WorkflowStorageError,
)


def build_research_publication_router(
    *,
    write_dependency: Callable[..., Any] | None = None,
    run_card_store_factory: Callable[[], ResearchRunCardStore] | None = None,
    workflow_store_factory: Callable[[], ResearchWorkflowStore] | None = None,
) -> APIRouter:
    """构造人工否决接口；批准路径保留在既有研究路由以兼容 URL。"""
    router = APIRouter()
    write_guard = Depends(write_dependency or require_configured_research_write_access)

    def cards() -> ResearchRunCardStore:
        return run_card_store_factory() if run_card_store_factory else ResearchRunCardStore()

    def workflows() -> ResearchWorkflowStore:
        return workflow_store_factory() if workflow_store_factory else ResearchWorkflowStore(cards().root)

    def card_response(card: Any) -> dict[str, Any]:
        digest = manifest_sha256(card)
        return {
            **card.to_dict(),
            "artifact_manifest_sha256": digest,
            "manifest_sha256": digest,
        }

    @router.post("/api/research/backtest-runs/{run_id}/reject", tags=["research"])
    def reject_backtest_run(
        run_id: str,
        request: ResearchBacktestRejectionRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            outcome = reject_research_backtest(
                run_id,
                reviewer=request.reviewer,
                reason=request.reason,
                manifest_digest=request.manifest_sha256,
                run_card_store=cards(),
                workflow_store=workflows(),
            )
            outcome["run_card"] = card_response(cards().require(run_id))
            return outcome
        except ResearchPublicationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RunCardError, WorkflowStorageError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router


__all__ = ["build_research_publication_router"]
