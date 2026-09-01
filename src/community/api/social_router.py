"""社区社交路由：订阅 / 信号 / 榜单 / 动态 / 用户主页。

同 ``strategies_router``：本模块**不使用** ``from __future__ import annotations``。
"""

import logging
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Path, Query

from src.community.application import discovery, engagement, leaderboard, subscribe
from src.community.api.deps import (
    coerce_actor,
    domain_errors,
    require_actor,
    store_opener,
)
from src.community.api.schemas import (
    MetricsInput,
    RebuildBoardInput,
    SignalBroadcastInput,
    SubscribeInput,
)
from src.community.infrastructure.store import CommunityStore

logger = logging.getLogger(__name__)


def build_community_social_router(
    *,
    write_dependency: Callable[..., Any],
    auth_dependency: Callable[..., Any],
    community_db: str | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/community", tags=["community"])
    Store = Annotated[CommunityStore, Depends(store_opener(community_db))]
    WriteAccess = Annotated[None, Depends(write_dependency)]
    Auth = Annotated[Any, Depends(auth_dependency)]

    # ------------------------------------------------------------ 订阅
    @router.post("/strategies/{publish_id}/subscribe", status_code=201)
    def subscribe_strategy(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: SubscribeInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        """订阅。**只推信号，不自动下单**（响应里的 notice 原样展示给用户）。"""
        with domain_errors():
            return subscribe.subscribe(
                store,
                publish_id,
                actor=require_actor(auth),
                notify_channels=list(payload.notify_channels),
            )

    @router.delete("/strategies/{publish_id}/subscribe")
    def unsubscribe_strategy(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return subscribe.unsubscribe(store, publish_id, actor=require_actor(auth))

    @router.get("/subscriptions")
    def my_subscriptions(store: Store, auth: Auth) -> list[dict[str, Any]]:
        with domain_errors():
            return subscribe.list_subscriptions(store, actor=require_actor(auth))

    @router.get("/subscriptions/signals")
    def subscription_signals(
        store: Store,
        auth: Auth,
        trade_date: str = Query(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        """拉我订阅的策略的当日信号；``trade_date`` 为空取各自最新一期。"""
        with domain_errors():
            return subscribe.pull_signals(
                store, actor=require_actor(auth), trade_date=trade_date, limit=limit
            )

    @router.post("/strategies/{publish_id}/signals", status_code=201)
    def broadcast_signals(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: SignalBroadcastInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        """作者发布当日信号快照（一天一条，重发覆盖）。仅作者本人 / admin。"""
        with domain_errors():
            return subscribe.publish_signals(
                store,
                publish_id,
                actor=require_actor(auth),
                payload=payload.payload,
                trade_date=payload.trade_date,
            )

    # ------------------------------------------------------------ 榜单
    @router.get("/leaderboard")
    def read_leaderboard(
        store: Store,
        board: str = Query(default="overall", pattern="^(overall|sharpe|return|rookie)$"),
        as_of: str = Query(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        """读榜（快照，不现算）。"""
        with domain_errors():
            return leaderboard.read_board(store, board=board, as_of=as_of, limit=limit)

    @router.get("/leaderboard/boards")
    def board_catalog() -> list[dict[str, Any]]:
        """各榜口径与门槛（为什么不用裸收益率排序，见 domain/scoring）。"""
        return leaderboard.board_catalog()

    @router.post("/leaderboard/rebuild")
    def rebuild_leaderboard(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: RebuildBoardInput,
    ) -> dict[str, Any]:
        """重算并落快照。仅 admin：榜单是全站可见的东西。"""
        actor = require_actor(auth)
        with domain_errors():
            if not actor.is_admin:
                from src.community.domain.models import PermissionDeniedError

                raise PermissionDeniedError("重算榜单仅限管理员")
            return leaderboard.rebuild_leaderboard(
                store, as_of=payload.as_of or None, board=payload.board, limit=payload.limit
            )

    @router.post("/strategies/{publish_id}/metrics", status_code=201)
    def record_metrics(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: MetricsInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        """写一期绩效切片（作者本人 / admin）。``score`` 由服务端按统一公式现算。"""
        values = payload.model_dump()
        as_of = values.pop("as_of", "")
        with domain_errors():
            return leaderboard.record_metrics(
                store, publish_id, actor=require_actor(auth), as_of=as_of or None, **values
            )

    # ------------------------------------------------------------ 动态与用户
    @router.get("/feed")
    def feed(
        store: Store,
        auth: Auth,
        scope: str = Query(default="all", pattern="^(all|following|mine)$"),
        limit: int = Query(default=50, ge=1, le=200),
        before: str = Query(default="", max_length=40),
    ) -> list[dict[str, Any]]:
        with domain_errors():
            return engagement.feed(
                store, actor=coerce_actor(auth), scope=scope, limit=limit, before=before
            )

    @router.get("/users/{user_id}/profile")
    def user_profile(
        store: Store,
        auth: Auth,
        user_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return discovery.user_profile(store, user_id, viewer=coerce_actor(auth))

    @router.post("/users/{user_id}/follow", status_code=201)
    def follow_user(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        user_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return engagement.follow(store, user_id, actor=require_actor(auth))

    @router.delete("/users/{user_id}/follow")
    def unfollow_user(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        user_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return engagement.unfollow(store, user_id, actor=require_actor(auth))

    @router.get("/tags")
    def tags(store: Store, limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
        with domain_errors():
            return discovery.popular_tags(store, limit=limit)

    return router
