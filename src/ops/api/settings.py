"""运维设置 HTTP 聚合入口。"""
from __future__ import annotations

from fastapi import APIRouter

from src.ops.api.data_sources import (
    LanePolicyPayload,
    LaneProbePayload,
    LaneSpeedtestPayload,
    _lane_code,
    _median_value,
    build_data_sources_router,
)
from src.ops.api.market_sync import build_market_sync_settings_router
from src.ops.api.notifications import build_notification_settings_router
from src.ops.api.paper_quant import build_paper_quant_router
from src.ops.api.share_pack import build_share_pack_router
from src.ops.api.system_settings import DesktopPrefsUpdate, build_system_settings_router


def build_ops_settings_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    scheduler_getter=None,
    setup_access_allowed=None,
) -> APIRouter:
    """聚合运维设置子路由，保持既有 URL 与依赖注入入口。"""
    router = APIRouter()
    router.include_router(build_data_sources_router(write_dependency=write_dependency))
    router.include_router(
        build_system_settings_router(
            write_dependency=write_dependency,
            market_db=market_db,
            setup_access_allowed=setup_access_allowed,
        )
    )
    router.include_router(
        build_notification_settings_router(
            write_dependency=write_dependency,
            ops_db=ops_db,
        )
    )
    router.include_router(
        build_paper_quant_router(
            write_dependency=write_dependency,
            ops_db=ops_db,
            scheduler_getter=scheduler_getter,
        )
    )
    router.include_router(
        build_market_sync_settings_router(
            write_dependency=write_dependency,
            ops_db=ops_db,
            scheduler_getter=scheduler_getter,
        )
    )
    router.include_router(build_share_pack_router(write_dependency=write_dependency))
    return router
