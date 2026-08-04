"""东财分钟线直连（绕开 akshare）。

``push2his`` 历史通道偶发断连时依次尝试 ``push2delay``；1 分钟指定交易日走 kline，
近窗走 trends2（最多约 5 日）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
import time
from typing import Any

import pandas as pd

from src.market.infrastructure.store_codes import normalize_code


class EastmoneyMinuteError(RuntimeError):
    """东财分钟线取数失败。"""


_HOSTS = (
    "https://push2his.eastmoney.com",
    "https://push2delay.eastmoney.com",
)
_UT = "fa5fd1943c7b386f172d6893dbfba10b"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}
_PERIODS = frozenset({"1", "5", "15", "30", "60"})
_RETRIES = 2


def _secid(code: str) -> str:
    plain = normalize_code(code)
    market = 1 if plain.startswith("6") else 0
    return f"{market}.{plain}"


def _get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    from src.market.infrastructure.http_client import market_get, market_session

    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            response = market_get(
                url,
                params=params,
                headers=_HEADERS,
                timeout=20,
                session=market_session(),
            )
            if response.status_code != 200:
                raise EastmoneyMinuteError(f"HTTP {response.status_code}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise EastmoneyMinuteError("响应非 JSON 对象")
            return payload
        except EastmoneyMinuteError:
            raise
        except Exception as exc:
            last = exc
            if attempt + 1 < _RETRIES:
                time.sleep(0.35 * (attempt + 1))
    assert last is not None
    raise EastmoneyMinuteError(f"{type(last).__name__}: {last}") from last


def _rows_from_csv(
    lines: list[str],
    *,
    has_avg: bool,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for line in lines:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        row: dict[str, Any] = {
            "datetime": parts[0],
            "open": parts[1],
            "close": parts[2],
            "high": parts[3],
            "low": parts[4],
            "volume": parts[5],
            "amount": parts[6],
        }
        if has_avg and len(parts) >= 8:
            row["avg_price"] = parts[7]
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=[
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "avg_price",
            ]
        )
    out = pd.DataFrame(rows)
    for col in ("open", "high", "low", "close", "volume", "amount", "avg_price"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "avg_price" not in out.columns or out["avg_price"].isna().all():
        # kline 成交量单位为「手」，成交额为元 → VWAP = 额/(量*100)。
        volume = out["volume"]
        amount = out["amount"]
        out["avg_price"] = (amount / (volume * 100.0)).where(volume > 0)
    else:
        out["avg_price"] = _sanitize_avg_price(out["avg_price"], out["close"])
    return out[
        ["datetime", "open", "high", "low", "close", "volume", "amount", "avg_price"]
    ].reset_index(drop=True)


def _sanitize_avg_price(avg: pd.Series, close: pd.Series) -> pd.Series:
    """trends 偶发把振幅等字段当均价；相对收盘偏离过大时按 100 倍回正或置空。"""
    ratio = avg / close.replace(0, pd.NA)
    # 典型误用：手未换算 → 约 100×；振幅百分比字段也会远偏离价格。
    scaled = avg.where(~(ratio > 20), avg / 100.0)
    ratio2 = scaled / close.replace(0, pd.NA)
    return scaled.where((ratio2 > 0.2) & (ratio2 < 5.0))


def _fetch_kline(secid: str, *, period: str, day: str) -> pd.DataFrame:
    ymd = day.replace("-", "")
    errors: list[str] = []
    for host in _HOSTS:
        url = f"{host}/api/qt/stock/kline/get"
        try:
            payload = _get_json(
                url,
                {
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "ut": _UT,
                    "klt": period,
                    "fqt": "0",
                    "secid": secid,
                    "beg": ymd,
                    "end": ymd,
                },
            )
        except EastmoneyMinuteError as exc:
            errors.append(f"{host.split('//')[1]}: {exc}")
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        klines = data.get("klines") if data else None
        if not isinstance(klines, list) or not klines:
            errors.append(f"{host.split('//')[1]}: 空 kline")
            continue
        frame = _rows_from_csv([str(x) for x in klines], has_avg=False)
        # 部分主机忽略 beg/end，只回最近一日——按目标日过滤。
        mask = frame["datetime"].astype(str).str.startswith(day)
        frame = frame.loc[mask].reset_index(drop=True)
        if frame.empty:
            errors.append(f"{host.split('//')[1]}: 无 {day}")
            continue
        return frame
    raise EastmoneyMinuteError(" | ".join(errors[-4:]) or "kline 失败")


def _fetch_trends(secid: str, *, ndays: int) -> pd.DataFrame:
    errors: list[str] = []
    for host in _HOSTS:
        url = f"{host}/api/qt/stock/trends2/get"
        try:
            payload = _get_json(
                url,
                {
                    "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                    "ut": _UT,
                    "ndays": str(max(1, min(5, ndays))),
                    "iscr": "0",
                    "secid": secid,
                },
            )
        except EastmoneyMinuteError as exc:
            errors.append(f"{host.split('//')[1]}: {exc}")
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        trends = data.get("trends") if data else None
        if not isinstance(trends, list) or not trends:
            errors.append(f"{host.split('//')[1]}: 空 trends")
            continue
        return _rows_from_csv([str(x) for x in trends], has_avg=True)
    raise EastmoneyMinuteError(" | ".join(errors[-4:]) or "trends 失败")


def fetch_minute_bars(
    code: str,
    *,
    period: str = "1",
    days: int = 1,
    trade_date: str | None = None,
) -> pd.DataFrame:
    """返回归一列：datetime/OHLC/volume/amount/avg_price。"""
    plain = normalize_code(code)
    scale = str(period).strip()
    if scale not in _PERIODS:
        raise EastmoneyMinuteError(f"不支持的分钟周期：{period}")
    secid = _secid(plain)
    day = (trade_date or "").strip()[:10]

    if day:
        # 指定交易日：优先历史 kline（可跨月）；失败再 trends 近窗过滤。
        try:
            return _fetch_kline(secid, period=scale, day=day)
        except EastmoneyMinuteError as kline_exc:
            if scale != "1":
                raise EastmoneyMinuteError(
                    f"{plain} 在 {day} 无分钟线（{kline_exc}）"
                ) from kline_exc
            try:
                frame = _fetch_trends(secid, ndays=5)
            except EastmoneyMinuteError as trends_exc:
                raise EastmoneyMinuteError(
                    f"{plain} 在 {day} 无分钟线；历史通道：{kline_exc}；"
                    f"近窗：{trends_exc}"
                ) from trends_exc
            out = frame.loc[frame["datetime"].astype(str).str.startswith(day)].reset_index(
                drop=True
            )
            if out.empty:
                raise EastmoneyMinuteError(
                    f"{plain} 在 {day} 无分钟线（近窗 trends 不含该日；"
                    f"历史 kline：{kline_exc}）"
                )
            return out

    window_days = max(1, int(days))
    frame = _fetch_trends(secid, ndays=window_days)
    end = datetime.now()
    # 分钟行情按交易日使用；收盘后访问“近 1 日”时，最近交易日的
    # 09:30 可能已经超过严格 24 小时，不能因此把整天数据判成空。
    start = end - timedelta(days=window_days)
    stamps = pd.to_datetime(frame["datetime"], errors="coerce")
    out = frame.loc[
        (stamps.dt.date >= start.date()) & (stamps <= end)
    ].reset_index(drop=True)
    if out.empty:
        raise EastmoneyMinuteError(f"{plain} 分钟线窗口为空")
    return out
