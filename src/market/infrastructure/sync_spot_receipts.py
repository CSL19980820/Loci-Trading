"""当日 spot 的来源回执构造与失败落盘。

从 ``sync_spot.py`` 拆出来是体量原因（那边贴着 600 行上限）。回执是研究输入
证据，不是供应商评分：每只**请求过**的代码都要有终态，源夹带回来但没请求的
代码不能入库，否则会产生没有 receipt 的遗留行情。

``_retry_db_write`` / ``_source_url`` / ``fallback_used`` 在函数内延迟 import：
主模块要 import 本模块，模块级反向 import 会成环。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
import logging
from typing import Any

from src.shared.clock import utc_now

from src.market.infrastructure.store import MarketStore

logger = logging.getLogger(__name__)

def _spot_receipts(
    requested_codes: Sequence[str],
    returned_dates: Mapping[str, str],
    attempts: Sequence[Mapping[str, Any]],
    *,
    adapter_id: str,
    trade_date: str,
    error: str = "",
    stale_dates: Mapping[str, str] | None = None,
    source_rows_by_code: Mapping[str, int] | None = None,
    rejected_ohlc_by_code: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    requested_sources = [str(item.get("source_id") or "") for item in attempts]
    from src.market.infrastructure.sync_spot import _source_url, fallback_used

    fallback = fallback_used(attempts, adapter_id)
    receipts: list[dict[str, Any]] = []
    for code in requested_codes:
        returned_date = returned_dates.get(code, "")
        stale_date = (stale_dates or {}).get(code, "")
        unresolved = not bool(returned_date)
        receipt_error = error
        if not receipt_error and unresolved:
            rejected_rows = int((rejected_ohlc_by_code or {}).get(code, 0))
            # 给企微/执行历史看的人话；内部仍用 coverage.rejected_ohlc_rows 计数。
            if rejected_rows:
                receipt_error = "当日现价无效（开高低收对不上或为0，常见于停牌/退市）"
            elif stale_date:
                receipt_error = (
                    f"只有旧日期 {stale_date}，没有今天 {trade_date}（常见于停牌/退市）"
                )
            else:
                receipt_error = "行情源没返回这只票（常见于停牌/退市）"
        receipts.append(
            {
                "code": code,
                "lane": "spot_batch",
                "requested_sources": requested_sources,
                "attempts": [dict(item) for item in attempts],
                "selected_source": adapter_id,
                "fallback_used": fallback,
                "unresolved": unresolved,
                "state": "failed" if unresolved else "selected",
                "coverage": {
                    "source_rows": int((source_rows_by_code or {}).get(code, 0)),
                    "rows_written": 0,
                    "rejected_ohlc_rows": int((rejected_ohlc_by_code or {}).get(code, 0)),
                },
                "source_url": _source_url(adapter_id),
                "published_at": "",
                "publication_status": "not_observed",
                "available_at": "",
                "availability_status": "not_observed",
                "coverage_start": returned_date,
                "coverage_end": returned_date,
                "request_start": trade_date,
                "request_end": trade_date,
                "error": receipt_error,
            }
        )
    return receipts


def _persist_spot_failure_receipts(
    store: MarketStore,
    codes: Sequence[str],
    attempts: Sequence[Mapping[str, Any]],
    *,
    adapter_id: str,
    error: str,
) -> list[dict[str, Any]]:
    """整批现价失败只留一条摘要回执，避免 5000+ 条同文案灌库。"""
    failure_attempts = [dict(item) for item in attempts]
    if not failure_attempts:
        failure_attempts.append(
            {
                "source_id": "spot_router",
                "state": "failed",
                "checked_at": utc_now(),
                "error": error,
            }
        )
    sample_codes = list(codes[:1]) or ["*"]
    receipts = _spot_receipts(
        sample_codes,
        {},
        failure_attempts,
        adapter_id=adapter_id,
        trade_date=date.today().isoformat(),
        error=error,
    )
    if receipts:
        receipts[0]["batch_size"] = len(codes)
    try:
        from src.market.infrastructure.sync_spot import _retry_db_write

        _retry_db_write(
            lambda: store.persist_quote_bar_receipts(receipts, [], source=""),
            what="spot 失败回执",
        )
    except Exception:
        logger.exception("持久化 spot 失败回执时又出错")
    return receipts
