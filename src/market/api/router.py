"""行情 / 股票池 HTTP。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.legacy.quant_common import (
    DEFAULT_PALACE_DB,
    BootstrapRequest,
    SyncRequest,
    UniverseSpecModel,
    _BOOTSTRAP,
    _BOOTSTRAP_LOCK,
    bootstrap_snapshot,
    bootstrap_update,
    market_store,
    missing_dependency,
)

logger = logging.getLogger(__name__)


def build_market_router(
    *,
    write_dependency,
    market_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    @router.get("/api/market/coverage", tags=["market"])
    def market_coverage() -> dict[str, Any]:
        with _market() as store:
            return store.coverage()

    @router.get("/api/market/session", tags=["market"])
    def market_session() -> dict[str, Any]:
        """交易日 / 实时闸门 / 是否需要补数。前端轮询与回填都看这个。"""
        from src.market.application.session import build_session_status

        with _market() as store:
            coverage = store.coverage()
            try:
                days = store.trading_days()
            except Exception:
                days = []
        return build_session_status(coverage=coverage, trading_days=days)

    @router.get("/api/market/live-tape", tags=["market"])
    def market_live_tape(
        refresh: bool = Query(default=False),
    ) -> dict[str, Any]:
        """任务栏 / 顶栏实时行情：指数 + 当前持仓现价（新浪 hq）。"""
        try:
            from src.market.infrastructure.live_tape import build_live_tape
            from src.ledger import PalaceStore
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        positions: list[dict[str, Any]] = []
        try:
            with PalaceStore(palace_db or DEFAULT_PALACE_DB) as store:
                positions = store.positions_payload()
        except Exception as exc:
            # 账本坏了仍应返回指数，不让顶栏整条挂掉
            logger.warning("读持仓失败，行情条仅显示指数：%s", exc)

        return build_live_tape(
            position_codes=positions,
            use_cache=not refresh,
        )

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
        with _market() as store:
            return universe_stats(store)

    @router.post("/api/universe/preview", tags=["universe"])
    def universe_preview(payload: UniverseSpecModel) -> dict[str, Any]:
        """只解析股票池与漏斗，不跑策略。"""
        try:
            from src.market.domain.universe import UniverseError, resolve_universe
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _market() as store:
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
        with _market() as store:
            rows = store.list_instruments(status="")
        matched = [
            row
            for row in rows
            if needle in row["code"] or needle in str(row["name"]).lower()
        ]
        return matched[:limit]

    @router.get("/api/market/board", tags=["market"])
    def market_board(
        q: str = Query(default="", max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=10, le=100),
        live: bool = Query(default=False),
        instrument_type: str | None = Query(default="STOCK"),
        status: str = Query(default="normal"),
    ) -> dict[str, Any]:
        """行情台分页列表：默认只读本机最新日线（快）；``live=true`` 才叠当前页实时。

        只对当前页批量拉实时，不扫全市场——几千只票靠分页浏览。
        """
        from datetime import datetime

        type_filter = None if instrument_type in (None, "", "all") else instrument_type
        status_filter = "" if status in ("", "all") else status
        offset = (page - 1) * page_size
        with _market() as store:
            total, instruments = store.page_instruments(
                q=q,
                instrument_type=type_filter,
                status=status_filter,
                offset=offset,
                limit=page_size,
            )
            local_map = store.latest_bars([row["code"] for row in instruments])

        live_map: dict[str, dict[str, Any]] = {}
        live_error = ""
        if live and instruments:
            try:
                from src.market.infrastructure.live_tape import fetch_live_quotes

                codes = [str(row["code"]) for row in instruments]
                types = {
                    str(row["code"]): str(row.get("instrument_type") or "STOCK")
                    for row in instruments
                }
                for quote in fetch_live_quotes(codes, instrument_types=types):
                    code = str(quote.get("code") or "")
                    if code:
                        live_map[code] = quote

                # 盘中实时写入当日 bar：后台线程，不拖慢列表响应
                persist_codes = list(codes)
                persist_types = dict(types)
                persist_db = market_db

                def _persist_spot() -> None:
                    try:
                        from src.market import MarketStore, apply_today_spot

                        with MarketStore(persist_db) as spot_store:
                            apply_today_spot(
                                spot_store,
                                persist_codes,
                                instrument_types=persist_types,
                            )
                    except Exception as exc:  # pragma: no cover
                        logger.warning("后台写入当日行情失败：%s", exc)

                threading.Thread(
                    target=_persist_spot, name="board-spot-persist", daemon=True
                ).start()
            except Exception as exc:  # pragma: no cover - 网络失败
                live_error = f"{type(exc).__name__}: {exc}"

        items: list[dict[str, Any]] = []
        for row in instruments:
            code = str(row["code"])
            local = local_map.get(code) or {}
            spot = live_map.get(code)
            item: dict[str, Any] = {
                "code": code,
                "name": row.get("name") or "",
                "market": row.get("market") or "",
                "board": row.get("board") or "",
                "instrument_type": row.get("instrument_type") or "STOCK",
                "status": row.get("status") or "",
                "local_date": local.get("trade_date") or "",
                "local_close": local.get("close"),
                "local_pct": local.get("pct"),
                "local_change": local.get("change"),
                "price": None,
                "pct": None,
                "change": None,
                "open": None,
                "high": None,
                "low": None,
                "prev_close": local.get("prev_close"),
                "volume": local.get("volume"),
                "amount": local.get("amount"),
                "trade_time": "",
                "ok": False,
                "source": "local" if local else "",
            }
            if spot:
                item.update(
                    {
                        "name": spot.get("name") or item["name"],
                        "price": spot.get("price"),
                        "pct": spot.get("pct"),
                        "change": spot.get("change"),
                        "open": spot.get("open"),
                        "high": spot.get("high"),
                        "low": spot.get("low"),
                        "prev_close": spot.get("prev_close"),
                        "volume": spot.get("volume"),
                        "amount": spot.get("amount"),
                        "trade_time": spot.get("trade_time") or "",
                        "ok": True,
                        "source": "sina",
                    }
                )
            elif local:
                item.update(
                    {
                        "price": local.get("close"),
                        "pct": local.get("pct"),
                        "change": local.get("change"),
                        "open": local.get("open"),
                        "high": local.get("high"),
                        "low": local.get("low"),
                        "ok": False,
                        "source": "local",
                    }
                )
            items.append(item)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "live_error": live_error,
            "items": items,
        }

    @router.get("/api/market/quotes/{code}", tags=["market"])
    def market_quotes(
        code: str,
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        adjust: Literal["qfq", "hfq", "none"] = "qfq",
        limit: int | None = Query(
            default=800,
            ge=50,
            le=5000,
            description="只返回最近 N 根（从末尾截）；不传则默认 800",
        ),
    ) -> dict[str, Any]:
        with _market() as store:
            try:
                from src.market.infrastructure.store import normalize_code

                code = normalize_code(code)
                frame = store.history(code, start=start, end=end, adjust=adjust)
                total_rows = len(frame)
                if limit and total_rows > limit:
                    frame = frame.iloc[-limit:].reset_index(drop=True)
                row = store.conn.execute(
                    "SELECT code, name, market, board, instrument_type"
                    " FROM instruments WHERE code = ?",
                    (code,),
                ).fetchone()
                meta = dict(row) if row else {"code": code, "name": ""}
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "code": code,
            "name": meta.get("name") or "",
            "market": meta.get("market") or "",
            "board": meta.get("board") or "",
            "adjust": adjust,
            "rows": len(frame),
            "total_rows": total_rows,
            "bars": frame.to_dict("records"),
        }

    @router.post("/api/market/sync", tags=["market"], status_code=202)
    def market_sync(payload: SyncRequest, _write: None = write_guard) -> dict[str, Any]:
        """同步行情。同步执行——单用户场景下等几十秒可以接受，
        真要长跑就建一个 sync 任务交给调度器。"""
        try:
            from src.ops.application.jobs import JobContext, execute_sync
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        context = JobContext(market_db=market_db)
        try:
            return execute_sync(payload.model_dump(), context)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"同步失败：{exc}") from exc

    @router.get("/api/market/bootstrap", tags=["market"])
    def market_bootstrap_status() -> dict[str, Any]:
        """历史 K 线回填进度；附带是否需要补数（空库或落后交易日）。"""
        from src.market.application.session import build_session_status

        snap = bootstrap_snapshot()
        with _market() as store:
            coverage = store.coverage()
            try:
                days = store.trading_days()
            except Exception:
                days = []
        session = build_session_status(coverage=coverage, trading_days=days)
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
            try:
                bootstrap_update(
                    phase="instruments",
                    message="正在刷新证券列表…",
                )

                def on_progress(done: int, total: int, code: str) -> None:
                    bootstrap_update(
                        phase="quotes",
                        done=done,
                        total=total,
                        code=code,
                        message=f"同步日线 {done}/{total}",
                    )

                context = JobContext(market_db=market_db)
                bootstrap_update(phase="quotes", message="开始同步历史日线…")
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
                bootstrap_update(
                    status="done",
                    phase="done",
                    done=int(report.get("total") or 0),
                    total=int(report.get("total") or 0),
                    message=f"完成：成功 {report.get('succeeded')} / 失败 {report.get('failed')}",
                    report=report,
                )
            except JobError as exc:
                bootstrap_update(status="error", phase="error", message=str(exc))
            except Exception as exc:
                bootstrap_update(
                    status="error",
                    phase="error",
                    message=f"{type(exc).__name__}: {exc}",
                )

        threading.Thread(target=run, name="loci-market-bootstrap", daemon=True).start()
        return bootstrap_snapshot()

    @router.get("/api/market/health", tags=["market"])
    def market_health(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict[str, Any]:
        """行情仓体检报告：覆盖率/时效/换手率缺失/复权因子等。"""
        try:
            from src.market.infrastructure.sentinel import check_market_health
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _market() as store:
            return check_market_health(store, trade_date=date).to_dict()

    return router
