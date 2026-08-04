"""直接对接腾讯财经公开 HTTP 接口。

日线走 ``web.ifzq.gtimg.cn``（JSON，单次最多 640 根，需分页拼全历史）；
现价 / live 走 ``qt.gtimg.cn``（~ 分隔文本）。符号与新浪相同：``sh600519``。
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
import json
import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

#: web.ifzq.gtimg.cn 会被腾讯 WAF 拦成 501；走 QQ 财经反代。
DAILY_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"
#: 备用（部分网络反代也不稳时）。
DAILY_URL_FALLBACK = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
SPOT_URL = "https://qt.gtimg.cn/q="
#: gtimg 单次 URL 长度有限，批量宜 80~100。
SPOT_BATCH_SIZE = 80
#: 腾讯日 K 单次上限。
DAILY_PAGE_SIZE = 640

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://finance.qq.com/",
}

DEFAULT_TIMEOUT = 20


class TencentFetchError(RuntimeError):
    """腾讯取数失败。"""


def _decode_text(response: requests.Response) -> str:
    """qt.gtimg.cn 常见 GBK；JSON 接口走 UTF-8。"""
    ctype = (response.headers.get("Content-Type") or "").lower()
    if "json" in ctype:
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    for encoding in ("gbk", "gb18030", "utf-8"):
        try:
            return response.content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return response.content.decode("utf-8", errors="replace")


def _get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> str:
    from src.market.infrastructure.http_client import market_get, market_session

    try:
        response = market_get(
            url,
            params=params,
            headers=HEADERS,
            timeout=DEFAULT_TIMEOUT,
            session=session or market_session(),
        )
    except Exception as exc:
        raise TencentFetchError(f"请求失败：{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise TencentFetchError(f"返回 {response.status_code}")
    return _decode_text(response)


def _parse_daily_rows(raw_rows: list[list[Any]]) -> pd.DataFrame:
    """腾讯日 K 行：[date, open, close, high, low, volume(, 分红dict)]。"""
    rows: list[dict[str, Any]] = []
    for item in raw_rows:
        if not item or len(item) < 6:
            continue
        try:
            open_ = float(item[1])
            close = float(item[2])
            high = float(item[3])
            low = float(item[4])
            volume_lots = float(item[5])
        except (TypeError, ValueError):
            continue
        trade_date = pd.to_datetime(str(item[0]), errors="coerce")
        if pd.isna(trade_date):
            continue
        # 成交量单位为「手」，与新浪「股」对齐。
        volume = volume_lots * 100.0
        amount = close * volume
        rows.append(
            {
                "date": trade_date.date(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "amount"]
        )
    return pd.DataFrame(rows)


def _fetch_daily_page(
    symbol: str,
    *,
    end_date: str = "",
    count: int = DAILY_PAGE_SIZE,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """拉一页不复权日 K。``end_date`` 为空表示截至最新。"""
    symbol = str(symbol).strip().lower()
    if not symbol:
        raise TencentFetchError("symbol 为空")
    count = max(1, min(int(count), DAILY_PAGE_SIZE))
    param = f"{symbol},day,,{end_date},{count},"
    last_error: Exception | None = None
    for url in (DAILY_URL, DAILY_URL_FALLBACK):
        try:
            text = _get(url, params={"param": param}, session=session)
            break
        except TencentFetchError as exc:
            last_error = exc
            # WAF 501 / 网关错误才换备用；其它错误直接抛
            if "501" not in str(exc) and "502" not in str(exc) and "503" not in str(exc):
                raise
    else:
        assert last_error is not None
        raise last_error
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise TencentFetchError(f"{symbol} JSON 解析失败") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (0, "0", None):
        raise TencentFetchError(f"{symbol} 接口返回异常")
    block = (payload.get("data") or {}).get(symbol) or {}
    day_rows = block.get("day") or []
    if not isinstance(day_rows, list):
        raise TencentFetchError(f"{symbol} 无 day 字段")
    return _parse_daily_rows(day_rows)


def fetch_daily(
    symbol: str, *, session: requests.Session | None = None
) -> pd.DataFrame:
    """取单只证券**不复权**全历史日线。

    symbol 形如 ``sh600519``。返回列：
    date/open/high/low/close/volume/amount。
    """
    symbol = str(symbol).strip().lower()
    pages: list[pd.DataFrame] = []
    end_date = ""
    while True:
        chunk = _fetch_daily_page(symbol, end_date=end_date, session=session)
        if chunk.empty:
            break
        pages.append(chunk)
        if len(chunk) < DAILY_PAGE_SIZE:
            break
        earliest = chunk["date"].min()
        if not isinstance(earliest, date):
            break
        end_date = (earliest - timedelta(days=1)).strftime("%Y-%m-%d")

    if not pages:
        raise TencentFetchError(f"{symbol} 无历史数据")

    merged = (
        pd.concat(pages, ignore_index=True)
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return merged


def fetch_daily_recent(
    symbol: str,
    *,
    count: int = 30,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """探测 / 小窗口：只拉最近 ``count`` 根（<=640）。"""
    frame = _fetch_daily_page(symbol, count=count, session=session)
    if frame.empty:
        raise TencentFetchError(f"{symbol} 近期日线为空")
    return frame.reset_index(drop=True)


def _split_spot_line(line: str) -> tuple[str, list[str]] | None:
    text = line.strip().rstrip(";")
    if not text or "~" not in text or "=" not in text:
        return None
    left, _, right = text.partition("=")
    symbol = left.strip()
    if symbol.startswith("v_"):
        symbol = symbol[2:]
    payload = right.strip().strip('"').strip("'")
    if not symbol or not payload:
        return None
    fields = payload.split("~")
    if len(fields) < 35:
        return None
    return symbol.lower(), fields


def _spot_amount(fields: Sequence[str]) -> float:
    """成交额：优先 slash 字段第三段，否则 37 列（万元）× 1e4。"""
    combo = str(fields[35]) if len(fields) > 35 else ""
    if combo and "/" in combo:
        parts = combo.split("/")
        if len(parts) >= 3:
            try:
                return float(parts[2])
            except ValueError:
                pass
    if len(fields) > 37:
        try:
            return float(fields[37]) * 10000.0
        except ValueError:
            pass
    return 0.0


def _spot_volume_shares(fields: Sequence[str]) -> float:
    """成交量：36 列为手，×100 变股。"""
    if len(fields) <= 36:
        return 0.0
    try:
        return float(fields[36]) * 100.0
    except ValueError:
        return 0.0


def _parse_spot_row(line: str) -> dict[str, Any] | None:
    parsed = _split_spot_line(line)
    if not parsed:
        return None
    symbol, fields = parsed
    try:
        open_ = float(fields[5])
        prev = float(fields[4])
        close = float(fields[3])
        high = float(fields[33])
        low = float(fields[34])
    except ValueError:
        return None
    if close <= 0 and open_ <= 0:
        return None
    if close <= 0:
        close = open_
    if high <= 0:
        high = max(open_, close)
    if low <= 0:
        low = min(open_, close) if open_ > 0 else close
    volume = _spot_volume_shares(fields)
    amount = _spot_amount(fields)
    stamp = str(fields[30]) if len(fields) > 30 else ""
    trade_date = pd.to_datetime(stamp[:8], format="%Y%m%d", errors="coerce")
    if pd.isna(trade_date):
        return None
    _ = prev  # 现价解析保留，供 live 复用
    return {
        "symbol": symbol,
        "date": trade_date.date(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
    }


def fetch_spot(
    symbols: Sequence[str], *, session: requests.Session | None = None
) -> pd.DataFrame:
    """批量现价 → 与 sina.fetch_spot 同形（symbol/date/OHLCV/amount）。"""
    clean = [str(symbol).strip().lower() for symbol in symbols if str(symbol).strip()]
    if not clean:
        return pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
        )

    rows: list[dict[str, Any]] = []
    for start in range(0, len(clean), SPOT_BATCH_SIZE):
        batch = clean[start : start + SPOT_BATCH_SIZE]
        text = _get(SPOT_URL + ",".join(batch), session=session)
        for chunk in text.split(";"):
            row = _parse_spot_row(chunk)
            if row:
                rows.append(row)
    return pd.DataFrame(rows)


def _parse_live_row(line: str) -> dict[str, Any] | None:
    parsed = _split_spot_line(line)
    if not parsed:
        return None
    symbol, fields = parsed
    try:
        name = str(fields[1]).strip()
        open_ = float(fields[5])
        prev = float(fields[4])
        price = float(fields[3])
        high = float(fields[33])
        low = float(fields[34])
        volume = _spot_volume_shares(fields)
        amount = _spot_amount(fields)
        change = float(fields[31]) if len(fields) > 31 else price - prev
        pct = float(fields[32]) if len(fields) > 32 else (
            (change / prev * 100.0) if prev else 0.0
        )
    except ValueError:
        return None
    if price <= 0 and open_ <= 0:
        return None
    if price <= 0:
        price = open_
    if prev <= 0:
        prev = open_ if open_ > 0 else price
    stamp = str(fields[30]) if len(fields) > 30 else ""
    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 3),
        "prev_close": round(prev, 3),
        "open": round(open_, 3),
        "high": round(high, 3),
        "low": round(low, 3),
        "change": round(price - prev, 3),
        "pct": round(pct, 2),
        "volume": volume,
        "amount": amount,
        "trade_date": stamp[:8] if len(stamp) >= 8 else stamp,
        "trade_time": stamp[8:] if len(stamp) > 8 else "",
        "source": "tencent",
    }


def fetch_live_hq(
    symbols: Sequence[str], *, session: requests.Session | None = None
) -> list[dict[str, Any]]:
    """批量 live 行情；单批失败记日志并继续。"""
    clean = [str(symbol).strip().lower() for symbol in symbols if str(symbol).strip()]
    if not clean:
        return []

    from src.market.infrastructure.http_client import market_session

    own_session = session is None
    sess = session or market_session()
    if own_session:
        sess.headers.update(HEADERS)

    out: list[dict[str, Any]] = []
    try:
        for start in range(0, len(clean), SPOT_BATCH_SIZE):
            batch = clean[start : start + SPOT_BATCH_SIZE]
            try:
                text = _get(SPOT_URL + ",".join(batch), session=sess)
            except TencentFetchError as exc:
                logger.warning("腾讯 live 批次失败：%s", exc)
                continue
            for chunk in text.split(";"):
                row = _parse_live_row(chunk)
                if row:
                    out.append(row)
    finally:
        if own_session:
            sess.close()
    return out
