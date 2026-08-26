"""研究限界上下文：维度契约、证据质量和只读研究剖面。"""
from src.research.api import build_research_router
from src.research.application import build_research_catalog, build_research_profile
from src.research.domain import (
    DimensionResult,
    DimensionSpec,
    EvidenceRef,
    QualitySnapshot,
    ResearchProfile,
    ReviewIssue,
    get_dimension_spec,
    list_dimension_specs,
)

__all__ = [
    "DimensionResult",
    "DimensionSpec",
    "EvidenceRef",
    "QualitySnapshot",
    "ResearchProfile",
    "ReviewIssue",
    "build_research_router",
    "build_research_catalog",
    "build_research_profile",
    "get_dimension_spec",
    "list_dimension_specs",
]
