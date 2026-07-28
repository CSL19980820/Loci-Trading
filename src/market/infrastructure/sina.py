"""直接对接新浪历史行情，绕开 akshare 的并发陷阱。

## 为什么不直接用 akshare

``ak.stock_zh_a_daily`` 每次调用都 ``py_mini_racer.MiniRacer()`` 新建一个
V8 isolate 来跑解密 JS。多线程并发下 V8 的地址空间初始化会撞车：

    [FATAL:partition_address_space.cc(243)]
    Check failed: !IsConfigurablePoolInitialized().

这不是 Python 异常——是**整个进程被原生代码直接打死**，连 traceback 都
没有，正在跑的全市场回填全部丢失。实测 5 并发跑到几百只时必然复现。

## 这里怎么做

拆开两件事：

- **HTTP 自己发**，可以放心并发——网络 IO 占了每次调用 300ms 里的绝大部分。
- **JS 解码走一个全局唯一、加锁的 MiniRacer 实例**。解码只要几毫秒，
  串行化几乎不影响吞吐，而竞态被彻底消除。

顺带把 ``outstanding_share`` 的解析从 demjson 换成标准 json——实测新浪
返回的就是合法 JSON，没必要多背一个宽松解析器。
"""
from __future__ import annotations

from collections.abc import Sequence
import json
import logging
import threading
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

HIST_URL = "https://finance.sina.com.cn/realstock/company/{}/hisdata_klc2/klc_kl.js"
AMOUNT_URL = (
    "https://stock.finance.sina.com.cn/stock/api/jsonp.php/"
    "var%20KKE_ShareAmount_{}=/StockService.getAmountBySymbol?_=20&symbol={}"
)
#: 复权因子。响应形如
#: ``var sh600519hfq={"total":33,"data":[{"d":"2026-06-26","f":"8.88..."},...]}``
FACTOR_URL = "https://finance.sina.com.cn/realstock/company/{}/{}.js"
#: 实时行情。历史日 K（hisdata_klc2）盘中/盘后早期不含当日，
#: 当日 OHLC 要从这里补——字段：开/昨收/现/高/低/.../量/额/.../日期/时间。
SPOT_URL = "https://hq.sinajs.cn/list={}"
SPOT_BATCH_SIZE = 400

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

DEFAULT_TIMEOUT = 20

#: 全局唯一的 JS 运行时与它的锁。整个进程只此一份。
_JS_LOCK = threading.Lock()
_JS_RUNTIME: Any = None


class SinaFetchError(RuntimeError):
    """新浪取数失败。"""


def _decode_kline(payload: str) -> list[dict[str, Any]]:
    """用共享的 V8 实例解密 K 线串。

    锁的粒度刻意只包住 JS 调用，不包 HTTP——否则并发就白做了。
    """
    global _JS_RUNTIME
    with _JS_LOCK:
        if _JS_RUNTIME is None:
            try:
                import py_mini_racer
                from akshare.stock.cons import hk_js_decode
            except ImportError as exc:  # pragma: no cover - 依赖缺失路径
                raise SinaFetchError(f"缺少解码依赖：{exc.name}") from exc
            runtime = py_mini_racer.MiniRacer()
            runtime.eval(hk_js_decode)
            _JS_RUNTIME = runtime
        return _JS_RUNTIME.call("d", payload)


