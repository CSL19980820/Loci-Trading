"""东财适配器。

包装 ``EastmoneySource``：原始中文表经共享管线归一（手→股、百分数→小数）。
扩展 spot_batch / live / 分钟线 / 个股资金流（akshare 东财口径）。
"""
from __future__ import annotations

from datetime import date, timedelta
import math
import threading
import time

import pandas as pd

from src.market.domain.source_contract import (
    CAPITAL_FLOW_CONTRACT,
    LIVE_CONTRACT,
    SPOT_CONTRACT,
)
from src.market.infrastructure.adapters.base import (
    AdapterError,
    MarketAdapter,
    window_start_date,
)
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    ProbeHint,
)
from src.market.infrastructure.pipeline import NormalizeError, empty_spot_frame, normalize
from src.market.infrastructure.sources import EastmoneySource, SourceError, _import_akshare
from src.market.infrastructure.store import guess_market, normalize_code


#: 全市场现价表（``ak.stock_zh_a_spot_em``）一次约 5500 行、数 MB。
#: ``fetch_spot`` 与 ``fetch_live_quotes`` 各自要它，board「live + 落盘」一轮就是
#: 同一份全表下载两遍。
#: 为什么是 4 秒：对齐 ``application/live_cache._QUOTE_TTL_SEC``（5s）的量级——
#: 盘中报价在几秒内复用不会让人看到「卡住的价格」，却足以把同一轮里的重复整表
#: 下载并成一次。再长就会影响盯盘手感，再短就等于没缓存。
_SPOT_RAW_TTL_SEC = 4.0
#: 只缓存一份全市场表：它本身就是最大的那个对象，多留几份只白吃内存。
_SPOT_RAW_CACHE_MAX = 1
_SPOT_RAW_LOCK = threading.Lock()
#: cache_key -> (过期时刻 monotonic, 原始表)
_SPOT_RAW_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}


def _cached_spot_raw(key: str) -> pd.DataFrame | None:
    """TTL 内的全市场现价原始表；没有 / 过期返回 None（调用方照常去取）。"""
    now = time.monotonic()
    with _SPOT_RAW_LOCK:
        hit = _SPOT_RAW_CACHE.get(key)
        if hit is None:
            return None
        expires_at, frame = hit
        if now >= expires_at:
            _SPOT_RAW_CACHE.pop(key, None)
            return None
    # 不复制：这张表几 MB，而唯一的下游 ``normalize`` 内部已经 ``raw.copy()``。
    return frame


def _store_spot_raw(key: str, frame: pd.DataFrame) -> None:
    """写缓存。满了先淘汰最旧的一条，dict 不会无界增长。"""
    with _SPOT_RAW_LOCK:
        while _SPOT_RAW_CACHE and len(_SPOT_RAW_CACHE) >= _SPOT_RAW_CACHE_MAX:
            _SPOT_RAW_CACHE.pop(next(iter(_SPOT_RAW_CACHE)), None)
        _SPOT_RAW_CACHE[key] = (time.monotonic() + _SPOT_RAW_TTL_SEC, frame)


def clear_spot_raw_cache() -> None:
    """清空现价缓存（换源 / 测试需要确定性时用）。"""
    with _SPOT_RAW_LOCK:
        _SPOT_RAW_CACHE.clear()


