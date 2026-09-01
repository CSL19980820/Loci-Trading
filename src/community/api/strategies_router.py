"""策略广场路由：列表 / 详情 / 版本 / 发布 / 收藏 / 克隆 / 评论。

注意：本模块**不使用** ``from __future__ import annotations``。工厂内
``Annotated[..., Depends(...)]`` 别名必须在路由 ``def`` 时求值成实体，否则 FastAPI
会把 ``store`` / 写依赖 / 当前用户误判成 query 参数（与 ledger 路由同一坑）。
"""

import logging
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from src.community.application import discovery, engagement, publishing
from src.community.api.deps import (
    coerce_actor,
    domain_errors,
    require_actor,
    store_opener,
)
from src.community.api.schemas import (
    CloneInput,
    CommentInput,
    ListingUpdateInput,
    PublishInput,
    VersionInput,
    VisibilityInput,
)
from src.community.infrastructure.store import CommunityStore

logger = logging.getLogger(__name__)


def build_community_strategies_router(
    *,
    write_dependency: Callable[..., Any],
    auth_dependency: Callable[..., Any],
    community_db: str | None = None,
) -> APIRouter:
    """装配广场路由。``auth_dependency`` 必须对匿名访客返回 None / 空上下文而不是抛 401，
    读接口要能匿名浏览；写接口自己用 ``require_actor`` 卡 401。
    """
    router = APIRouter(prefix="/api/community", tags=["community"])
    Store = Annotated[CommunityStore, Depends(store_opener(community_db))]
    WriteAccess = Annotated[None, Depends(write_dependency)]
    Auth = Annotated[Any, Depends(auth_dependency)]

    @router.get("/strategies")
    def square(
        store: Store,
        auth: Auth,
        sort: str = Query(default="hot", pattern="^(hot|new|score|stars)$"),
        kind: str = Query(default="", max_length=32),
        tag: str = Query(default="", max_length=32),
        keyword: str = Query(default="", max_length=64),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        """广场列表。匿名可读；登录后每条附带 ``starred``。"""
        with domain_errors():
            return discovery.list_square(
                store,
                sort=sort,
                kind=kind,
                tag=tag,
                keyword=keyword,
                page=page,
                page_size=page_size,
                viewer=coerce_actor(auth),
            )

    @router.get("/strategies/mine")
    def my_strategies(
        store: Store,
        auth: Auth,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        """我的发布（含私有 / 未列出 / 已下架）。"""
        with domain_errors():
            return discovery.list_mine(
                store, actor=require_actor(auth), page=page, page_size=page_size
            )

    @router.get("/me/stars")
    def my_stars(
        store: Store,
        auth: Auth,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        """我收藏的策略。条目与广场列表**同形状**（含 ``metrics``），前端复用卡片组件。

        未登录 401：收藏是私人清单，匿名访客没有「我的」可言。
        """
        with domain_errors():
            return discovery.list_starred(
                store, actor=require_actor(auth), limit=limit, offset=offset
            )
    @router.post("/strategies/preflight")
    def preflight(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: PublishInput,
    ) -> dict[str, Any]:
        """发布前预检：只跑上架清单，不写库。"""
        require_actor(auth)
        with domain_errors():
            return publishing.preflight(payload.model_dump())

    @router.post("/strategies", status_code=201)
    def publish(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: PublishInput,
    ) -> dict[str, Any]:
        with domain_errors():
            return publishing.publish_strategy(
                store, actor=require_actor(auth), payload=payload.model_dump()
            )

    @router.get("/strategies/{publish_id}")
    def strategy_detail(
        store: Store,
        auth: Auth,
        publish_id: str = Path(max_length=64),
        count_view: bool = Query(default=True),
    ) -> dict[str, Any]:
        with domain_errors():
            return publishing.detail(
                store, publish_id, actor=coerce_actor(auth), count_view=count_view
            )

    @router.patch("/strategies/{publish_id}")
    def update_listing(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: ListingUpdateInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        """改文案。版本内容冻结，改逻辑请发新版。"""
        with domain_errors():
            return publishing.update_listing(
                store,
                publish_id,
                actor=require_actor(auth),
                payload=payload.model_dump(exclude_none=True),
            )

    @router.get("/strategies/{publish_id}/versions")
    def strategy_versions(
        store: Store,
        auth: Auth,
        publish_id: str = Path(max_length=64),
    ) -> list[dict[str, Any]]:
        """版本列表（倒序）。非作者只看得到当前版正文。"""
        with domain_errors():
            return publishing.list_versions(store, publish_id, actor=coerce_actor(auth))

    @router.post("/strategies/{publish_id}/versions", status_code=201)
    def add_version(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: VersionInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        """发新版。旧版原地冻结，不可改不可删。"""
        with domain_errors():
            return publishing.publish_new_version(
                store,
                publish_id,
                actor=require_actor(auth),
                payload=payload.model_dump(exclude_none=True),
            )

    @router.post("/strategies/{publish_id}/delist")
    def delist(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return publishing.delist_strategy(store, publish_id, actor=require_actor(auth))

    @router.post("/strategies/{publish_id}/relist")
    def relist(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return publishing.relist_strategy(store, publish_id, actor=require_actor(auth))

    @router.post("/strategies/{publish_id}/visibility")
    def set_visibility(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: VisibilityInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return publishing.set_visibility(
                store, publish_id, actor=require_actor(auth), visibility=payload.visibility
            )

    @router.post("/strategies/{publish_id}/star")
    def star(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return engagement.star(store, publish_id, actor=require_actor(auth))

    @router.delete("/strategies/{publish_id}/star")
    def unstar(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return engagement.unstar(store, publish_id, actor=require_actor(auth))

    @router.post("/strategies/{publish_id}/clone")
    def clone(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        publish_id: str = Path(max_length=64),
        payload: CloneInput = Body(default=CloneInput()),
    ) -> dict[str, Any]:
        """克隆：返回可导入的 bundle + 计数 +1。

        **不写调用方的租户库**：社区只交付 payload，导入由客户端自己完成。
        """
        with domain_errors():
            return engagement.clone(
                store, publish_id, actor=require_actor(auth), version=payload.version
            )

    @router.get("/strategies/{publish_id}/comments")
    def list_comments(
        store: Store,
        auth: Auth,
        publish_id: str = Path(max_length=64),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with domain_errors():
            return engagement.list_comments(
                store, publish_id, actor=coerce_actor(auth), limit=limit
            )

    @router.post("/strategies/{publish_id}/comments", status_code=201)
    def add_comment(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        payload: CommentInput,
        publish_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        with domain_errors():
            return engagement.add_comment(
                store,
                publish_id,
                actor=require_actor(auth),
                body=payload.body,
                parent_id=payload.parent_id,
            )

    @router.delete("/comments/{comment_id}")
    def delete_comment(
        store: Store,
        auth: Auth,
        write: WriteAccess,
        comment_id: str = Path(max_length=64),
    ) -> dict[str, Any]:
        """软删：留占位行，楼层与父子关系不塌。"""
        with domain_errors():
            return engagement.delete_comment(store, comment_id, actor=require_actor(auth))

    return router
