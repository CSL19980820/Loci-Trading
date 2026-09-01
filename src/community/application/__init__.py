"""社区用例层：编排 domain 规则与 infrastructure 读写。"""

from src.community.application.discovery import (
    list_mine,
    list_square,
    list_starred,
    popular_tags,
    user_profile,
)
from src.community.application.engagement import (
    add_comment,
    clone,
    delete_comment,
    feed,
    follow,
    list_comments,
    star,
    unfollow,
    unstar,
)
from src.community.application.leaderboard import (
    board_catalog,
    read_board,
    rebuild_all,
    rebuild_leaderboard,
    record_metrics,
)
from src.community.application.retention import purge_expired
from src.community.application.publishing import (
    clone_bundle,
    delist_strategy,
    detail,
    list_versions,
    preflight,
    publish_new_version,
    publish_strategy,
    relist_strategy,
    set_visibility,
    update_listing,
)

# 注意：**不要**在这里 re-export ``subscribe`` / ``unsubscribe`` 这两个函数名。
# 它们与同名子模块 ``src.community.application.subscribe`` 撞名；一旦 re-export，
# ``from src.community.application import subscribe`` 拿到的就是函数而不是模块，
# 调用方写 ``subscribe.subscribe(...)`` 会 AttributeError。要用函数请从子模块导入。
from src.community.application.subscribe import (
    list_subscriptions,
    publish_signals,
    pull_signals,
)

__all__ = [
    "add_comment",
    "board_catalog",
    "clone",
    "clone_bundle",
    "delete_comment",
    "delist_strategy",
    "detail",
    "feed",
    "follow",
    "list_comments",
    "list_mine",
    "list_square",
    "list_starred",
    "list_subscriptions",
    "list_versions",
    "popular_tags",
    "preflight",
    "publish_new_version",
    "publish_signals",
    "publish_strategy",
    "pull_signals",
    "purge_expired",
    "read_board",
    "rebuild_all",
    "rebuild_leaderboard",
    "record_metrics",
    "relist_strategy",
    "set_visibility",
    "star",
    "unfollow",
    "unstar",
    "update_listing",
    "user_profile",
]
