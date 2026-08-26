"""行情数据质量与修复用例。"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.market.infrastructure.sentinel import HealthReport
    from src.market.infrastructure.store import MarketStore


def check_market_health(
    store: "MarketStore",
    *,
    trade_date: str | None = None,
    include_ok: bool = False,
    include_network: bool = False,
) -> "HealthReport":
    """执行行情体检并返回领域报告。"""
    from src.market.infrastructure.sentinel import check_market_health as _check_market_health

    return _check_market_health(
        store,
        trade_date=trade_date,
        include_ok=include_ok,
        include_network=include_network,
    )


def repair_turnover(store: "MarketStore", *, since: str | None = None) -> dict[str, Any]:
    """按请求选择换手率缺失回填或异常单位修复。"""
    from src.market.infrastructure.turnover_repair import (
        backfill_missing_turnover,
        repair_inflated_turnover,
    )

    if since:
        return repair_inflated_turnover(store, since=since)
    return backfill_missing_turnover(store, since=None)
