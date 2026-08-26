"""证券宝（baostock）适配器 —— hist_daily 独立免费源。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.market.infrastructure.adapters.base import (
    AdapterError,
    MarketAdapter,
    window_start_date,
)
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    ProbeHint,
)
from src.market.infrastructure.sources import BaostockSource, SourceError


class BaostockAdapter(MarketAdapter):
    """证券宝 —— 仅 hist_daily；对齐 Vibe A 股链中的 baostock 位。"""

    meta = AdapterMeta(
        id="baostock",
        label="证券宝",
        lanes=(LANE_HIST_DAILY,),
        description=(
            "baostock 不复权日 K；登录后拉全历史，原始 turn（百分数）由管线换算为小数；"
            "不经 akshare，作东财/腾讯之外的独立备源。"
        ),
        base_url="http://baostock.com",
        probe_hints={LANE_HIST_DAILY: ProbeHint(note="≈400d", window_days=400)},
    )

    def __init__(self, source: BaostockSource | None = None) -> None:
        self._source = source or BaostockSource()

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
                start_date=window_start_date(bars, today=end).isoformat(),
                end_date=end.isoformat(),
            )
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        return self._normalize_daily(frame)

    def _fetch_daily_for_probe(self, code: str) -> pd.DataFrame:
        """探测只用近窗，避免登录后拉全历史把数据源页卡死。"""
        end = date.today()
        start = end - timedelta(days=400)
        try:
            frame = self._source.fetch_daily(
                code,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        return self._normalize_daily(frame)

    @classmethod
    def _normalize_daily(cls, frame: pd.DataFrame) -> pd.DataFrame:
        return cls._normalize_daily_frame(frame, who="证券宝")
