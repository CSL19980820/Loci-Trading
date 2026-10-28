"""收盘快照定稿：权威日 K 不可用时的同日收盘兜底。

通达信是日终定稿首选源，但公开服务器可能在协议层整体失联。此时不能把盘中
``_spot`` 行当作收盘数据，也不能让全市场选股永久失败；允许在 **15:00 之后**
从自报交易日的行情源取完整收盘快照，并写成独立的 ``sina_close`` 正式日 K。

三个硬约束：

1. 只在目标交易日收盘后执行，且源返回日期必须等于目标日。
2. 有成交标的直接使用源给出的收盘 OHLCV；源明确今日零量额且昨收有效的停牌
   标的，以昨收生成 ``volume=0`` 的平价行，不能拿旧日 K 冒充今日。
3. 每条写入都带 ``hist_daily`` 回执和 ``close_snapshot=true`` 标记，选股门禁
   仍按正式日 K 回执核验。
"""
from __future__ import annotations

from datetime import datetime, time as clock_time
import logging
import time
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from src.shared.clock import utc_now

from src.market.infrastructure.adapters import (
    AdapterError,
    get_adapter,
    lane_provider_enabled,
)
from src.market.infrastructure.store import MarketStore, normalize_code
from src.market.infrastructure.store_quote_payload import partition_valid_ohlc_rows

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
_CLOSE_AT = clock_time(15, 0)

#: 快照定稿在仓内使用独立 source，避免把收盘兜底误记成新浪历史日 K。
CLOSE_SNAPSHOT_SOURCE = "sina_close"
CLOSE_SNAPSHOT_ADAPTER = "sina"


class CloseSnapshotError(RuntimeError):
    """收盘快照无法作为正式日 K 定稿。"""


