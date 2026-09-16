"""On-demand, paginated UI reads; never change the agent's evidence horizon."""
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ledger import GuardianStore
from src.ops.application.guardian_context import active_strategies, observation_snapshot
from src.ops.infrastructure.store import OpsStore


@dataclass(frozen=True)
class HistoryWindow:
    start: str
    end: str
    limit: int
    offset: int


def history_window(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1000000),
) -> HistoryWindow:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    first = start or end or today
    last = end or start or today
    if first > last or last == date.max:
        raise HTTPException(422, "日期范围无效：开始日期须不晚于结束日期")
    return HistoryWindow(first.isoformat(), last.isoformat(), limit, offset)


Window = Annotated[HistoryWindow, Depends(history_window)]


def build_guardian_reads_router() -> APIRouter:
    router = APIRouter()

    @router.get("/reviews")
    def get_reviews(window: Window) -> dict:
        with GuardianStore() as ledger:
            return {**ledger.report_page(**asdict(window)), **asdict(window)}

    @router.get("/runs")
    def get_runs(window: Window) -> dict:
        with GuardianStore() as ledger:
            return {**ledger.cycle_page(**asdict(window)), **asdict(window)}

    @router.get("/runs/{slot}")
    def get_run(slot: str) -> dict:
        with GuardianStore() as ledger:
            item = ledger.cycle_detail(slot)
            if item is None:
                raise HTTPException(404, "尚无该轮研判")
            return item

    @router.get("/trades")
    def get_trades(window: Window) -> dict:
        with GuardianStore() as ledger:
            return {**ledger.trade_page(**asdict(window)), **asdict(window)}

    @router.get("/performance")
    def get_performance(
        limit: int = Query(default=20, ge=1, le=200),
        offset: int = Query(default=0, ge=0, le=1000000),
    ) -> dict:
        with GuardianStore() as ledger:
            return {**ledger.performance_page(limit=limit, offset=offset), "limit": limit, "offset": offset}

    @router.get("/research")
    def get_research() -> dict:
        with OpsStore(None) as store, GuardianStore() as ledger:
            state = ledger.state()
            return {"active_strategies": [{"slug": r["slug"], "name": r.get("name", r["slug"])}
                                           for r in active_strategies(store)],
                    **observation_snapshot(state)}

    return router
