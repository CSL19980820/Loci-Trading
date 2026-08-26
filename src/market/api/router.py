"""行情 / 股票池 HTTP。"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.market.api.schemas import (
    BootstrapRequest,
    _BOOTSTRAP,
    _BOOTSTRAP_LOCK,
    bootstrap_snapshot,
    bootstrap_update,
)
from src.shared.api_deps import (
    market_hot_store,
    market_store,
    missing_dependency,
)
from src.shared.api_models import UniverseSpecModel

logger = logging.getLogger(__name__)

# 测试与旧导入路径兼容：闸门实现在 board_router。
from src.market.api.board_router import board_spot_persist_gate as board_spot_persist_gate


def _session_status(store) -> tuple[dict[str, Any], dict[str, Any]]:
    """读覆盖 + 日历并组装闸门状态，返回 ``(coverage, session)``。

    日历读不出时降级为空日历，但必须留痕：静默空列表会让 ``build_session_status``
    报「休市」，和真的休市无法区分。
    """
    from src.market.application.session import build_session_status

    coverage = store.coverage()
    try:
        days = store.trading_days()
    except sqlite3.Error as exc:
        logger.warning("交易日历读取失败，按空日历降级：%s", exc)
        days = []
    return coverage, build_session_status(coverage=coverage, trading_days=days)


def build_market_router(
    *,
    write_dependency,
    market_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    from src.market.api.akshare import build_akshare_catalog_router

    router.include_router(build_akshare_catalog_router(write_dependency=write_dependency))
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    def _hot():
        return market_hot_store()

    @router.get("/api/market/coverage", tags=["market"])
    def market_coverage() -> dict[str, Any]:
        with _hot() as store:
            return store.coverage()

    @router.get("/api/market/session", tags=["market"])
    def market_session() -> dict[str, Any]:
        """交易日 / 实时闸门 / 是否需要补数。前端轮询与回填都看这个。"""
        with _hot() as store:
            return _session_status(store)[1]

    @router.get("/api/market/live-tape", tags=["market"])
    def market_live_tape(
        refresh: bool = Query(default=False),
    ) -> dict[str, Any]:
        """任务栏 / 顶栏实时行情：只有指数（新浪 hq）。

        账本不再记录真实持仓，行情条也就没有「我的票」这一段，只保留指数。
        """
        try:
            from src.market.application.live import build_live_tape
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        return build_live_tape(use_cache=not refresh)

    @router.get("/api/universe/presets", tags=["universe"])
    def universe_presets() -> list[dict[str, Any]]:
        try:
            from src.market.domain.universe import list_presets
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return list_presets()

    @router.get("/api/universe/stats", tags=["universe"])
    def universe_stats_api() -> dict[str, Any]:
        try:
            from src.market.domain.universe import universe_stats
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _hot() as store:
            return universe_stats(store)

    @router.post("/api/universe/preview", tags=["universe"])
    def universe_preview(payload: UniverseSpecModel) -> dict[str, Any]:
        """只解析股票池与漏斗，不跑策略。"""
        try:
            from src.market.domain.universe import UniverseError, resolve_universe
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _hot() as store:
            try:
                resolved = resolve_universe(
                    store, payload.model_dump(exclude_none=True)
                )
            except UniverseError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "universe": resolved.spec,
            "universe_funnel": resolved.funnel.to_dict(),
            "code_count": len(resolved.codes),
        }

    @router.get("/api/market/search", tags=["market"])
    def market_search(
        q: str = Query(min_length=1, max_length=32),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        """代码或名称模糊搜索，供前端全局搜索框与命令面板用。"""
        needle = q.strip().lower()
        if not needle:
            return []
        with _hot() as store:
            _total, rows = store.page_instruments(
                q=needle,
                instrument_type=None,
                status="",
                offset=0,
                limit=limit,
            )
        return rows

    from src.market.api.board_router import register_board_routes

    register_board_routes(
        router,
        hot_factory=_hot,
        market_db=market_db,
        write_dependency=write_dependency,
    )

    @router.get("/api/market/quotes/{code}", tags=["market"])
    def market_quotes(
        code: str,
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        adjust: Literal["qfq", "hfq", "none"] = "qfq",
        limit: int | None = Query(
            default=60,
            ge=20,
            le=5000,
            description="只返回最近 N 根日线（从末尾截）；详情默认 60，可按需加大",
        ),
    ) -> dict[str, Any]:
        with _hot() as store:
            try:
                from src.market import normalize_code

                code = normalize_code(code)
                frame = store.history(code, start=start, end=end, adjust=adjust)
                total_rows = len(frame)
                if limit and total_rows > limit:
                    frame = frame.iloc[-limit:].reset_index(drop=True)
                row = store.conn.execute(
                    "SELECT code, name, market, board, industry, instrument_type"
                    " FROM instruments WHERE code = ?",
                    (code,),
                ).fetchone()
                meta = dict(row) if row else {"code": code, "name": ""}
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        from src.market.domain.universe import BOARD_LABELS, classify_board

        board_bucket = classify_board(code)
        board_zh = BOARD_LABELS.get(board_bucket, "")
        stored_board = str(meta.get("board") or "").strip()
        # 库内可能已是中文「主板」等；否则用代码归类标签
        if stored_board in BOARD_LABELS.values():
            board_label = stored_board
        elif board_zh:
            board_label = board_zh
        else:
            board_label = stored_board or "其他"
        return {
            "code": code,
            "name": meta.get("name") or "",
            "market": meta.get("market") or "",
            "board": stored_board or board_bucket,
            "board_label": board_label,
            "industry": str(meta.get("industry") or "").strip(),
            "adjust": adjust,
            "rows": len(frame),
            "total_rows": total_rows,
            "bars": frame.to_dict("records"),
        }

    @router.get("/api/market/minute/{code}", tags=["market"])
    def market_minute(
        code: str,
        period: Literal["1", "5", "15", "30", "60"] = "1",
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        days: int = Query(default=1, ge=1, le=5),
        adjust: Literal["qfq", "hfq", "none"] = "none",
    ) -> dict[str, Any]:
        """实时拉取分钟线；不写 ``market.db``。``date`` 指定交易日时只取该日。

        源（通达信/东财/新浪）只给不复权成交价；``adjust=qfq|hfq`` 时用本地
        ``adjust_factors`` 缩放到与日 K 同口径（通达信协议本身不提供前复权分时）。
        """
        from src.market.application.minute import (
            MinuteQueryError,
            apply_minute_adjust,
            fetch_minute_bars,
            unadjusted_prev_close,
        )

        try:
            code, frame, source = fetch_minute_bars(
                code,
                period=period,
                days=days,
                trade_date=date,
            )
        except MinuteQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        name = ""
        prev_close: float | None = None
        actual_trade_date = date or ""
        if not actual_trade_date:
            for raw in frame.get("datetime", []):
                datetime_text = str(raw or "")
                if len(datetime_text) >= 10:
                    actual_trade_date = datetime_text[:10]
                    break
        with _hot() as store:
            row = store.conn.execute(
                "SELECT name FROM instruments WHERE code = ?",
                (code,),
            ).fetchone()
            if row:
                name = str(row["name"] or "")
            if actual_trade_date:
                prev_close = unadjusted_prev_close(
                    store.conn, code, actual_trade_date
                )
                frame, prev_close = apply_minute_adjust(
                    store,
                    code,
                    actual_trade_date,
                    frame,
                    adjust=adjust,
                    prev_close=prev_close,
                )
        bars = frame.to_dict("records")
        for bar in bars:
            dt = bar.get("datetime")
            if dt is not None and not isinstance(dt, str):
                bar["datetime"] = str(dt)
        return {
            "code": code,
            "name": name,
            "trade_date": actual_trade_date,
            "period": period,
            "adjust": adjust,
            "source": source,
            "prev_close": prev_close,
            "rows": len(bars),
            "bars": bars,
        }

    @router.get("/api/market/bootstrap", tags=["market"])
    def market_bootstrap_status() -> dict[str, Any]:
        """历史 K 线回填进度；附带是否需要补数（空库或落后交易日）。"""
        snap = bootstrap_snapshot()
        with _market() as store:
            coverage, session = _session_status(store)
        snap["needed"] = bool(session.get("needs_backfill"))
        snap["coverage"] = coverage
        snap["session"] = session
        snap["backfill_kind"] = session.get("backfill_kind")
        return snap

    @router.post("/api/market/bootstrap", tags=["market"], status_code=202)
    def market_bootstrap_start(
        payload: BootstrapRequest | None = None,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """后台启动全市场历史日 K 回填；前端轮询 GET 看进度条。"""
        try:
            from src.ops.application.jobs import JobContext, JobError, execute_sync
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        with _BOOTSTRAP_LOCK:
            if _BOOTSTRAP.get("status") == "running":
                return bootstrap_snapshot()
            _BOOTSTRAP.update(
                {
                    "status": "running",
                    "phase": "instruments",
                    "done": 0,
                    "total": 0,
                    "percent": 0.0,
                    "code": "",
                    "message": "正在刷新证券列表…",
                    "report": None,
                }
            )

        opts = (payload or BootstrapRequest()).model_dump()

        def run() -> None:
            stop_heartbeat = threading.Event()

            def instruments_heartbeat() -> None:
                started = time.monotonic()
                while not stop_heartbeat.wait(5.0):
                    snap = bootstrap_snapshot()
                    if snap.get("status") != "running" or snap.get("phase") != "instruments":
                        return
                    waited = int(time.monotonic() - started)
                    bootstrap_update(
                        phase="instruments",
                        message=f"正在刷新证券列表…（已等待 {waited}s）",
                    )

            try:
                bootstrap_update(
                    phase="instruments",
                    message="正在刷新证券列表…",
                )
                threading.Thread(
                    target=instruments_heartbeat,
                    name="loci-bootstrap-instruments-hb",
                    daemon=True,
                ).start()

                def on_progress(done: int, total: int, code: str) -> None:
                    message = (
                        f"等待首个行情请求完成（{done}/{total}）"
                        if total > 0 and done == 0 and not code
                        else f"同步日线 {done}/{total}"
                    )
                    if code and done < total:
                        message += f" · 当前 {code}"
                    bootstrap_update(
                        phase="quotes",
                        done=done,
                        total=total,
                        code=code,
                        message=message,
                    )

                context = JobContext(market_db=market_db)
                bootstrap_update(phase="instruments", message="正在刷新证券列表…")
                report = execute_sync(
                    {
                        "refresh_instruments": True,
                        "workers": opts["workers"],
                        "interval": opts["interval"],
                        "limit": opts["limit"],
                        "with_factors": opts["with_factors"],
                        "force": False,
                    },
                    context,
                    progress=on_progress,
                )
                stop_heartbeat.set()
                bootstrap_update(
                    status="done",
                    phase="done",
                    done=int(report.get("total") or 0),
                    total=int(report.get("total") or 0),
                    message=f"完成：成功 {report.get('succeeded')} / 失败 {report.get('failed')}",
                    report=report,
                )
            except JobError as exc:
                stop_heartbeat.set()
                bootstrap_update(status="error", phase="error", message=str(exc))
            except Exception as exc:
                stop_heartbeat.set()
                bootstrap_update(
                    status="error",
                    phase="error",
                    message=f"{type(exc).__name__}: {exc}",
                )

        threading.Thread(target=run, name="loci-market-bootstrap", daemon=True).start()
        return bootstrap_snapshot()

    from src.market.api.quality_router import build_quality_router
    router.include_router(build_quality_router(write_dependency=write_dependency, market_db=market_db))

    return router
