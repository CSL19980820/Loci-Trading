"""MarketAdapter 抽象基类。

转换逻辑只活在各具体 Adapter 里；基类只定契约与「不支持」的默认行为。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import time
from typing import Any

import pandas as pd

from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    DAILY_REQUIRED_COLUMNS,
    ProbeResult,
)


class AdapterError(RuntimeError):
    """适配器取数失败。router / 调用方据此换路或上报。"""


class MarketAdapter(ABC):
    """一条可接入数据源。

    ``meta.lanes`` 声明自己接哪些 lane；未实现的方法保持 stub，
    ``probe`` 对不支持的 lane 返回 ``unsupported=True``。
    """

    meta: AdapterMeta

    @abstractmethod
    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        """返回已归一的不复权日线。

        必选列：date/open/high/low/close/volume/amount。
        可选：turnover（小数）、outstanding_share。
        """

    def fetch_spot_sample(self, codes: list[str] | None = None) -> pd.DataFrame:
        """批量现价小样本（探测用）。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 spot_batch")

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        """批量现价。返回列至少含 code/date/open/high/low/close/volume/amount。"""
        raise AdapterError(f"{self.meta.id} 不支持 spot_batch")

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        """顶栏/列表富行情。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 spot_batch live")

    def fetch_instruments(self) -> pd.DataFrame:
        """证券列表。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 instruments")

    def fetch_adjust_factors(self, code: str) -> pd.DataFrame:
        """复权因子。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 adjust_factor")

    def fetch_minute(
        self, code: str, *, period: str = "1", days: int = 1
    ) -> pd.DataFrame:
        """分钟 K 线。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 minute_bars")

    def fetch_capital_flow(self, code: str) -> pd.DataFrame:
        """个股资金流。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 capital_flow")

    def probe(self, lane: str) -> ProbeResult:
        """连通探测：小样本取数 + RTT。

        子类可覆盖；默认按 lane 调对应 stub / fetch_daily。
        """
        from src.market.infrastructure.adapters.types import (
            LANE_ADJUST_FACTOR,
            LANE_CAPITAL_FLOW,
            LANE_HIST_DAILY,
            LANE_INSTRUMENTS,
            LANE_MINUTE,
            LANE_SPOT_BATCH,
        )

        if lane not in self.meta.lanes:
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=False,
                unsupported=True,
                error=f"{self.meta.label} 不支持 lane={lane}",
            )

        started = time.perf_counter()
        try:
            rows: int | None = None
            if lane == LANE_HIST_DAILY:
                frame = self.fetch_daily("600519")
                self._assert_daily_shape(frame)
                rows = int(len(frame))
            elif lane == LANE_SPOT_BATCH:
                frame = self.fetch_spot_sample(["600519"])
                rows = int(len(frame)) if frame is not None else 0
            elif lane == LANE_INSTRUMENTS:
                frame = self.fetch_instruments()
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("证券列表为空")
            elif lane == LANE_ADJUST_FACTOR:
                frame = self.fetch_adjust_factors("600519")
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("复权因子为空")
            elif lane == LANE_MINUTE:
                frame = self.fetch_minute("600519", period="1", days=1)
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("分钟线为空")
            elif lane == LANE_CAPITAL_FLOW:
                frame = self.fetch_capital_flow("600519")
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("资金流为空")
            else:
                return ProbeResult(
                    adapter_id=self.meta.id,
                    lane=lane,
                    ok=False,
                    unsupported=True,
                    error=f"未知或未实现的 lane={lane}",
                )
            rtt = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=True,
                rtt_ms=rtt,
                rows=rows,
            )
        except Exception as exc:
            rtt = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=False,
                rtt_ms=rtt,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _assert_daily_shape(frame: pd.DataFrame) -> None:
        if frame is None or frame.empty:
            raise AdapterError("日线为空")
        missing = [c for c in DAILY_REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise AdapterError(f"日线缺列：{missing}")

    def catalog_entry(self) -> dict[str, Any]:
        """给 list_catalog / API 用的扁平字典。"""
        return {
            "id": self.meta.id,
            "label": self.meta.label,
            "lanes": list(self.meta.lanes),
            "description": self.meta.description,
        }
