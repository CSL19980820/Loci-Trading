"""行情质量、修复与同步 HTTP 路由。"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from src.app.legacy.quant_common import SyncRequest, market_store, missing_dependency


_MARKET_SYNC_LOCK = threading.Lock()


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
    ) -> dict[str, Any]:
        """行情仓体检报告：覆盖率/时效/换手率缺失/复权因子等。"""
        try:
            from src.market.application.quality import check_market_health

            with market_store(market_db) as store:
                report = check_market_health(
                    store, trade_date=date, include_ok=include_ok
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
            409: {"description": "行情同步已在当前进程运行"},
            502: {"description": "同步执行失败"},
        },
    )
    async def market_sync(payload: SyncRequest, _write: None = write_guard) -> dict[str, Any]:
        """同步行情并在完成后返回报告；同一进程内拒绝重复执行。"""
        try:
            from src.ops.application.jobs import JobContext, JobError, execute_sync
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        if not _MARKET_SYNC_LOCK.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="行情同步正在执行")
        try:
            return await run_in_threadpool(
                execute_sync, payload.model_dump(), JobContext(market_db=market_db)
            )
        except JobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"同步失败：{exc}") from exc
        finally:
            _MARKET_SYNC_LOCK.release()

    return router
