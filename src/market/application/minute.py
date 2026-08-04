"""分钟线查询用例。"""
from __future__ import annotations

from typing import Any, Literal, Protocol

import pandas as pd

MinuteAdjust = Literal["qfq", "hfq", "none"]
_PRICE_COLS = ("open", "high", "low", "close", "avg_price")


class MinuteQueryError(ValueError):
    """分钟线请求不合法或行情源拒绝请求。"""


class _QuotesConn(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...


def unadjusted_prev_close(
    conn: _QuotesConn,
    code: str,
    trade_date: str,
) -> float | None:
    """分时用的昨收：取 ``quotes_daily`` 不复权收盘价。"""
    day = str(trade_date or "").strip()[:10]
    plain = str(code or "").strip()
    if not day or not plain:
        return None
    row = conn.execute(
        "SELECT close FROM quotes_daily "
        "WHERE code = ? AND trade_date < ? "
        "ORDER BY trade_date DESC LIMIT 1",
        (plain, day),
    ).fetchone()
    if row is None:
        return None
    try:
        value = float(row["close"] if hasattr(row, "keys") else row[0])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return value if value > 0 and value == value else None


def _latest_trade_date(conn: _QuotesConn, code: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(trade_date) AS d FROM quotes_daily WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return None
    value = row["d"] if hasattr(row, "keys") else row[0]
    text = str(value or "").strip()[:10]
    return text or None


def adjust_ratio_on_date(
    store: Any,
    code: str,
    trade_date: str,
    adjust: MinuteAdjust,
) -> float:
    """与日 K ``history(..., adjust=)`` 同口径的单日价格乘数。

    前复权锚定该票库内**最新**交易日因子，避免只取目标日窗口时把 ratio 算成 1。
    """
    if adjust == "none":
        return 1.0
    day = str(trade_date or "").strip()[:10]
    if not day:
        return 1.0
    latest = _latest_trade_date(store.conn, code) or day
    dates = pd.Series([day, latest], dtype=str)
    factors = store._factor_series(code, dates)
    ratios = store._adjust_ratio(factors, adjust)
    value = float(ratios.iloc[0])
    if not (value > 0 and value == value):
        return 1.0
    return value


def apply_minute_adjust(
    store: Any,
    code: str,
    trade_date: str,
    frame: pd.DataFrame,
    *,
    adjust: MinuteAdjust,
    prev_close: float | None,
) -> tuple[pd.DataFrame, float | None]:
    """把分钟成交价缩放到与日 K 相同的复权口径；量/额保持原始。"""
    if frame is None or frame.empty or adjust == "none":
        return frame, prev_close

    day_ratio = adjust_ratio_on_date(store, code, trade_date, adjust)
    out = frame.copy()
    for col in _PRICE_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") * day_ratio

    adj_prev = prev_close
    if prev_close is not None and prev_close > 0:
        prev_day_row = store.conn.execute(
            "SELECT trade_date FROM quotes_daily "
            "WHERE code = ? AND trade_date < ? "
            "ORDER BY trade_date DESC LIMIT 1",
            (code, trade_date),
        ).fetchone()
        prev_day = (
            str(
                prev_day_row["trade_date"]
                if prev_day_row is not None and hasattr(prev_day_row, "keys")
                else (prev_day_row[0] if prev_day_row is not None else "")
            ).strip()[:10]
        )
        prev_ratio = (
            adjust_ratio_on_date(store, code, prev_day, adjust) if prev_day else day_ratio
        )
        adj_prev = float(prev_close) * prev_ratio
    return out, adj_prev


def fetch_minute_bars(
    code: str,
    *,
    period: str,
    days: int,
    trade_date: str | None,
) -> tuple[str, Any, str]:
    """规范化代码并从适配器读取分钟线，不写入行情库。"""
    from src.market.infrastructure.adapters import fetch_minute_routed
    from src.market.infrastructure.adapters.base import AdapterError
    from src.market.infrastructure.store import normalize_code
    from src.market.infrastructure.store_codes import MarketError

    try:
        normalized = normalize_code(code)
    except MarketError as exc:
        raise MinuteQueryError(str(exc)) from exc

    try:
        frame, source = fetch_minute_routed(
            normalized,
            period=period,
            days=days,
            trade_date=trade_date,
        )
    except AdapterError as exc:
        raise MinuteQueryError(str(exc)) from exc
    return normalized, frame, source
