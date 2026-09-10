"""最近交易日选股 HTTP：可选同步行情后读取结果。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.shared.api_deps import (
    market_hot_store,
    market_store,
    missing_dependency,
    should_sync_today,
)
from src.shared.paths import market_hot_db
from src.shared.screen_capacity import ScreenCapacityBusy, screen_capacity_permit

logger = logging.getLogger(__name__)


def build_screen_today_router(
    *,
    write_dependency,
    market_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    """注册最近交易日选股端点。"""
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    def _hot():
        return market_hot_store(str(market_hot_db()))

    def _capacity_label(strategy: str) -> str:
        from src.shared.tenancy import current_tenant, is_primary_tenant

        slug = str(strategy or "?")
        return f"http-today:{slug}" if is_primary_tenant() else f"http-today:[{current_tenant()}] {slug}"

    @router.get("/api/screen/today", tags=["strategy"])
    def screen_today(
        strategy: str = Query(min_length=1, max_length=64),
        force_sync: bool = Query(default=False),
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        record_candidates: bool = Query(default=True),
        top_n: int = Query(default=0, ge=0, le=500),
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """取指定日（默认最近可交易日）选股结果；默认写入候选池。"""
        try:
            from src.market import DataQualityError
            from src.strategy import screen as run_screen
            from src.strategy.application.persist import persist_screen_candidates
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        synced = False
        sync_note = ""
        if force_sync or should_sync_today(market_db):
            try:
                from src.ops.application.jobs import JobContext, execute_sync

                ctx = JobContext(
                    market_db=market_db, market_hot_db=str(market_hot_db())
                )
                refresh_instruments = force_sync
                with ctx.market() as store:
                    if not store.list_instruments():
                        refresh_instruments = True
                report = execute_sync(
                    {
                        "workers": 6,
                        "interval": 0.1,
                        "with_factors": True,
                        "refresh_instruments": refresh_instruments,
                        "limit": 200,
                    },
                    ctx,
                )
                synced = True
                sync_note = (
                    f"同步 {report.get('succeeded', 0)} 只，"
                    f"跳过 {report.get('skipped', 0)} 只"
                )
            except Exception as exc:
                sync_note = f"同步失败（{exc}），使用本地数据"

        # 同步成功后把最近交易日（含当日 spot）增量镜像进热库；镜像失败不阻断，
        # 热库缺当日由哨兵/重建任务兜底。
        if synced:
            try:
                from src.market import mirror_recent_to_hot

                with _market() as full, _hot() as hot:
                    mirror_recent_to_hot(full, hot)
            except Exception as exc:
                logger.warning("镜像热库失败（由哨兵兜底）：%s", exc)

        try:
            # 同步请求不应在长任务后排队；容量已满时交回可重试的 429。
            with screen_capacity_permit(
                label=_capacity_label(strategy),
                wait_sec=0,
            ):
                with _hot() as store:
                    try:
                        result = run_screen(
                            store,
                            strategy,
                            trade_date=date,
                            universe=None,
                        )
                    except DataQualityError as exc:
                        raise HTTPException(
                            status_code=422,
                            detail=f"数据体检未通过，已拒绝选股：{exc}",
                            headers={"X-Data-Health": "blocked"},
                        ) from exc
                    except StrategyError as exc:
                        raise HTTPException(status_code=422, detail=str(exc)) from exc
                    names = (
                        {
                            item["code"]: item["name"]
                            for item in store.list_instruments(status="")
                        }
                        if record_candidates
                        else {}
                    )
        except ScreenCapacityBusy as exc:
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"Retry-After": "5"},
            ) from exc

        body: dict[str, Any] = {
            "strategy": result.strategy_slug,
            "strategy_revision": result.strategy_revision,
            "trade_date": result.trade_date,
            "entry_timing": result.entry_timing,
            "universe_size": result.universe_size,
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "params": result.params,
            "effective_params": result.effective_params,
            "picks": result.picks,
            "watch_picks": result.watch_picks,
            "universe": result.universe,
            "universe_funnel": result.universe_funnel,
            "data_snapshot": result.data_snapshot,
            "synced": synced,
            "sync_note": sync_note,
        }
        if record_candidates:
            body["recorded"] = persist_screen_candidates(
                result,
                palace_db=palace_db,
                names=names,
                top_n=top_n,
                source="api:screen_today",
            )
        return body

    return router


__all__ = ["build_screen_today_router"]
