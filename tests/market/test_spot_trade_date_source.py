"""写当日 K 线的现价源必须自报交易日。

不声明交易日的源只能由本地补「今天」。落在周一至周五的法定节假日，
`_is_current_trading_day` 的 weekday 兜底会判为交易日，补出来的今天又骗过
「spot 未返回今天就报错」那道闸门——于是昨天的收盘快照被写成当日 K 线，
还往 trading_calendar 插一个假交易日。
"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.registry import reset_registry
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_SPOT_BATCH,
)
from src.market.infrastructure.adapters.base import MarketAdapter
from src.market.infrastructure.sync_spot import dated_spot_adapter_ids


class _Undated(MarketAdapter):
    meta = AdapterMeta(
        id="undated",
        label="不报日期的源",
        lanes=(LANE_SPOT_BATCH,),
        description="fake",
        spot_declares_trade_date=False,
    )

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        raise NotImplementedError

    def fetch_spot(self, codes, *, instrument_types=None, batch_size=400):
        raise NotImplementedError


class _Dated(MarketAdapter):
    meta = AdapterMeta(
        id="dated",
        label="自报日期的源",
        lanes=(LANE_SPOT_BATCH,),
        description="fake",
    )

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        raise NotImplementedError

    def fetch_spot(self, codes, *, instrument_types=None, batch_size=400):
        raise NotImplementedError


def test_eastmoney_does_not_claim_to_declare_a_trade_date() -> None:
    """东财现价表本来就没有日期列，meta 必须诚实。"""
    assert EastmoneyAdapter.meta.spot_declares_trade_date is False


def test_tencent_and_sina_parse_a_real_timestamp() -> None:
    assert TencentAdapter.meta.spot_declares_trade_date is True
    assert SinaAdapter.meta.spot_declares_trade_date is True


def test_undated_sources_are_kept_out_of_the_persist_path() -> None:
    try:
        reset_registry([_Undated(), _Dated()])
        assert dated_spot_adapter_ids() == ["dated"]
    finally:
        reset_registry()


def test_no_restriction_when_every_source_is_undated() -> None:
    """全员不报日期时返回 None（不加限制），由既有闸门兜底，而不是整条线路瘫掉。"""
    try:
        reset_registry([_Undated()])
        assert dated_spot_adapter_ids() is None
    finally:
        reset_registry()


def test_the_real_registry_still_leaves_a_usable_spot_source() -> None:
    ids = dated_spot_adapter_ids()
    assert ids is None or ids, "现价写库路径不能被过滤成空"
    if ids:
        assert "eastmoney" not in ids
