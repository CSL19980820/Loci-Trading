"""通达信历史分时适配器。"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import AdapterMeta, LANE_MINUTE
from src.market.infrastructure.store import normalize_code


class TdxAdapter(MarketAdapter):
    """通达信 TDX 协议：只提供历史 1 分钟分时。"""

    meta = AdapterMeta(
        id="tdx",
        label="通达信",
        lanes=(LANE_MINUTE,),
        description=(
            "TDX 历史分时回退；返回逐分钟收盘价和成交量，补齐 A 股交易时间轴，"
            "不写 market.db。"
        ),
    )

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        _ = code, instrument_type
        raise AdapterError("通达信适配器不提供 hist_daily")

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
