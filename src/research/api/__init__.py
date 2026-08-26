from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from src.research.api.factor_router import build_research_factor_router
from src.research.api.temporal import build_research_temporal_router
from src.research.api.publication_router import build_research_publication_router
from src.research.api.router import build_research_router


def build_research_api_router(
    *,
    write_dependency: Callable[..., Any] | None = None,
    market_db: str | None = None,
) -> APIRouter:
    """Compose all research HTTP adapters at the bounded-context boundary."""
    router = APIRouter()
    router.include_router(
        build_research_router(
            write_dependency=write_dependency,
            market_db=market_db,
        )
    )
    router.include_router(
        build_research_temporal_router(write_dependency=write_dependency)
    )
    router.include_router(
        build_research_publication_router(write_dependency=write_dependency)
    )
    router.include_router(
        build_research_factor_router(
            write_dependency=write_dependency,
            market_db=market_db,
        )
    )
    return router

__all__ = [
    "build_research_api_router",
    "build_research_factor_router",
    "build_research_publication_router",
    "build_research_router",
    "build_research_temporal_router",
]