def _finite(value: object, default: float = 0.0) -> float:
    """NaN / inf / 非数一律回落：它们既过不了 JSON，也会污染下游阈值判断。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class EastmoneyAdapter(MarketAdapter):
    """东财 —— hist_daily / spot_batch / minute / capital_flow。"""

    meta = AdapterMeta(
        id="eastmoney",
        label="东财",
        lanes=(
            LANE_HIST_DAILY,
            LANE_SPOT_BATCH,
            LANE_MINUTE,
            LANE_CAPITAL_FLOW,
        ),
        description=(
            "日线经 akshare stock_zh_a_hist（覆盖 Vibe 链 eastmoney+akshare-hist）；"
            "现价/资金流经 akshare；分钟线直连 push2his/push2delay；"
            "成交量手→股、换手率百分数→小数在共享管线完成。"
        ),
        base_url="https://www.eastmoney.com",
        probe_hints={LANE_HIST_DAILY: ProbeHint(note="≈400d", window_days=400)},
        # 东财现价表没有日期/时间列，date 只能本地补，因此不可用于写当日 K 线。
        spot_declares_trade_date=False,
    )

    def __init__(self, source: EastmoneySource | None = None) -> None:
        self._source = source or EastmoneySource()

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        try:
            frame = self._source.fetch_daily(code, instrument_type=instrument_type)
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        return self._normalize_daily(frame)

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        end = date.today()
        try:
            frame = self._source.fetch_daily(
                code,
                instrument_type=instrument_type,
                start_date=window_start_date(bars, today=end).strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        return self._normalize_daily(frame)

    def _fetch_daily_for_probe(self, code: str) -> pd.DataFrame:
        end = date.today()
        start = end - timedelta(days=400)
        frame = self._source.fetch_daily(
            code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return self._normalize_daily(frame)

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        """全市场现价表按 ``codes`` 过滤；仅 A 股现货（指数不在东财 spot 表）。"""
        _ = batch_size
        stock_codes = self._stock_codes(codes, instrument_types)
        if not stock_codes:
            return empty_spot_frame()
        out = self._normalize_spot(self._load_spot_raw(who="现价"))
        filtered = out[out["code"].isin(set(stock_codes))]
        if filtered.empty:
            raise AdapterError(f"东财现价未命中：{stock_codes[:5]}")
        return filtered.reset_index(drop=True)

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        """顶栏富行情：name / prev_close / pct / price 等。"""
        _ = batch_size
        stock_codes = self._stock_codes(codes, instrument_types)
        if not stock_codes:
            return []
        spot = self._normalize_spot(
            self._load_spot_raw(who="live 行情"), include_rich=True
        )
        spot = spot[spot["code"].isin(set(stock_codes))]
        if spot.empty:
            raise AdapterError("东财 live 行情未命中")
        out: list[dict] = []
        for item in spot.to_dict(orient="records"):
            price = _finite(item.get("close"))
            if price <= 0:
                # 停牌行的最新价在东财表里是 NaN；带着 NaN 出接口就是非法 JSON。
                continue
            prev = _finite(item.get("prev_close"), price) or price
            out.append(
                {
                    "code": item["code"],
                    "name": item.get("name") or "",
                    "price": price,
                    "prev_close": prev,
                    "open": _finite(item.get("open"), price) or price,
                    "high": _finite(item.get("high"), price) or price,
                    "low": _finite(item.get("low"), price) or price,
                    "change": _finite(item.get("change")),
                    "pct": _finite(item.get("pct")),
                    "volume": _finite(item.get("volume")),
                    "amount": _finite(item.get("amount")),
                    "trade_time": "",
                    "source": "eastmoney",
                }
            )
        return out

    def fetch_minute(
        self,
        code: str,
        *,
        period: str = "1",
        days: int = 1,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        from src.market.infrastructure.eastmoney_minute import (
            EastmoneyMinuteError,
            fetch_minute_bars,
        )

        plain = normalize_code(code)
        try:
            return fetch_minute_bars(
                plain,
                period=period,
                days=days,
                trade_date=trade_date,
            )
        except EastmoneyMinuteError as exc:
            raise AdapterError(f"东财分钟线 {plain} 失败：{exc}") from exc
        except Exception as exc:
            raise AdapterError(
                f"东财分钟线 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc

    def fetch_capital_flow(self, code: str) -> pd.DataFrame:
        plain = normalize_code(code)
        market = guess_market(plain)
        ak = _import_akshare()
        try:
            frame = ak.stock_individual_fund_flow(stock=plain, market=market)
        except Exception as exc:
            raise AdapterError(
                f"东财资金流 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc
        return self._normalize_capital_flow(frame)

    @staticmethod
    def _stock_codes(
        codes: list[str], instrument_types: dict[str, str] | None
    ) -> list[str]:
        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        return [c for c in normalized if types.get(c, "STOCK") != "INDEX"]

    def _load_spot_raw(self, *, who: str) -> pd.DataFrame:
        """全市场现价原始表，带 4s 进程内 TTL 缓存。

        缓存只在「取到了非空表」时写；失败一律照旧抛 ``AdapterError``，
        既不缓存失败，也不会因为缓存不可用而多出一种错误。
        """
        cache_key = self._spot_cache_key()
        if cache_key is not None:
            cached = _cached_spot_raw(cache_key)
            if cached is not None:
                return cached
        try:
            raw = self._fetch_spot_em()
        except Exception as exc:
            raise AdapterError(
                f"东财{who}失败：{type(exc).__name__}: {exc}"
            ) from exc
        if raw is None or raw.empty:
            raise AdapterError(f"东财{who}为空")
        if cache_key is not None:
            _store_spot_raw(cache_key, raw)
        return raw

    def _spot_cache_key(self) -> str | None:
        """缓存键；取数实现被换过的实例不共享缓存（返回 None）。

        测试与子类会把 ``_fetch_spot_em`` 换成自己的桩，那份数据不属于真实
        东财线路，混进同一格缓存只会串味。
        """
        if "_fetch_spot_em" in vars(self):
            return None
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @staticmethod
    def _fetch_spot_em() -> pd.DataFrame:
        ak = _import_akshare()
        return ak.stock_zh_a_spot_em()

    @classmethod
    def _normalize_spot(
        cls, frame: pd.DataFrame, *, include_rich: bool = False
    ) -> pd.DataFrame:
        contract = LIVE_CONTRACT if include_rich else SPOT_CONTRACT
        try:
            out = normalize(frame, contract, who="东财", empty_label="东财现价")
        except NormalizeError as exc:
            raise AdapterError(str(exc)) from exc
        if "code" not in out.columns:
            raise AdapterError("东财现价缺 code 列")
        out = out.copy()
        out["code"] = out["code"].astype(str).str.strip().str.zfill(6)
        if "date" not in out.columns:
            # 本地补的日期只够 probe / 顶栏展示用；写库路径靠 meta 上的
            # spot_declares_trade_date=False 把这一源挡在外面。
            out["date"] = date.today()
        if include_rich:
            return out
        return out[
            ["code", "date", "open", "high", "low", "close", "volume", "amount"]
        ].reset_index(drop=True)

    @classmethod
    def _normalize_capital_flow(cls, frame: pd.DataFrame) -> pd.DataFrame:
        try:
            return normalize(
                frame,
                CAPITAL_FLOW_CONTRACT,
                who="东财资金流",
                empty_label="东财资金流",
            )
        except NormalizeError as exc:
            raise AdapterError(str(exc)) from exc

    @classmethod
    def _normalize_daily(cls, frame: pd.DataFrame) -> pd.DataFrame:
        return cls._normalize_daily_frame(frame, who="东财")
