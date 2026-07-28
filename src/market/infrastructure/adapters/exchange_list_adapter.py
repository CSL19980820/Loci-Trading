"""交易所证券列表适配器。

包装 ``src.market.infrastructure.sources.fetch_instrument_list``（上交所 / 深交所 / 北交所
分表合并）。不接日线——日线仍走新浪 / 东财。
"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import AdapterMeta, LANE_INSTRUMENTS
from src.market.infrastructure.sources import SourceError, fetch_instrument_list


class ExchangeListAdapter(MarketAdapter):
    """交易所列表 —— instruments lane。"""

    meta = AdapterMeta(
        id="exchange_list",
        label="交易所列表",
        lanes=(LANE_INSTRUMENTS,),
        description="上交所/深交所/北交所上市证券列表（纯表格，不经 py_mini_racer）。",
    )

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        raise AdapterError("交易所列表适配器不提供日线")

    def fetch_instruments(self) -> pd.DataFrame:
        try:
            frame = fetch_instrument_list()
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        except Exception as exc:
            raise AdapterError(
                f"交易所列表异常：{type(exc).__name__}: {exc}"
            ) from exc
        if frame is None or frame.empty:
            raise AdapterError("交易所列表为空")
        # 归一最小列；board / list_date 原样保留。
        out = frame.copy()
        if "code" not in out.columns:
            raise AdapterError("交易所列表缺 code 列")
        out["code"] = out["code"].astype(str).str.strip().str.zfill(6)
        if "name" not in out.columns:
            out["name"] = ""
        return out.reset_index(drop=True)
