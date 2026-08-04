"""行情 / 股票池 HTTP。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.legacy.quant_common import (
    DEFAULT_PALACE_DB,
    BootstrapRequest,
    UniverseSpecModel,
    _BOOTSTRAP,
    _BOOTSTRAP_LOCK,
    bootstrap_snapshot,
    bootstrap_update,
    market_store,
    missing_dependency,
)

logger = logging.getLogger(__name__)

#: board live 后台写库节流：多会话/多轮询并发时，60s 内只放行一次
#: apply_today_spot，避免写放大与锁竞争。
_SPOT_PERSIST_LOCK = threading.Lock()
_SPOT_PERSIST_LAST: float = 0.0
_SPOT_PERSIST_INTERVAL_SEC = 60.0


def board_spot_persist_gate() -> bool:
    """进程内节流闸门：距上次放行超过间隔才返回 True。"""
    global _SPOT_PERSIST_LAST
    with _SPOT_PERSIST_LOCK:
        import time

        now = time.monotonic()
        if now - _SPOT_PERSIST_LAST < _SPOT_PERSIST_INTERVAL_SEC:
            return False
        _SPOT_PERSIST_LAST = now
        return True


def build_market_router(
    *,
    write_dependency,
    market_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()
    from src.market.api.akshare import build_akshare_catalog_router

    router.include_router(build_akshare_catalog_router(write_dependency=write_dependency))
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
            from src.market.application.live import build_live_tape
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
        if not needle:
            return []
        with _market() as store:
            _total, rows = store.page_instruments(
                q=needle,
                instrument_type=None,
                status="",
                offset=0,
                limit=limit,
            )
        return rows

    @router.get("/api/market/board", tags=["market"])
    def market_board(
        q: str = Query(default="", max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        live: bool = Query(default=False),
        instrument_type: str | None = Query(default="STOCK"),
        status: str = Query(default="normal"),
        industry: str | None = Query(
            default=None,
            description="所属行业模糊匹配（如 半导体 / 电力设备）；空=全部",
        ),
        sort: str = Query(
            default="code",
            description="排序：code | turnover_desc | turnover_asc | pct_desc | pct_asc",
        ),
        turnover_min: float | None = Query(
            default=None,
            ge=0,
            description="最低换手率（百分数，如 5 表示 5%）",
        ),
        codes: str | None = Query(
            default=None,
            max_length=800,
            description="逗号分隔代码（最多 80）；指定时忽略分页宇宙，按给定顺序返回",
        ),
    ) -> dict[str, Any]:
        """行情台分页列表：默认只读本机最新日线（快）；``live=true`` 才叠当前页实时。

        只对当前页批量拉实时，不扫全市场——几千只票靠分页浏览。
        ``codes`` 供首页「昨选今涨」等按票叠价。
        """
        from datetime import datetime

        type_filter = None if instrument_type in (None, "", "all") else instrument_type
        status_filter = "" if status in ("", "all") else status
        industry_filter = None if industry in (None, "", "all") else str(industry).strip()
        sort_key = (sort or "code").strip().lower()
        allowed_sort = {
            "code",
            "turnover_desc",
            "turnover_asc",
            "pct_desc",
            "pct_asc",
        }
        if sort_key not in allowed_sort:
            raise HTTPException(
                status_code=422,
                detail="sort 仅支持 code / turnover_desc / turnover_asc / pct_desc / pct_asc",
            )
        # 库内 turnover 为小数；入参按百分数（与列表展示一致）
        turnover_floor = None if turnover_min is None else float(turnover_min) / 100.0
        offset = (page - 1) * page_size
        code_list = [
            part.strip()
            for part in str(codes or "").split(",")
            if part.strip()
        ][:80]
        with _market() as store:
            if code_list:
                instruments = store.instruments_by_codes(
                    code_list, instrument_type=type_filter
                )
                total = len(instruments)
            elif sort_key.startswith("turnover") or turnover_floor is not None:
                total, instruments = store.page_instruments_by_turnover(
                    q=q,
                    instrument_type=type_filter,
                    status=status_filter,
                    industry=industry_filter,
                    turnover_min=turnover_floor,
                    sort=sort_key if sort_key.startswith("turnover") else "code",
                    offset=offset,
                    limit=page_size,
                )
            elif sort_key.startswith("pct"):
                total, instruments = store.page_instruments_by_pct(
                    q=q,
                    instrument_type=type_filter,
                    status=status_filter,
                    industry=industry_filter,
                    sort=sort_key,
                    offset=offset,
                    limit=page_size,
                )
            else:
                total, instruments = store.page_instruments(
                    q=q,
                    instrument_type=type_filter,
                    status=status_filter,
                    industry=industry_filter,
                    offset=offset,
                    limit=page_size,
                )
            local_map = store.latest_bars([row["code"] for row in instruments])

        live_map: dict[str, dict[str, Any]] = {}
        live_error = ""
        if live and instruments:
            try:
                from src.market.application.live import fetch_live_quotes

                codes = [str(row["code"]) for row in instruments]
                types = {
                    str(row["code"]): str(row.get("instrument_type") or "STOCK")
                    for row in instruments
                }
                for quote in fetch_live_quotes(codes, instrument_types=types):
                    code = str(quote.get("code") or "")
                    if code:
                        live_map[code] = quote

                # 盘中实时写入当日 bar：后台线程，不拖慢列表响应。
                # 每次 live 轮询都写库会放大写放大与锁竞争，60s 内只落一次。
                persist_codes = list(codes)
                persist_types = dict(types)
                persist_quotes = list(live_map.values())
                persist_db = market_db
                def _persist_spot() -> None:
                    try:
                        from src.market import MarketStore, apply_today_spot

                        with MarketStore(persist_db) as spot_store:
                            apply_today_spot(
                                spot_store,
                                persist_codes,
                                instrument_types=persist_types,
                                live_quotes=persist_quotes,
                            )
                    except Exception as exc:  # pragma: no cover
                        logger.warning("后台写入当日行情失败：%s", exc)

                if persist_quotes and board_spot_persist_gate():
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
                "industry": row.get("industry") or "",
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
                "turnover": local.get("turnover"),
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
                        "source": spot.get("source") or "sina",
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

    @router.get("/api/market/industries", tags=["market"])
    def market_industries() -> dict[str, Any]:
        """已入库所属行业列表（刷新证券列表后才有半导体/电力设备等）。"""
        with _market() as store:
            names = store.list_industries()
        return {"items": names, "total": len(names)}

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
        with _market() as store:
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
        with _market() as store:
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

    from src.market.api.quality_router import build_quality_router
    router.include_router(build_quality_router(write_dependency=write_dependency, market_db=market_db))

    return router
