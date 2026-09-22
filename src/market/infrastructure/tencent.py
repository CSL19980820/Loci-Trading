"""直接对接腾讯财经公开 HTTP 接口。

日线优先 QQ 财经反代 ``proxy.finance.qq.com``（JSON，单次最多 640 根，需分页）；
直连 ``web.ifzq.gtimg.cn`` 常被 WAF 拦成 501 或握手超时，只作快败备源。
近窗再不行才走 ``data.gtimg.cn`` flashdata。现价 / live 走 ``qt.gtimg.cn``。
符号与新浪相同：``sh600519``。
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
import json
import logging
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

logger = logging.getLogger(__name__)

#: web.ifzq.gtimg.cn 会被腾讯 WAF 拦成 501；走 QQ 财经反代。
DAILY_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"
#: 同一反代主机的不复权 path；主 path 被 WAF/5xx 时不必换域名。
DAILY_URL_PROXY_KLINE = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/kline"
#: 直连 ifzq。主机经常握手超时，必须快败，不能按 6s×2 死磕。
DAILY_URL_FALLBACK = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
DAILY_IFZQ_URLS: tuple[str, ...] = (
    DAILY_URL,
    DAILY_URL_PROXY_KLINE,
    DAILY_URL_FALLBACK,
)
FLASHDATA_LATEST_TMPL = "https://data.gtimg.cn/flashdata/hushen/latest/daily/{symbol}.js"
#: flashdata 各板块都是「手」；ifzq 日 K 对科创板已经是股。
FLASHDATA_LOT_SCALE = 100.0
#: 直连 ifzq 的握手上限。WAF/黑洞时 6s 重试只会拖死盘中增量。
IFZQ_CONNECT_TIMEOUT = 2.0
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


def _url_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_direct_ifzq(url: str) -> bool:
    return "ifzq.gtimg.cn" in _url_host(url)


def _is_connect_failure(exc: BaseException) -> bool:
    text = str(exc)
    return any(
        token in text
        for token in (
            "ConnectTimeout",
            "ConnectTimeoutError",
            "ConnectionError",
            "Connection refused",
            "NewConnectionError",
            "NameResolutionError",
        )
    )


def _get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    connect_timeout: float | None = None,
    retries: int | None = None,
) -> str:
    from src.market.infrastructure.http_client import market_get, market_session

    kwargs: dict[str, Any] = {
        "params": params,
        "headers": HEADERS,
        "timeout": timeout,
        "session": session or market_session(),
    }
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    if retries is not None:
        kwargs["retries"] = retries
    try:
        response = market_get(url, **kwargs)
    except Exception as exc:
        raise TencentFetchError(f"请求失败：{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise TencentFetchError(f"返回 {response.status_code}")
    return _decode_text(response)


def volume_scale(symbol: str) -> float:
    """腾讯成交量 → 股 的换算系数；单位按板块而异，不能一刀切当「手」。

    实测 2026-08-11：日 K ``day`` 末根的成交量与现价接口第 36 列**逐票完全相等**，
    两个接口是同一口径。用现价第 35 列的成交额除以现价反推真实股数：
    主板 / 创业板 / 北交所 / ETF / 指数比值约 100（源侧是「手」），
    科创板（688/689）比值约 1（源侧已经是「股」），再 ×100 会把成交量与隐含换手率
    整整放大 100 倍。
    """
    from src.market.domain.universe import classify_board

    code = str(symbol).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix):
            code = code[len(prefix) :]
            break
    return 1.0 if classify_board(code) == "star" else 100.0


#: 旧名：这套系数原本只用在日 K 上，现价接口同口径后沿用同一函数。
daily_volume_scale = volume_scale


def _parse_daily_rows(
    raw_rows: list[list[Any]], *, volume_scale: float = 100.0
) -> pd.DataFrame:
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
            volume_src = float(item[5])
        except (TypeError, ValueError):
            continue
        trade_date = pd.to_datetime(str(item[0]), errors="coerce")
        if pd.isna(trade_date):
            continue
        # 统一成「股」与新浪对齐；缩放系数按板块由 volume_scale 决定。
        volume = volume_src * volume_scale
        # 此接口未提供成交额；未知值必须留空，不能用收盘价伪造全天 VWAP。
        amount = None
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


def _day_rows_from_block(block: object) -> list[Any]:
    """不复权 ``day`` 优先；个别 fqkline 只给 qfqday/hfqday 时再降级。"""
    if not isinstance(block, dict):
        return []
    for key in ("day", "qfqday", "hfqday"):
        rows = block.get(key)
        if isinstance(rows, list) and rows:
            return rows
    return []


def _parse_flashdata(text: str) -> pd.DataFrame:
    """腾讯 flashdata：``YYMMDD open close high low volume``，量单位为手。"""
    cleaned = text.strip()
    if "start=" in cleaned[:80] or cleaned.startswith("daily_"):
        _, _, rest = cleaned.partition("=")
        if rest:
            cleaned = rest.strip().strip(";").strip("'").strip('"')
    cleaned = cleaned.replace("\\n", "\n")
    rows: list[dict[str, Any]] = []
    for line in cleaned.splitlines():
        line = line.strip().strip("'").strip()
        if not line or line.startswith("start"):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        stamp = parts[0]
        if len(stamp) == 6 and stamp.isdigit():
            year = 1900 + int(stamp[:2]) if int(stamp[:2]) >= 90 else 2000 + int(stamp[:2])
            raw_date = f"{year:04d}{stamp[2:]}"
        elif len(stamp) == 8 and stamp.isdigit():
            raw_date = stamp
        else:
            continue
        trade_date = pd.to_datetime(raw_date, format="%Y%m%d", errors="coerce")
        if pd.isna(trade_date):
            continue
        try:
            open_ = float(parts[1])
            close = float(parts[2])
            high = float(parts[3])
            low = float(parts[4])
            volume = float(parts[5]) * FLASHDATA_LOT_SCALE
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "date": trade_date.date(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": None,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "amount"]
        )
    return pd.DataFrame(rows)


def _fetch_flashdata_latest(
    symbol: str, *, count: int, session: requests.Session | None = None
) -> tuple[pd.DataFrame, int]:
    text = _get(FLASHDATA_LATEST_TMPL.format(symbol=symbol), session=session)
    frame = _parse_flashdata(text)
    if frame.empty:
        raise TencentFetchError(f"{symbol} flashdata 为空")
    frame = frame.sort_values("date").reset_index(drop=True)
    if count and len(frame) > count:
        frame = frame.tail(int(count)).reset_index(drop=True)
    return frame, int(len(frame))


def _fetch_daily_page(
    symbol: str,
    *,
    end_date: str = "",
    count: int = DAILY_PAGE_SIZE,
    session: requests.Session | None = None,
) -> tuple[pd.DataFrame, int]:
    """拉一页不复权日 K，返回 (归一表, 源侧原始行数)。

    原始行数要单独回报：解析会丢掉脏行，拿 ``len(frame)`` 判断「这是最后
    一页」会把更早的历史整段截断。``end_date`` 为空表示截至最新。
    """
    symbol = str(symbol).strip().lower()
    if not symbol:
        raise TencentFetchError("symbol 为空")
    count = max(1, min(int(count), DAILY_PAGE_SIZE))
    param = f"{symbol},day,,{end_date},{count},"
    last_error: Exception | None = None
    text: str | None = None
    dead_hosts: set[str] = set()
    for url in DAILY_IFZQ_URLS:
        host = _url_host(url)
        if host in dead_hosts:
            continue
        try:
            extra: dict[str, Any] = {}
            if _is_direct_ifzq(url):
                extra = {"connect_timeout": IFZQ_CONNECT_TIMEOUT, "retries": 0}
            text = _get(url, params={"param": param}, session=session, **extra)
            break
        except TencentFetchError as exc:
            last_error = exc
            # 握手都失败时同 host 另一条 path 不会突然通，换 CDN 比再等 12s 有用。
            if _is_connect_failure(exc) and host:
                dead_hosts.add(host)
    if text is None:
        if not end_date:
            try:
                return _fetch_flashdata_latest(symbol, count=count, session=session)
            except TencentFetchError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise TencentFetchError(f"{symbol} JSON 解析失败") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (0, "0", None):
        raise TencentFetchError(f"{symbol} 接口返回异常")
    block = (payload.get("data") or {}).get(symbol) or {}
    day_rows = _day_rows_from_block(block)
    if not day_rows:
        raise TencentFetchError(f"{symbol} 无 day 字段")
    frame = _parse_daily_rows(day_rows, volume_scale=volume_scale(symbol))
    return frame, len(day_rows)


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
    previous_earliest: date | None = None
    while True:
        chunk, raw_rows = _fetch_daily_page(symbol, end_date=end_date, session=session)
        if not chunk.empty:
            pages.append(chunk)
        if raw_rows < DAILY_PAGE_SIZE:
            break
        earliest = chunk["date"].min() if not chunk.empty else None
        if not isinstance(earliest, date):
            break
        if previous_earliest is not None and earliest >= previous_earliest:
            # 源忽略了 end_date（只回最新一页），再翻下去就是无限循环。
            break
        previous_earliest = earliest
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
    frame, _raw_rows = _fetch_daily_page(symbol, count=count, session=session)
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


def _spot_volume_shares(fields: Sequence[str], symbol: str) -> float | None:
    """成交量 → 股；解析不出来返回 ``None``。第 36 列与日 K 同口径，系数按板块取。

    以前失败回 0.0，与「集合竞价还没成交」（源侧确实是 "0"）无法区分：一根
    量为 0 却有成交额的当日 bar 会被当成真实零成交，量比 / 换手 / 放量形态全错。
    """
    if len(fields) <= 36:
        return None
    try:
        return float(fields[36]) * volume_scale(symbol)
    except ValueError:
        return None


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
    volume = _spot_volume_shares(fields, symbol)
    amount = _spot_amount(fields)
    if volume is None:
        return None  # 量字段读不出来时不落 bar，宁缺勿假
    # 停牌 / 尚未成交的票只回昨收，量额皆 0。这条通道产出的是**当日日 K**，
    # 零成交却落一根 bar，等于凭空给这只票多记一个交易日（live 通道不受此限）。
    if volume <= 0 and amount <= 0:
        return None
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
        # live 只上屏、不落库：量读不出来时留 0 保住报价行，不会污染日 K。
        volume = _spot_volume_shares(fields, symbol) or 0.0
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
    # 腾讯盘口数量为手（含科创板），与其日K成交量的板块口径不同。
    book = {}
    for key, index, scale in (("bid_price", 9, 1), ("bid_quantity", 10, 100),
                              ("ask_price", 19, 1), ("ask_quantity", 20, 100),
                              ("limit_up", 47, 1), ("limit_down", 48, 1)):
        try:
            book[key] = float(fields[index]) * scale
        except (ValueError, IndexError):
            book[key] = None  # 缺字段不能伪装成零卖盘或无涨跌停限制。
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
        **book,
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
    failures: list[str] = []
    batches = 0
    try:
        for start in range(0, len(clean), SPOT_BATCH_SIZE):
            batch = clean[start : start + SPOT_BATCH_SIZE]
            batches += 1
            try:
                text = _get(SPOT_URL + ",".join(batch), session=sess)
            except TencentFetchError as exc:
                failures.append(str(exc))
                logger.warning("腾讯 live 批次失败：%s", exc)
                continue
            for chunk in text.split(";"):
                row = _parse_live_row(chunk)
                if row:
                    out.append(row)
    finally:
        if own_session:
            sess.close()
    if batches and len(failures) == batches:
        # 全批失败还返回空表，上层只会报「行情为空」，把真正的网络原因吞掉。
        raise TencentFetchError(f"live {batches} 批全部失败 -> {failures[-1]}")
    return out
