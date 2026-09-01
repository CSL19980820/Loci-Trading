"""社区限界上下文：策略广场 / 排行榜 / 跟单订阅 / 互动 / 动态流。

外部只从这里导入（``from src.community import CommunityStore, build_community_router``）；
深引 ``src.community.infrastructure.*`` 会被 ``.importlinter`` 的
``protect-community-infra`` 拦下。
"""

from src.community.api import build_community_router
from src.community.application import (
    detail,
    list_square,
    list_subscriptions,
    publish_new_version,
    publish_signals,
    publish_strategy,
    pull_signals,
    purge_expired,
    read_board,
    rebuild_leaderboard,
    record_metrics,
)
from src.community.domain import (
    BOARDS,
    KINDS,
    SORTS,
    Actor,
    Comment,
    CommunityError,
    EquityPoint,
    FeedItem,
    PublishedStrategy,
    PublishedVersion,
    RuleViolation,
    StrategyMetrics,
    Subscription,
    check_publish_ready,
    checklist,
    compute_score,
    describe_boards,
    normalize_equity_curve,
    oos_discount,
    rank_entries,
)
from src.community.infrastructure.store import CommunityStore

__all__ = [
    "BOARDS",
    "KINDS",
    "SORTS",
    "Actor",
    "Comment",
    "CommunityError",
    "CommunityStore",
    "EquityPoint",
    "FeedItem",
    "PublishedStrategy",
    "PublishedVersion",
    "RuleViolation",
    "StrategyMetrics",
    "Subscription",
    "build_community_router",
    "check_publish_ready",
    "checklist",
    "compute_score",
    "describe_boards",
    "detail",
    "list_square",
    "list_subscriptions",
    "normalize_equity_curve",
    "oos_discount",
    "publish_new_version",
    "publish_signals",
    "publish_strategy",
    "pull_signals",
    "purge_expired",
    "rank_entries",
    "read_board",
    "rebuild_leaderboard",
    "record_metrics",
]
