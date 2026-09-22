"""运维设置 HTTP 聚合入口。"""
from __future__ import annotations

from fastapi import APIRouter

from src.ops.api.data_sources import (
    build_data_sources_router,
)
from src.ops.api.market_sync import build_market_sync_settings_router
from src.ops.api.notifications import build_notification_settings_router
from src.ops.api.paper_quant import build_paper_quant_router
from src.ops.api.guardian import build_guardian_router
from src.ops.api.stock_agents import build_stock_agents_router
from src.ops.api.share_pack import build_share_pack_router
from src.ops.api.system_settings import build_system_settings_router
from src.ops.api.retention_settings import build_retention_router


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
    router.include_router(build_retention_router(write_dependency=write_dependency))
    router.include_router(build_guardian_router(write_dependency=write_dependency, scheduler_getter=scheduler_getter))
    router.include_router(build_stock_agents_router(write_dependency=write_dependency, scheduler_getter=scheduler_getter))
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
            # **一律传 None**：通知配置（含企微 webhook）是每个租户自己的东西，必须
            # 落在 ``OpsStore(None)`` 解析出来的那个租户库里。
            #
            # 组合根把 ``PALACE_OPS_DB`` 读成字符串一路传到这里（``app/main.py`` →
            # ``app/legacy/quant_router.py`` → 本文件），而那个变量表达的是「这台机器上
            # 主租户的那一份库」。``paths._tenant_scoped`` 里「env 只对主租户生效」的
            # 护栏只在**不传参**时起作用；显式传一个字符串会把它整条绕过。运维一旦填了
            # 这个变量，全部租户就共用一个 ops.db——A 改 webhook 会改掉 B 的，A 的告警
            # 会发进 B 的群，而且不报错、不刷红。
            #
            # 生产暂未设该变量所以没引爆；但 ``tests/conftest.py`` 全程设着，于是也没有
            # 任何用例能发现回归。回归测试见 ``tests/ops/test_notify_tenant.py``。
            # ``src/ai/api/assistant.py`` 的挂载点出于同样理由早就写死 None。
            ops_db=None,
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
