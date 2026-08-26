"""通达信适配器：全市场日线主源 + 历史分时。

日线走 TDX 二进制协议，是 hist_daily 的默认主源；选型实测见
``infrastructure/tdx_daily.py`` 头注释与 ``scripts/benchmark_data_sources.py``。
"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    ProbeHint,
)
from src.market.infrastructure.pipeline import empty_spot_frame
from src.market.infrastructure.store import normalize_code


class TdxAdapter(MarketAdapter):
    """通达信 TDX 协议：日线主源 + 实时日 K + 历史 1 分钟分时。"""

    meta = AdapterMeta(
        id="tdx",
        label="通达信",
        lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH, LANE_MINUTE),
        description=(
            "TDX 二进制行情协议：全市场日线主源（单票 p50 约 28ms，8 路并发"
            " 约 166 票/秒），实时日 K 走同一条长连接取最后一根（全市场约 22s），"
            "另提供历史分时回退。日线含真实成交额；换手率源侧没有，由仓内流通"
            "股本推算。分时不写 market.db。"
        ),
        base_url="tdx://binary",
        probe_hints={
            LANE_HIST_DAILY: ProbeHint(note="最近 60 根日线", recent_count=60),
            LANE_SPOT_BATCH: ProbeHint(note="最后一根日线", recent_count=1),
        },
        # 换手率与流通股本源侧不提供，仓内按股本推算；标出来让多源合并
        # 时优先采信真实值的源。
        estimated_fields=(),
        # 日线报文自带 ``datetime``（如 ``2026-08-24 15:00``），所以当日快照
        # 是源自报交易日、不是本地补的今天——可以进 ``dated_spot_adapter_ids``
        # 的写库白名单。东财现价表没有日期列，那才是必须挡在写库外的那类。
        spot_declares_trade_date=True,
    )

    #: 全历史翻页上限内的一次性根数；再多没有意义（A 股最长约 8800 个交易日）。
    _FULL_BARS = None
    #: 实时日 K 的并发。取最后一根是最短的一次往返（约 25ms），16 路实测
    #: 249 票/秒（全市场约 22s）——但那个档位跑久了会被 TDX 在协议层拒（见
    #: ``router_live.ADAPTER_SOURCE_CONCURRENCY`` 的注释）。8 路仍有 120+ 票/秒，
    #: 全市场约 45s，足够盘中用。
    _SPOT_WORKERS = 8
    _SPOT_WORKERS = 8

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        """当日快照 = 每只票日线的最后一根。

        别用 ``get_security_quotes``：它一次能拿 80 只、更省往返，但**不带交易日**，
        而且混市场批量会整批失败（实测沪+深+北一起问返回 0 条）。日线接口每只多
        一次往返，却自报 ``datetime``——当日 K 线必须由源自报日期才能写库，
        否则法定节假日会把昨天的收盘价盖上今天的日期，还往交易日历插假交易日。

        ``batch_size`` 在这条源上没有意义（协议按票请求，不按批），保留只为签名
        与其它适配器一致。"""
        _ = batch_size
        from src.market.infrastructure.tdx_daily import fetch_daily_many

        wanted = [str(code).strip() for code in codes if str(code).strip()]
        if not wanted:
            return empty_spot_frame()
        frames = fetch_daily_many(
            wanted,
            bars=1,
            workers=self._SPOT_WORKERS,
            instrument_types=instrument_types,
        )
        rows: list[dict[str, object]] = []
        for code, frame in frames.items():
            if frame is None or frame.empty:
                continue
            last = frame.iloc[-1]
            rows.append(
                {
                    "code": code,
                    "date": str(last["date"]),
                    "open": last["open"],
                    "high": last["high"],
                    "low": last["low"],
                    "close": last["close"],
                    "volume": last["volume"],
                    "amount": last["amount"],
                }
            )
        if not rows:
            raise AdapterError(
                f"通达信当日快照没拿到任何一只（请求 {len(wanted)} 只）"
            )
        return pd.DataFrame(rows)

    def fetch_spot_sample(self, codes: list[str] | None = None) -> pd.DataFrame:
        """探测只问两只；默认样本会走全市场，把体检页拖成半分钟。"""
        return self.fetch_spot(list(codes or ["600519", "000001"]))

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        return self._daily(code, bars=self._FULL_BARS, instrument_type=instrument_type)

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        return self._daily(
            code, bars=max(1, int(bars)), instrument_type=instrument_type
        )

    def fetch_daily_many(
        self,
        codes: list[str],
        *,
        bars: int | None = None,
        workers: int = 8,
        instrument_types: dict[str, str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """批量日线。本源的核心能力位：一条线程一条长连接，按票扇出。

        失败的票不出现在返回值里，调用方据此决定是否回退其它源。
        指数必须在 ``instrument_types`` 里显式声明，见 ``tdx_daily.fetch_daily_bars``。
        """
        from src.market.infrastructure.tdx_daily import fetch_daily_many

        return fetch_daily_many(
            list(codes),
            bars=bars,
            workers=workers,
            instrument_types=instrument_types,
        )

    def _daily(
        self, code: str, *, bars: int | None, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        from src.market.infrastructure.tdx_daily import TdxDailyError, fetch_daily_bars

        plain = normalize_code(code)
        try:
            return fetch_daily_bars(
                plain, bars=bars, instrument_type=instrument_type
            )
        except TdxDailyError as exc:
            raise AdapterError(f"通达信日线 {plain} 失败：{exc}") from exc
        except Exception as exc:
            raise AdapterError(
                f"通达信日线 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc

    def _fetch_daily_for_probe(self, code: str) -> pd.DataFrame:
        """探测只要近窗；全历史翻页会把体检页拖成十几秒。"""
        return self._daily(code, bars=60)

    def fetch_minute(
        self,
        code: str,
        *,
        period: str = "1",
        days: int = 1,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        from src.market.infrastructure.tdx_minute import (
            TdxMinuteError,
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
        except TdxMinuteError as exc:
            raise AdapterError(f"通达信分钟线 {plain} 失败：{exc}") from exc
        except Exception as exc:
            raise AdapterError(
                f"通达信分钟线 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc
