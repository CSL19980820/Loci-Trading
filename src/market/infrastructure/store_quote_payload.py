"""行情批量写入前的归一化。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_schema import PANEL_FIELDS


def partition_valid_ohlc_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按日 K 最小价格约束拆分可落盘与拒绝的行，保留原始列供回执记录。"""
    if frame is None:
        return pd.DataFrame(), pd.DataFrame()
    if frame.empty:
        return frame.copy(), frame.copy()

    columns = {str(column).strip().lower(): column for column in frame.columns}
    required = ("open", "high", "low", "close")
    if any(field not in columns for field in required):
        return frame.iloc[0:0].copy(), frame.copy()

    prices = pd.DataFrame(
        {field: pd.to_numeric(frame[columns[field]], errors="coerce") for field in required},
        index=frame.index,
    )
    valid = (
        prices.notna().all(axis=1)
        & (prices > 0).all(axis=1)
        & (prices["high"] >= prices[["open", "low", "close"]].max(axis=1))
        & (prices["low"] <= prices[["open", "high", "close"]].min(axis=1))
    )
    return frame.loc[valid].copy(), frame.loc[~valid].copy()


def quote_payload_from_bars(
    bars: Iterable[dict[str, Any]],
    *,
    source: str,
    receipt_ids: Mapping[str, str] | None = None,
) -> list[tuple[Any, ...]]:
    records: list[dict[str, Any]] = []
    for raw in bars:
        try:
            code = normalize_code(str(raw.get("code") or ""))
        except MarketError:
            continue
        trade_date = raw.get("date") if raw.get("date") is not None else raw.get("trade_date")
        if trade_date is not None and trade_date != "":
            records.append(
                {"code": code, "trade_date": trade_date, **{
                    column: raw.get(column) for column in PANEL_FIELDS
                }}
            )
    if not records:
        return []
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d")
    frame = frame[["code", "trade_date", *PANEL_FIELDS]].drop_duplicates(
        subset=["code", "trade_date"], keep="last"
    ).astype(object).where(pd.notna(frame), None)
    frame, _rejected = partition_valid_ohlc_rows(frame)
    return [
        (
            str(row.trade_date), str(row.code), row.open, row.high, row.low, row.close,
            row.volume, row.amount, row.outstanding_share, row.turnover, source,
            (receipt_ids or {}).get(str(row.code)),
        )
        for row in frame.itertuples(index=False)
    ]
