"""行情 / 策略 / 回测 / 技能 / 任务 / 供应商的 HTTP 聚合挂载。

各限界上下文路由已下沉到 ``src/<bc>/api/``；本文件只做 include，保持 URL 不变。
懒导入与 503 capabilities 语义由子 router / quant_common 保留。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def build_quant_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    palace_db: str | None = None,
    scheduler_getter=None,
    setup_access_allowed=None,
) -> APIRouter:
    """构造聚合 router。依赖由 app.main 注入，便于测试时整体替换。"""
    from src.ai.api.router import build_ai_router
    from src.intel.api.router import build_intel_router
    from src.market.api.router import build_market_router
    from src.ops.api.jobs import build_jobs_router
    from src.ops.api.settings import build_ops_settings_router
    from src.ops.api.skills import build_skills_router
    from src.review.api.router import build_review_router
    from src.app.screen_skills_api import build_screen_skills_router
    from src.strategy.api.convert import build_strategy_convert_router
    from src.strategy.api.router import build_strategy_router

    router = APIRouter()

    @router.get("/api/capabilities", tags=["system"])
    def capabilities() -> dict[str, Any]:
        """哪些能力当前可用。前端据此决定隐藏哪些入口。"""

        def probe(module: str) -> bool:
            try:
                __import__(module)
                return True
            except ImportError:
                return False

        has_pandas = probe("pandas")
        has_akshare = probe("akshare")
        has_scheduler = probe("apscheduler")
        has_yaml = probe("yaml")
        has_crypto = probe("cryptography")
        return {
            "market": has_pandas,
            "quotes_sync": has_pandas and has_akshare,
            "strategies": has_pandas,
            "backtest": has_pandas,
            "skills": has_yaml,
            "scheduler": has_scheduler,
            "llm": has_crypto,
            "missing": [
                name
                for name, ok in (
                    ("pandas", has_pandas),
                    ("akshare", has_akshare),
                    ("apscheduler", has_scheduler),
                    ("PyYAML", has_yaml),
                    ("cryptography", has_crypto),
                )
                if not ok
            ],
        }

    common = dict(
        write_dependency=write_dependency,
        market_db=market_db,
        ops_db=ops_db,
        palace_db=palace_db,
    )
    router.include_router(
        build_market_router(
            write_dependency=write_dependency,
            market_db=market_db,
            palace_db=palace_db,
        )
    )
    router.include_router(
        build_strategy_router(**common, scheduler_getter=scheduler_getter)
    )
    router.include_router(
        build_strategy_convert_router(
            write_dependency=write_dependency, ops_db=ops_db
        )
    )
    router.include_router(
        build_screen_skills_router(
            write_dependency=write_dependency,
            market_db=market_db,
            ops_db=ops_db,
            scheduler_getter=scheduler_getter,
        )
    )
    router.include_router(
        build_review_router(market_db=market_db, palace_db=palace_db)
    )
    router.include_router(
        build_skills_router(**common, scheduler_getter=scheduler_getter)
    )
    router.include_router(
        build_jobs_router(**common, scheduler_getter=scheduler_getter)
    )
    router.include_router(
        build_ops_settings_router(
            write_dependency=write_dependency,
            market_db=market_db,
            ops_db=ops_db,
            scheduler_getter=scheduler_getter,
            setup_access_allowed=setup_access_allowed,
        )
    )
    router.include_router(
        build_ai_router(
            write_dependency=write_dependency,
            ops_db=ops_db,
            palace_db=palace_db,
        )
    )
    router.include_router(build_intel_router(write_dependency=write_dependency))
    return router
