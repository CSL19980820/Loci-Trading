"""社区入站适配器。"""

from src.community.api.router import build_community_router
from src.community.api.social_router import build_community_social_router
from src.community.api.strategies_router import build_community_strategies_router

__all__ = [
    "build_community_router",
    "build_community_social_router",
    "build_community_strategies_router",
]