def _get(url: str, session: requests.Session | None = None) -> str:
    caller = session or requests
    try:
        response = caller.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
    except Exception as exc:
        raise SinaFetchError(f"请求失败：{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise SinaFetchError(f"返回 {response.status_code}")
    return response.text


def fetch_daily(symbol: str, *, session: requests.Session | None = None) -> pd.DataFrame:
    """取单只证券的**不复权**日线。

    symbol 形如 ``sh600519``。返回列：
    date/open/high/low/close/volume/amount/outstanding_share/turnover

    注意：历史接口通常**不含当日未收盘/刚收盘的那根**；要当日 bar 请用
    ``fetch_spot``，由同步层拼到日线上。
    """
    text = _get(HIST_URL.format(symbol), session)
    if "=" not in text:
        raise SinaFetchError(f"{symbol} 返回内容异常（可能已退市或代码不存在）")

    encoded = text.split("=")[1].split(";")[0].replace('"', "")
    if not encoded.strip():
        raise SinaFetchError(f"{symbol} 无历史数据")

    rows = _decode_kline(encoded)
    if not rows:
        raise SinaFetchError(f"{symbol} 解码后为空")

    frame = pd.DataFrame(rows)
    if "date" not in frame.columns:
        raise SinaFetchError(f"{symbol} 数据缺少日期列")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame = frame.dropna(subset=["date"])
    # 这几列在部分标的上才有，留着会污染后续的统一 schema。
    frame = frame.drop(columns=[c for c in ("prevclose", "postVol", "postAmt") if c in frame.columns])

    numeric = [c for c in ("open", "high", "low", "close", "volume", "amount") if c in frame.columns]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    shares = _fetch_outstanding_share(symbol, session)
    frame = _attach_turnover(frame, shares)
    return frame.reset_index(drop=True)


def fetch_spot(
    symbols: Sequence[str], *, session: requests.Session | None = None
) -> pd.DataFrame:
    """批量取实时行情，拼成当日日 K 一行。

    返回列：symbol/date/open/high/low/close/volume/amount。
    停牌、退市、空串会跳过。单次请求过多会被网关截断，调用方应分批。
    """
    clean = [str(symbol).strip().lower() for symbol in symbols if str(symbol).strip()]
    if not clean:
        return pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
        )

    # 名称是 GBK，但我们只用 ASCII 的价量日期字段，encoding 无所谓。
    text = _get(SPOT_URL.format(",".join(clean)), session)

    rows: list[dict[str, Any]] = []
    for chunk in text.split(";"):
        line = chunk.strip()
        if not line or "hq_str_" not in line or "=" not in line:
            continue
        left, _, right = line.partition("=")
        symbol = left.split("hq_str_")[-1].strip()
        payload = right.strip().strip(";").strip('"')
        if not symbol or not payload:
            continue
        fields = payload.split(",")
        if len(fields) < 32:
            continue
        try:
            open_ = float(fields[1])
            high = float(fields[4])
            low = float(fields[5])
            close = float(fields[3])
            volume = float(fields[8])
            amount = float(fields[9])
        except ValueError:
            continue
        # 未开盘/停牌常见现价为 0；没有可用 OHLC 就别写入假 K 线。
        if close <= 0 and open_ <= 0:
            continue
        if close <= 0:
            close = open_
        if high <= 0:
            high = max(open_, close)
        if low <= 0:
            low = min(open_, close) if open_ > 0 else close
        trade_date = pd.to_datetime(fields[30], errors="coerce")
        if pd.isna(trade_date):
            continue
        rows.append(
            {
                "symbol": symbol,
                "date": trade_date.date(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        )
    return pd.DataFrame(rows)


def fetch_live_hq(
    symbols: Sequence[str], *, session: requests.Session | None = None
) -> list[dict[str, Any]]:
    """批量实时行情（富字段：名称/昨收/涨跌幅），供顶栏 / 列表 live 用。

    ``symbols`` 已是 sh/sz 前缀。停牌空串跳过；单批失败不抛，继续下一批。
    """
    clean = [str(symbol).strip().lower() for symbol in symbols if str(symbol).strip()]
    if not clean:
        return []

    own_session = session is None
    sess = session or requests.Session()
    if own_session:
        sess.headers.update(HEADERS)

    out: list[dict[str, Any]] = []
    try:
        for start in range(0, len(clean), SPOT_BATCH_SIZE):
            batch = clean[start : start + SPOT_BATCH_SIZE]
            try:
                text = _get(SPOT_URL.format(",".join(batch)), sess)
            except SinaFetchError as exc:
                logger.warning("实时行情批次失败：%s", exc)
                continue
            for chunk in text.split(";"):
                row = _parse_hq_line(chunk)
                if row:
                    out.append(row)
    finally:
        if own_session:
            sess.close()
    return out


def _parse_hq_line(line: str) -> dict[str, Any] | None:
    """解析单条 hq_str_*。要名称、昨收、现价才能算涨跌幅。"""
    text = line.strip()
    if not text or "hq_str_" not in text or "=" not in text:
        return None
    left, _, right = text.partition("=")
    symbol = left.split("hq_str_")[-1].strip().lower()
    payload = right.strip().strip(";").strip('"')
    if not symbol or not payload:
        return None
    fields = payload.split(",")
    if len(fields) < 32:
        return None
    try:
        name = fields[0].strip()
        open_ = float(fields[1])
        prev = float(fields[2])
        price = float(fields[3])
        high = float(fields[4])
        low = float(fields[5])
        volume = float(fields[8])
        amount = float(fields[9])
    except ValueError:
        return None
    if price <= 0 and open_ <= 0:
        return None
    if price <= 0:
        price = open_
    if prev <= 0:
        prev = open_ if open_ > 0 else price
    change = price - prev
    pct = (change / prev * 100.0) if prev else 0.0
    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 3),
        "prev_close": round(prev, 3),
        "open": round(open_, 3),
        "high": round(high, 3),
        "low": round(low, 3),
        "change": round(change, 3),
        "pct": round(pct, 2),
        "volume": volume,
        "amount": amount,
        "trade_date": fields[30],
        "trade_time": fields[31] if len(fields) > 31 else "",
        "source": "sina",
    }


