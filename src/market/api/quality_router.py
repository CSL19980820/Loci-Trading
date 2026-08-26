"""行情质量、修复与同步 HTTP 路由。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

from src.market.api.schemas import SyncRequest
from src.shared.api_deps import market_store, missing_dependency


def build_quality_router(
    *,
    write_dependency,
    market_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    @router.get("/api/market/health", tags=["market"])
    def market_health(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        include_ok: bool = Query(
            default=False,
            description="保留通过项，供体检页扫描回放；选股门禁勿开",
        ),
        include_network: bool = Query(
            default=False,
            description="深度扫描：探测数据源连通（外网）；选股门禁勿开",
        ),
    ) -> dict[str, Any]:
        """行情仓体检：仓内质量 + 线路/依赖/会话等扩展项；可选连通探测。"""
        try:
            from src.market.application.quality import check_market_health

            with market_store(market_db) as store:
                report = check_market_health(
                    store,
                    trade_date=date,
                    include_ok=include_ok,
                    include_network=include_network,
                )
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return report.to_dict()

    @router.post("/api/market/repair/turnover", tags=["market"])
    def market_repair_turnover(
        since: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """回填/修复换手率，不重拉 OHLC。"""
        try:
            from src.market.application.quality import repair_turnover

            with market_store(market_db) as store:
                report = repair_turnover(store, since=since)
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return {"ok": True, **report}

    @router.post(
        "/api/market/sync",
        tags=["market"],
        responses={
            200: {
                "description": (
                    "同步完成并返回报告；闸门判定「已有同步在跑」时同样是 200，"
                    'body 为 {"ok": true, "status": "skipped", ...}'
                )
            },
            422: {"description": "请求参数非法，或没有可同步的标的"},
            502: {"description": "同步执行失败"},
        },
    )
    async def market_sync(payload: SyncRequest, _write: None = write_guard) -> dict[str, Any]:
        """同步行情并在完成后返回报告。

        **并发闸门只有一处**：``execute_sync`` 自己会占 ``ops.market_gate`` 的 sync
        写槽（HTTP / bootstrap / CLI / 调度四个入口共用同一把）。这里曾经再叠一层
        进程锁并回 409，等于同一件事判两次，还把「有人正在写同一批当日行情」说成
        冲突错误。现在闸门统一在 ``market_gate``：它说 skipped 就返回 200 +
        ``status="skipped"`` —— 排队不是故障，调用方不该看到红色。
        """
        try:
            from src.ops.application.jobs import (
                JobContext,
                JobError,
                JobSkipped,
                execute_sync,
            )
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            return await run_in_threadpool(
                execute_sync, payload.model_dump(), JobContext(market_db=market_db)
            )
        except JobSkipped as exc:
            # JobSkipped 是 JobError 的子类，必须排在 JobError 之前接。
            logger.info("行情同步本轮未启动（闸门判跳过）：%s", exc)
            return {
                "ok": True,
                "status": "skipped",
                "skipped": True,
                "detail": "已有同步在跑，本次未重复启动",
                "reason": str(exc),
            }
        except JobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            # JobError 之外的一律按 502 上报，但先记全 traceback：否则代码 bug
            # （KeyError / AttributeError）会伪装成「同步失败」，无从排查。
            logger.exception("行情同步未预期失败")
            raise HTTPException(status_code=502, detail=f"同步失败：{exc}") from exc

    return router