def finalize_close_snapshot(
    store: MarketStore,
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    trade_date: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """用收盘后的完整快照写入正式日 K 与 ``hist_daily`` 回执。"""
    current = now or datetime.now(_TZ)
    current = current.replace(tzinfo=_TZ) if current.tzinfo is None else current.astimezone(_TZ)
    target = str(trade_date or current.date().isoformat())[:10]
    if target != current.date().isoformat():
        raise CloseSnapshotError(
            f"收盘快照只能定稿当天，目标日 {target} 与当前日期 {current.date().isoformat()} 不一致"
        )
    if current.time() < _CLOSE_AT:
        raise CloseSnapshotError("尚未收盘，禁止用现价快照替代正式日 K")
    if not lane_provider_enabled(CLOSE_SNAPSHOT_ADAPTER, "spot_batch"):
        raise CloseSnapshotError(f"收盘快照源 {CLOSE_SNAPSHOT_ADAPTER} 已被停用")

    wanted = list(dict.fromkeys(normalize_code(code) for code in codes if str(code).strip()))
    if not wanted:
        return _empty_report(target)

    started = time.monotonic()
    adapter = get_adapter(CLOSE_SNAPSHOT_ADAPTER)
    try:
        frame = adapter.fetch_spot_close(
            wanted,
            instrument_types=instrument_types,
            batch_size=400,
        )
    except AdapterError as exc:
        raise CloseSnapshotError(f"收盘快照拉取失败：{exc}") from exc
    except Exception as exc:
        raise CloseSnapshotError(
            f"收盘快照拉取失败：{type(exc).__name__}: {exc}"
        ) from exc
    if frame is None or frame.empty:
        raise CloseSnapshotError("收盘快照为空")

    required = {"code", "date", "open", "high", "low", "close", "volume", "amount"}
    missing_columns = sorted(required - set(str(column) for column in frame.columns))
    if missing_columns:
        raise CloseSnapshotError(f"收盘快照缺列：{missing_columns}")

    prepared = frame.copy()
    prepared["code"] = prepared["code"].map(lambda value: normalize_code(str(value)))
    prepared["date"] = pd.to_datetime(
        prepared["date"], format="ISO8601", errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    prepared = prepared[prepared["code"].isin(set(wanted))]
    stale = sorted(
        set(prepared.loc[prepared["date"] != target, "code"].astype(str))
    )
    prepared = prepared[prepared["date"] == target].drop_duplicates(
        subset=["code"], keep="last"
    )
    if prepared.empty:
        raise CloseSnapshotError(f"收盘快照没有任何一只返回 {target}")

    prepared, rejected = partition_valid_ohlc_rows(prepared)
    invalid = set(rejected["code"].astype(str)) if not rejected.empty else set()
    if prepared.empty:
        raise CloseSnapshotError("收盘快照的 OHLC 全部无效")

    returned = set(prepared["code"].astype(str))
    missing = [code for code in wanted if code not in returned or code in invalid]
    fetched_at = utc_now()
    receipts: list[dict[str, Any]] = []
    bars: list[dict[str, Any]] = []
    no_trade_codes: list[str] = []
    source_url = str(getattr(adapter.meta, "base_url", "") or "")
    fields = [str(column) for column in prepared.columns]
    for row in prepared.itertuples(index=False):
        code = str(row.code)
        volume = float(row.volume or 0.0)
        no_trade = volume <= 0
        if no_trade:
            no_trade_codes.append(code)
        attempts = [
            {
                "source_id": CLOSE_SNAPSHOT_SOURCE,
                "state": "selected",
                "checked_at": fetched_at,
                "rows": 1,
                "fields": fields,
            }
        ]
        receipts.append(
            {
                "code": code,
                "lane": "hist_daily",
                "requested_sources": [CLOSE_SNAPSHOT_SOURCE],
                "attempts": attempts,
                "selected_source": CLOSE_SNAPSHOT_SOURCE,
                "fallback_used": True,
                "unresolved": False,
                "state": "selected",
                "coverage": {
                    "source_rows": 1,
                    "rows_written": 0,
                    "close_snapshot": True,
                    "no_trade": no_trade,
                    "source_adapter": CLOSE_SNAPSHOT_ADAPTER,
                },
                "source_url": source_url,
                "fetched_at": fetched_at,
                "published_at": "",
                "publication_status": "not_observed",
                "available_at": "",
                "availability_status": "not_observed",
                "coverage_start": target,
                "coverage_end": target,
                "request_start": target,
                "request_end": target,
            }
        )
        bars.append(
            {
                "code": code,
                "date": target,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": volume,
                "amount": float(row.amount or 0.0),
            }
        )

    written = store.persist_quote_bar_receipts(
        receipts, bars, source=CLOSE_SNAPSHOT_SOURCE
    )
    if returned:
        store.set_watermarks(
            [(code, target) for code in sorted(returned)],
            status="ok",
            source=CLOSE_SNAPSHOT_SOURCE,
        )

    finalized_codes = sorted(returned)
    failed_codes = sorted(set(missing) | set(stale) | invalid)
    if no_trade_codes:
        logger.warning(
            "收盘快照以零成交平价行定稿 %d 只：%s",
            len(no_trade_codes),
            ", ".join(no_trade_codes[:10]),
        )
    return {
        "status": "failed" if failed_codes else "ok",
        "source": CLOSE_SNAPSHOT_SOURCE,
        "trade_date": target,
        "total": len(wanted),
        "succeeded": len(finalized_codes),
        "failed": len(failed_codes),
        "rows_written": int(written),
        "no_trade": len(no_trade_codes),
        "no_trade_codes": no_trade_codes,
        "finalized_codes": finalized_codes,
        "failed_codes": failed_codes,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


def _empty_report(target: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "source": CLOSE_SNAPSHOT_SOURCE,
        "trade_date": target,
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "rows_written": 0,
        "no_trade": 0,
        "no_trade_codes": [],
        "finalized_codes": [],
        "failed_codes": [],
        "elapsed_seconds": 0.0,
    }