def _fetch_outstanding_share(
    symbol: str, session: requests.Session | None
) -> pd.DataFrame:
    """流通股本变动表（稀疏，只在股本变化时有行）。

    拿不到不算致命——没有它只是缺换手率，日线本身仍然可用。换手率是
    通达信量能类公式的必需字段，所以失败要记日志而不是静默。
    """
    try:
        text = _get(AMOUNT_URL.format(symbol, symbol), session)
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end < 0:
            raise SinaFetchError("响应中找不到数组")
        records = json.loads(text[start : end + 1])
    except Exception as exc:
        logger.info("取 %s 流通股本失败，将缺少换手率：%s", symbol, exc)
        return pd.DataFrame(columns=["date", "outstanding_share"])

    if not records:
        return pd.DataFrame(columns=["date", "outstanding_share"])
    frame = pd.DataFrame(records)
    frame = frame.rename(columns={"amount": "outstanding_share"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    # 新浪这个接口的单位是万股。
    frame["outstanding_share"] = pd.to_numeric(
        frame["outstanding_share"], errors="coerce"
    ) * 10000
    return frame.dropna(subset=["date"])


def _attach_turnover(frame: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """把稀疏的股本表前向填充到每个交易日，再算换手率。"""
    if shares.empty:
        frame["outstanding_share"] = pd.NA
        frame["turnover"] = pd.NA
        return frame

    merged = pd.merge(frame, shares, on="date", how="outer").sort_values("date")
    merged["outstanding_share"] = merged["outstanding_share"].ffill()
    # 只保留真实有行情的交易日：股本变动日不一定是交易日。
    merged = merged[merged["close"].notna()].copy()
    shares_value = merged["outstanding_share"]
    # 股本为 0 或缺失时相除会得到 inf，那比 NaN 更危险：它会安静地通过
    # "换手率 >= 5" 这类阈值判断，把一只没有股本数据的票选出来。
    merged["turnover"] = (merged["volume"] / shares_value).where(shares_value > 0)
    return merged


def fetch_hfq_factors(
    symbol: str, *, session: requests.Session | None = None
) -> pd.DataFrame:
    """取稀疏的后复权因子（date, hfq_factor）。

    只在除权除息日有行。取不到返回空表——行情本身不受影响，
    只是无法做复权换算。
    """
    empty = pd.DataFrame(columns=["date", "hfq_factor"])
    try:
        text = _get(FACTOR_URL.format(symbol, "hfq"), session)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return empty
        # akshare 这里用的是 eval()，对一个网络返回的字符串做 eval 是不必要的
        # 风险；实测新浪返回的就是合法 JSON，用 json.loads 即可。
        payload = json.loads(text[start : end + 1])
    except Exception as exc:
        logger.info("取 %s 后复权因子失败：%s", symbol, exc)
        return empty

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return empty
    frame = pd.DataFrame(data).rename(columns={"d": "date", "f": "hfq_factor"})
    if "date" not in frame.columns or "hfq_factor" not in frame.columns:
        return empty
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame["hfq_factor"] = pd.to_numeric(frame["hfq_factor"], errors="coerce")
    return (
        frame[["date", "hfq_factor"]].dropna().sort_values("date").reset_index(drop=True)
    )
