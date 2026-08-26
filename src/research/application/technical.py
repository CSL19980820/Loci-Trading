"""本地行情上的研究技术维度计算。

这里只计算可由 ``MarketStore.history`` 重建的指标；估值、新闻和定性判断不在
这个模块里补值。
"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from src.research.domain.contract import DimensionResult, EvidenceRef
from src.research.domain.dimensions import get_dimension_spec


def _number(value: Any, *, digits: int = 6) -> int | float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return round(float(value), digits)
    return value


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence(
    *,
    source_id: str,
    as_of: str,
    payload: dict[str, Any],
    observed_at: str,
    title: str = "本地行情事实",
) -> EvidenceRef:
    return EvidenceRef(
        source_id=source_id,
        title=title,
        observed_at=observed_at,
        as_of=as_of,
        payload_sha256=_payload_hash(payload),
        quote=f"as_of={as_of}; market_revision-bound=true",
    )


def _series_value(row: pd.Series, name: str) -> int | float | str | None:
    value = row.get(name)
    if isinstance(value, str):
        return value
    return _number(value)


def indicator_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """计算 UZI 技术维度中可复现的常用指标。"""
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    for column in ("open", "high", "low", "close", "volume"):
        if column not in work:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    close = work["close"]
    high = work["high"]
    low = work["low"]
    volume = work["volume"].fillna(0.0)

    for window in (5, 10, 20, 60, 120, 200):
        work[f"ma{window}"] = close.rolling(window, min_periods=window).mean()

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    work["macd_dif"] = ema12 - ema26
    work["macd_dea"] = work["macd_dif"].ewm(span=9, adjust=False, min_periods=9).mean()
    work["macd_hist"] = (work["macd_dif"] - work["macd_dea"]) * 2

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    work["rsi14"] = 100 - (100 / (1 + rs))
    work.loc[(avg_loss == 0) & (avg_gain > 0), "rsi14"] = 100.0

    lowest = low.rolling(9, min_periods=9).min()
    highest = high.rolling(9, min_periods=9).max()
    span = (highest - lowest).replace(0, np.nan)
    rsv = (close - lowest) / span * 100
    work["kdj_k"] = rsv.ewm(com=2, adjust=False, min_periods=9).mean()
    work["kdj_d"] = work["kdj_k"].ewm(com=2, adjust=False, min_periods=9).mean()
    work["kdj_j"] = 3 * work["kdj_k"] - 2 * work["kdj_d"]

    direction = np.sign(delta.fillna(0.0))
    work["obv"] = (direction * volume).cumsum()
    work["williams_r"] = (highest - close) / span * -100
    work["volume_ratio20"] = volume / volume.rolling(20, min_periods=20).mean().replace(0, np.nan)

    ma50 = close.rolling(50, min_periods=50).mean()
    ma200 = work["ma200"]
    slope = ma50 - ma50.shift(20)
    work["stage"] = "未判定"
    ready = close.notna() & ma200.notna() & slope.notna()
    work.loc[ready & (close > ma200) & (ma50 > ma200) & (slope > 0), "stage"] = "上升"
    work.loc[ready & (close < ma200) & (ma50 < ma200) & (slope < 0), "stage"] = "下降"
    work.loc[ready & ~work["stage"].isin(["上升", "下降"]), "stage"] = "震荡"

    vol20 = close.pct_change().rolling(20, min_periods=20).std()
    vol60 = close.pct_change().rolling(60, min_periods=60).std()
    work["vcp_possible"] = (vol20 < vol60 * 0.75) & (close >= work["ma20"])
    return work


def build_basic_dimension(
    instrument: dict[str, Any] | None,
    latest: dict[str, Any] | None,
    *,
    observed_at: str,
) -> DimensionResult:
    spec = get_dimension_spec("0_basic")
    instrument = instrument or {}
    latest = latest or {}
    as_of = str(latest.get("trade_date") or "")
    values: dict[str, Any] = {
        "code": str(instrument.get("code") or latest.get("code") or ""),
        "name": str(instrument.get("name") or ""),
        "market": str(instrument.get("market") or ""),
        "board": str(instrument.get("board") or ""),
        "industry": str(instrument.get("industry") or ""),
        "status": str(instrument.get("status") or ""),
        "list_date": str(instrument.get("list_date") or ""),
        "close": _number(latest.get("close")),
        "turnover": _number(latest.get("turnover")),
        "as_of": as_of,
    }
    gaps = [
        field for field in ("industry", "close", "as_of")
        if values.get(field) in (None, "")
    ]
    # PE/PB/市值等 UZI 字段没有被本地行情仓接入，必须保留 partial。
    gaps.extend(["pe", "pb", "market_cap", "eps"])
    payload = {key: values.get(key) for key in ("code", "close", "industry", "as_of")}
    evidence = ()
    if values["code"] and (values["close"] is not None or instrument):
        evidence = (_evidence(
            source_id="market.db",
            as_of=as_of,
            payload=payload,
            observed_at=observed_at,
        ),)
    return DimensionResult(
        key=spec.key,
        name=spec.name,
        quality="partial" if values["code"] else "missing",
        source="market.db" if evidence else "",
        retrieved_at=observed_at,
        as_of=as_of,
        data_gaps=tuple(gaps),
        values=values,
        evidence=evidence,
    )


def build_kline_dimension(
    frame: pd.DataFrame,
    *,
    observed_at: str,
    market_revision: str,
) -> DimensionResult:
    spec = get_dimension_spec("2_kline")
    if frame.empty:
        return DimensionResult(
            key=spec.key,
            name=spec.name,
            quality="missing",
            source="",
            retrieved_at=observed_at,
            as_of="",
            data_gaps=("market.db 没有该标的历史日 K",),
        )

    calculated = indicator_frame(frame)
    row = calculated.iloc[-1]
    as_of = str(row.get("trade_date") or calculated.index[-1] or "")
    if not as_of or as_of == "nan":
        as_of = str(calculated.index[-1])
    scalar_names = (
        "open", "high", "low", "close", "volume", "turnover",
        "ma5", "ma10", "ma20", "ma60", "ma120", "ma200",
        "macd_dif", "macd_dea", "macd_hist", "rsi14",
        "kdj_k", "kdj_d", "kdj_j", "obv", "williams_r", "volume_ratio20",
    )
    values: dict[str, Any] = {name: _series_value(row, name) for name in scalar_names}
    values["stage"] = str(row.get("stage") or "未判定")
    values["vcp_possible"] = bool(row.get("vcp_possible")) if not pd.isna(row.get("vcp_possible")) else False
    values["bars"] = int(len(calculated))
    values["adjust"] = "qfq"
    values["method_notes"] = {
        "rsi14": "Wilder-style exponential smoothing",
        "stage": "本地启发式四阶段标签，不是 UZI 评分",
        "vcp_possible": "波动率收缩代理，需要人工复核",
    }
    gaps = [name for name in ("ma200", "rsi14", "macd_hist") if values.get(name) is None]
    if len(calculated) < 200:
        gaps.append("历史不足 200 根，MA200/Stage 可能不完整")
    recent_columns = ["trade_date", "close", "volume", "ma20", "rsi14", "macd_hist"]
    recent = calculated.tail(60).copy()
    recent["trade_date"] = recent.get("trade_date", recent.index.astype(str)).astype(str)
    values["recent"] = [
        {column: _series_value(item, column) for column in recent_columns}
        for _, item in recent.iterrows()
    ]
    payload = {
        "as_of": as_of,
        "bars": len(calculated),
        "close": values.get("close"),
        "rsi14": values.get("rsi14"),
        "macd_hist": values.get("macd_hist"),
        "market_revision": market_revision,
    }
    evidence = (_evidence(
        source_id="market.db",
        as_of=as_of,
        payload=payload,
        observed_at=observed_at,
        title="本地行情与可重建技术指标",
    ),)
    return DimensionResult(
        key=spec.key,
        name=spec.name,
        quality="full" if len(calculated) >= 200 and not gaps else "partial",
        source="market.db",
        retrieved_at=observed_at,
        as_of=as_of,
        data_gaps=tuple(gaps),
        values=values,
        evidence=evidence,
    )

