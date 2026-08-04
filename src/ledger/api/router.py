"""账本 HTTP 路由（dashboard / positions / candidates / plans / reviews / account）。"""
import csv
import io
import json
import logging
from collections.abc import Callable, Generator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from src.ledger import PalaceStore
from src.ledger.api.schemas import (
    CandidateBatchDeleteInput,
    CandidateInput,
    CashflowInput,
    DailyPnlInput,
    PlanInput,
    ReviewInput,
    SnapshotInput,
    TradeInput,
)

logger = logging.getLogger(__name__)

MAX_QIANLONG_IMPORT_BYTES = 2 * 1024 * 1024


def build_ledger_router(
    *,
    write_dependency: Callable[..., None],
    get_store: Callable[..., Generator[PalaceStore, None, None]],
    market_db: str | None = None,
) -> APIRouter:
    """装配账本路由；写操作与 Store 依赖由组合根注入。

    注意：本模块不使用 ``from __future__ import annotations``。
    工厂内 ``Annotated[..., Depends(...)]`` 别名必须在路由 ``def`` 时求值为实体，
    否则 FastAPI 会把 ``store`` / 写依赖误判为 query 参数。
    """
    router = APIRouter()
    Store = Annotated[PalaceStore, Depends(get_store)]
    WriteAccess = Annotated[None, Depends(write_dependency)]

    @router.get("/api/dashboard", tags=["dashboard"])
    def dashboard(
        store: Store, date_value: str | None = Query(default=None, alias="date")
    ) -> dict[str, Any]:
        return store.dashboard_payload(date_value)

    @router.get("/api/positions", tags=["positions"])
    def positions(store: Store) -> list[dict[str, Any]]:
        return store.positions_payload()

    @router.get("/api/candidates", tags=["candidates"])
    def candidates(
        store: Store,
        date_value: str | None = Query(default=None, alias="date"),
        include_backfill: bool = Query(
            default=False,
            description="true 时含区间回填；默认排除",
        ),
    ) -> list[dict[str, Any]]:
        return store.candidates_payload(
            date_value, include_backfill=include_backfill
        )

    @router.get("/api/candidates/list", tags=["candidates"])
    def candidates_list(
        store: Store,
        strategy: str | None = Query(default=None, max_length=64),
        decision: str | None = Query(default=None, max_length=32),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=200, ge=1, le=1000),
        include_backfill: bool = Query(
            default=False,
            description="true 时含区间回填；默认排除",
        ),
    ) -> list[dict[str, Any]]:
        """跨日期候选列表。按战法/裁决过滤，点进详情看单条。"""
        return store.candidates_list_payload(
            strategy=strategy,
            decision=decision,
            start=start,
            end=end,
            limit=limit,
            include_backfill=include_backfill,
        )

    @router.get("/api/plans", tags=["plans"])
    def plans(store: Store, status: str = "active") -> list[dict[str, Any]]:
        return store.plans_payload(status)

    @router.get("/api/timeline/{code}", tags=["timeline"])
    def timeline(code: str, store: Store) -> list[dict[str, Any]]:
        return store.timeline_payload(code)

    @router.get("/api/trades", tags=["positions"])
    def trades(
        store: Store,
        code: str | None = Query(default=None, pattern=r"^\d{6}$"),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return store.trades_payload(code=code, limit=limit)

    def _csv_attachment(
        rows: list[dict[str, Any]], columns: list[tuple[str, str]], filename: str
    ) -> Response:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([header for _, header in columns])
        for row in rows:
            writer.writerow([row.get(key, "") for key, _ in columns])
        return Response(
            content=buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/api/trades/export.csv", tags=["positions"])
    def export_trades_csv(
        store: Store,
        code: str | None = Query(default=None, pattern=r"^\d{6}$"),
        limit: int = Query(default=10_000, ge=1, le=10_000),
    ) -> Response:
        rows = store.trades_payload(code=code, limit=limit)
        columns = [
            ("date", "日期"),
            ("action", "动作"),
            ("code", "代码"),
            ("name", "名称"),
            ("shares", "数量"),
            ("price", "价格"),
            ("realized_pnl", "已实现盈亏"),
            ("reason", "备注"),
        ]
        return _csv_attachment(rows, columns, "trades.csv")

    @router.get("/api/candidates/export.csv", tags=["candidates"])
    def export_candidates_csv(
        store: Store,
        strategy: str | None = Query(default=None, max_length=64),
        decision: str | None = Query(default=None, max_length=32),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=10_000, ge=1, le=10_000),
        include_backfill: bool = Query(default=False),
    ) -> Response:
        rows = store.candidates_list_payload(
            strategy=strategy,
            decision=decision,
            start=start,
            end=end,
            limit=limit,
            include_backfill=include_backfill,
        )
        columns = [
            ("date", "日期"),
            ("code", "代码"),
            ("name", "名称"),
            ("decision", "裁决"),
            ("score", "评分"),
            ("reason", "理由"),
            ("pool_id", "候选池"),
            ("rule_version", "战法"),
        ]
        return _csv_attachment(rows, columns, "candidates.csv")

    def _read_qianlong_upload(upload: UploadFile) -> tuple[dict[str, Any], str]:
        # 同步读文件：async 路由会切线程，与单连接 PalaceStore 冲突。
        source_label = upload.filename or "state.json"
        raw = upload.file.read(MAX_QIANLONG_IMPORT_BYTES + 1)
        if len(raw) > MAX_QIANLONG_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="state.json 文件过大")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="state.json 须为 UTF-8 编码") from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="JSON 格式无效") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="潜龙 state.json 必须是 JSON 对象")
        return payload, source_label

    @router.post("/api/import/qianlong/preview", tags=["positions"])
    def preview_qianlong_import(
        store: Store,
        file: UploadFile = File(..., description="潜龙 state.json"),
    ) -> dict[str, Any]:
        payload, _ = _read_qianlong_upload(file)
        return store.preview_qianlong_state(payload)

    @router.post("/api/import/qianlong/confirm", tags=["positions"])
    def confirm_qianlong_import(
        store: Store,
        _: WriteAccess,
        file: UploadFile = File(..., description="潜龙 state.json"),
    ) -> dict[str, Any]:
        payload, source_label = _read_qianlong_upload(file)
        return store.import_qianlong_payload(
            payload,
            source="qianlong-web-import",
            source_label=source_label,
        )

    @router.get("/api/alerts/today", tags=["plans"])
    def today_alerts(store: Store) -> list[dict[str, Any]]:
        from src.review.application.alerts import today_alerts_payload

        if not market_db:
            return today_alerts_payload(store, None)
        try:
            from src.market import MarketStore

            with MarketStore(market_db) as market:
                return today_alerts_payload(store, market)
        except Exception:
            logger.debug("行情库不可用，触价提醒降级为无报价", exc_info=True)
            return today_alerts_payload(store, None)

    @router.get("/api/reviews", tags=["review"])
    def reviews(
        store: Store, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        return store.reviews_payload(limit=limit)

    @router.get("/api/pools", tags=["candidates"])
    def pools(store: Store) -> list[dict[str, Any]]:
        return store.pool_dates_payload()

    @router.get("/api/pools/day", tags=["candidates"])
    def pool_day(
        store: Store,
        date_value: str | None = Query(default=None, alias="date"),
        pool_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return store.pool_day_payload(date_value, pool_id)

    @router.get("/api/analytics", tags=["dashboard"])
    def analytics(store: Store) -> dict[str, Any]:
        return store.analytics_payload()

    @router.get("/api/scorecard", tags=["review"])
    def scorecard(store: Store) -> dict[str, Any]:
        return store.scorecard()

    @router.post("/api/trades", status_code=201, tags=["positions"])
    def create_trade(payload: TradeInput, store: Store, _: WriteAccess) -> dict[str, Any]:
        values = payload.model_dump()
        correlation_id = str(values.get("correlation_id") or "").strip()
        return store.record_trades([values], idempotency_key=correlation_id)[0]

    @router.post("/api/candidates", status_code=201, tags=["candidates"])
    def create_candidate(
        payload: CandidateInput, store: Store, _: WriteAccess
    ) -> dict[str, str]:
        return {"id": store.record_candidate(**payload.model_dump())}

    @router.delete("/api/candidates/{candidate_id}", tags=["candidates"])
    def delete_candidate(
        candidate_id: str, store: Store, _: WriteAccess
    ) -> dict[str, bool]:
        if not store.delete_candidate(candidate_id):
            raise HTTPException(status_code=404, detail=f"未找到候选：{candidate_id}")
        return {"removed": True}

    @router.post("/api/candidates/batch-delete", tags=["candidates"])
    def batch_delete_candidates(
        payload: CandidateBatchDeleteInput,
        store: Store,
        _: WriteAccess,
    ) -> dict[str, int]:
        return {"removed": store.delete_candidates(payload.ids)}

    @router.post("/api/plans", status_code=201, tags=["plans"])
    def create_plan(payload: PlanInput, store: Store, _: WriteAccess) -> dict[str, str]:
        return {"id": store.record_plan(**payload.model_dump())}

    @router.post("/api/reviews", status_code=201, tags=["review"])
    def create_review(payload: ReviewInput, store: Store, _: WriteAccess) -> dict[str, str]:
        return {"id": store.record_review(**payload.model_dump())}

    @router.post("/api/snapshots", status_code=201, tags=["account"])
    def create_snapshot(
        payload: SnapshotInput, store: Store, _: WriteAccess
    ) -> dict[str, str]:
        return {"id": store.record_snapshot(**payload.model_dump())}

    @router.post("/api/cashflows", status_code=201, tags=["account"])
    def create_cashflow(
        payload: CashflowInput, store: Store, _: WriteAccess
    ) -> dict[str, str]:
        return {"id": store.record_account_event(kind="CASHFLOW", **payload.model_dump())}

    @router.get("/api/daily-pnl", tags=["account"])
    def list_daily_pnl(
        store: Store,
        limit: int = Query(default=365, ge=1, le=3650),
    ) -> dict[str, Any]:
        """券商市值法当日盈亏流水（应用账本权威）。"""
        return {
            "summary": store.daily_pnl_summary(),
            "rows": store.list_daily_pnl(limit=limit),
        }

    @router.post("/api/daily-pnl", status_code=201, tags=["account"])
    def upsert_daily_pnl(
        payload: DailyPnlInput, store: Store, _: WriteAccess
    ) -> dict[str, Any]:
        return store.record_daily_pnl(**payload.model_dump())

    return router
