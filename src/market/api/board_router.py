"""行情台 board / industries 路由。"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

#: board live 后台写库节流：多会话/多轮询并发时，60s 内只放行一次
#: apply_today_spot，避免写放大与锁竞争。
_SPOT_PERSIST_LOCK = threading.Lock()
_SPOT_PERSIST_LAST: float = 0.0
_SPOT_PERSIST_INTERVAL_SEC = 60.0

_ALLOWED_BOARD_SORT = frozenset(
    {
        "code",
        "turnover_desc",
        "turnover_asc",
        "pct_desc",
        "pct_asc",
        "amount_desc",
        "amount_asc",
    }
)


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


class BoardSpotPersistBody(BaseModel):
    """显式落盘当日 spot：指定 codes，或按与 board 相同的分页条件取当前页。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    codes: list[str] | None = Field(
        default=None,
        description="指定代码（最多 80）；有值时忽略分页条件",
    )
    q: str = Field(default="", max_length=32)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    instrument_type: str | None = "STOCK"
    status: str = "normal"
    industry: str | None = None
    sort: str = "code"
    turnover_min: float | None = Field(default=None, ge=0)


def apply_spot_and_mirror(
    market_db: str | None,
    codes: Sequence[str],
    *,
    instrument_types: Mapping[str, str] | None = None,
    live_quotes: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """写全量库当日 spot，再增量镜像热库。供显式 POST 与 GET persist 后台复用。"""
    from src.market import (
        MarketStore,
        apply_today_spot,
        mirror_recent_to_hot,
        open_market_hot,
    )

    code_list = [str(code) for code in codes if str(code).strip()]
    types = dict(instrument_types or {})
    written = 0
    with MarketStore(market_db) as spot_store:
        written = apply_today_spot(
            spot_store,
            code_list,
            instrument_types=types or None,
            live_quotes=live_quotes,
        )
    mirrored: dict[str, Any] = {}
    with MarketStore(market_db) as full, open_market_hot() as hot:
        mirrored = mirror_recent_to_hot(full, hot)
    return {
        "written": int(written),
        "codes": code_list,
        "mirrored": mirrored,
    }


def _resolve_board_page(
    store: Any,
    *,
    q: str,
    page: int,
    page_size: int,
    instrument_type: str | None,
    status: str,
    industry: str | None,
    sort: str,
    turnover_min: float | None,
    codes: Sequence[str] | None,
) -> tuple[int, list[dict[str, Any]]]:
    type_filter = None if instrument_type in (None, "", "all") else instrument_type
    status_filter = "" if status in ("", "all") else status
    industry_filter = None if industry in (None, "", "all") else str(industry).strip()
    sort_key = (sort or "code").strip().lower()
    if sort_key not in _ALLOWED_BOARD_SORT:
        raise HTTPException(
            status_code=422,
            detail=(
                "sort 仅支持 code / turnover_desc / turnover_asc / pct_desc /"
                " pct_asc / amount_desc / amount_asc"
            ),
        )
    turnover_floor = None if turnover_min is None else float(turnover_min) / 100.0
    offset = (page - 1) * page_size
    code_list = [str(part).strip() for part in (codes or []) if str(part).strip()][:80]
    if code_list:
        instruments = store.instruments_by_codes(code_list, instrument_type=type_filter)
        return len(instruments), instruments
    if sort_key.startswith("turnover") or turnover_floor is not None:
        return store.page_instruments_by_turnover(
            q=q,
            instrument_type=type_filter,
            status=status_filter,
            industry=industry_filter,
            turnover_min=turnover_floor,
            sort=sort_key if sort_key.startswith("turnover") else "code",
            offset=offset,
            limit=page_size,
        )
    if sort_key.startswith("pct"):
        return store.page_instruments_by_pct(
            q=q,
            instrument_type=type_filter,
            status=status_filter,
            industry=industry_filter,
            sort=sort_key,
            offset=offset,
            limit=page_size,
        )
    if sort_key.startswith("amount"):
        return store.page_instruments_by_amount(
            q=q,
            instrument_type=type_filter,
            status=status_filter,
            industry=industry_filter,
            sort=sort_key,
            offset=offset,
            limit=page_size,
        )
    return store.page_instruments(
        q=q,
        instrument_type=type_filter,
        status=status_filter,
        industry=industry_filter,
        offset=offset,
        limit=page_size,
    )


def register_board_routes(
    router: APIRouter,
    *,
    hot_factory,
    market_db: str | None,
    write_dependency,
) -> None:
    def _hot():
        return hot_factory()

    write_guard = Depends(write_dependency)

    @router.get("/api/market/board", tags=["market"])
    def market_board(
        request: Request,
        q: str = Query(default="", max_length=32),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        live: bool = Query(default=False),
        persist: bool = Query(
            default=False,
            description="live=true 时将本页 spot 落盘到 market.db 并镜像热库；需写鉴权",
        ),
        instrument_type: str | None = Query(default="STOCK"),
        status: str = Query(default="normal"),
        industry: str | None = Query(
            default=None,
            description="所属行业模糊匹配（如 半导体 / 电力设备）；空=全部",
        ),
        sort: str = Query(
            default="code",
            description=(
                "排序：code | turnover_desc | turnover_asc | pct_desc | pct_asc |"
                " amount_desc | amount_asc"
            ),
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
        ``persist=true`` 才后台落盘当日 spot（默认只读轮询不写库）。
        轮询请用 ``persist=false``；显式落盘请走 ``POST /api/market/board/spot``。
        """
        if persist and not live:
            raise HTTPException(status_code=422, detail="persist 需要 live=true")
        if persist:
            write_dependency(request)

        code_list = [
            part.strip() for part in str(codes or "").split(",") if part.strip()
        ][:80]
        with _hot() as store:
            total, instruments = _resolve_board_page(
                store,
                q=q,
                page=page,
                page_size=page_size,
                instrument_type=instrument_type,
                status=status,
                industry=industry,
                sort=sort,
                turnover_min=turnover_min,
                codes=code_list or None,
            )
            local_map = store.latest_bars([row["code"] for row in instruments])

        live_map: dict[str, dict[str, Any]] = {}
        live_error = ""
        if live and instruments:
            try:
                from src.market.application.live import fetch_live_quotes

                page_codes = [str(row["code"]) for row in instruments]
                types = {
                    str(row["code"]): str(row.get("instrument_type") or "STOCK")
                    for row in instruments
                }
                for quote in fetch_live_quotes(page_codes, instrument_types=types):
                    code = str(quote.get("code") or "")
                    if code:
                        live_map[code] = quote

                # 显式 persist 才后台写当日 bar；60s 节流避免写放大与锁竞争。
                persist_codes = list(page_codes)
                persist_types = dict(types)
                persist_quotes = list(live_map.values())
                persist_db = market_db

                def _persist_spot() -> None:
                    try:
                        apply_spot_and_mirror(
                            persist_db,
                            persist_codes,
                            instrument_types=persist_types,
                            live_quotes=persist_quotes,
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.warning("后台写入当日行情失败：%s", exc)

                if persist and persist_quotes and board_spot_persist_gate():
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

    @router.post("/api/market/board/spot", tags=["market"])
    def market_board_spot_persist(
        payload: BoardSpotPersistBody,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """显式落盘当日 spot 并镜像热库；与 live 轮询解耦，需写鉴权。"""
        raw_codes = [
            str(code).strip() for code in (payload.codes or []) if str(code).strip()
        ][:80]
        with _hot() as store:
            _total, instruments = _resolve_board_page(
                store,
                q=payload.q,
                page=payload.page,
                page_size=payload.page_size,
                instrument_type=payload.instrument_type,
                status=payload.status,
                industry=payload.industry,
                sort=payload.sort,
                turnover_min=payload.turnover_min,
                codes=raw_codes or None,
            )
        if not instruments:
            raise HTTPException(status_code=422, detail="没有可落盘的标的")
        page_codes = [str(row["code"]) for row in instruments]
        types = {
            str(row["code"]): str(row.get("instrument_type") or "STOCK")
            for row in instruments
        }
        try:
            result = apply_spot_and_mirror(
                market_db,
                page_codes,
                instrument_types=types,
            )
        except Exception as exc:
            logger.warning("显式落盘当日行情失败：%s", exc)
            raise HTTPException(
                status_code=502, detail=f"落盘失败：{type(exc).__name__}: {exc}"
            ) from exc
        return {
            "ok": True,
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **result,
        }

    @router.get("/api/market/industries", tags=["market"])
    def market_industries() -> dict[str, Any]:
        """已入库所属行业列表（刷新证券列表后才有半导体/电力设备等）。"""
        with _hot() as store:
            names = store.list_industries()
        return {"items": names, "total": len(names)}

