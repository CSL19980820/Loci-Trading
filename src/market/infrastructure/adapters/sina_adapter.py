"""新浪直连适配器。

薄包装 ``SinaSource`` / ``src.market.infrastructure.sina``：日线与换手率已在 sina 模块
归一成小数；现价批量也经本适配器，业务层不再直调 sina。
"""
from __future__ import annotations

import pandas as pd

from src.market.domain.source_contract import CAPITAL_FLOW_CONTRACT
from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_ADJUST_FACTOR,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    ProbeHint,
)
from src.market.infrastructure.pipeline import NormalizeError, normalize
from src.market.infrastructure.sources import SinaSource, SourceError
from src.market.infrastructure.store import normalize_code, to_sina_symbol


class SinaAdapter(MarketAdapter):
    """新浪直连 —— hist_daily / spot_batch / adjust_factor / minute_bars / capital_flow。"""

    meta = AdapterMeta(
        id="sina",
        label="新浪直连",
        lanes=(
            LANE_HIST_DAILY,
            LANE_SPOT_BATCH,
            LANE_ADJUST_FACTOR,
            LANE_MINUTE,
            # 资金流回退位：注册表里本适配器排在东财之后，天然是第二顺位，
            # 不要为此调顺序。只覆盖主力 / 超大单两组，缺大中小单拆分。
            LANE_CAPITAL_FLOW,
        ),
        description=(
            "一次拉全历史，自带流通股本与换手率（小数）；分钟线直连 quotes.sina.cn；"
            "日 K / 复权不经 akshare；资金流为东财的回退源（仅主力 / 超大单）。"
        ),
        base_url="https://finance.sina.com.cn",
        probe_hints={LANE_HIST_DAILY: ProbeHint(note="full")},
    )

    def __init__(self, source: SinaSource | None = None) -> None:
        self._source = source or SinaSource()

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        try:
            frame = self._source.fetch_daily(code, instrument_type=instrument_type)
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        return self._normalize_daily(frame)

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        from src.market import sina

        return self._live_via_symbols(
            codes,
            sina.fetch_live_hq,
            instrument_types=instrument_types,
            batch_size=batch_size,
            who="新浪",
        )

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        from src.market import sina

        return self._spot_via_symbols(
            codes,
            sina.fetch_spot,
            instrument_types=instrument_types,
            batch_size=batch_size,
            who="新浪",
            fetch_error_type=sina.SinaFetchError,
        )

    def fetch_adjust_factors(self, code: str) -> pd.DataFrame:
        try:
            return self._source.fetch_adjust_factors(code)
        except Exception as exc:
            raise AdapterError(
                f"新浪复权因子失败：{type(exc).__name__}: {exc}"
            ) from exc

    def fetch_minute(
        self,
        code: str,
        *,
        period: str = "1",
        days: int = 1,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        from src.market import sina

        plain = normalize_code(code)
        symbol = to_sina_symbol(plain)
        try:
            return sina.fetch_minute(
                symbol,
                period=period,
                days=days,
                trade_date=trade_date,
            )
        except sina.SinaFetchError as exc:
            raise AdapterError(f"新浪分钟线 {plain} 失败：{exc}") from exc
        except Exception as exc:
            raise AdapterError(
                f"新浪分钟线 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc

    def fetch_capital_flow(self, code: str) -> pd.DataFrame:
        """个股资金流（东财之后的回退源）。

        新浪只有主力（``netamount`` / ``ratioamount``）与超大单（``r0_net`` /
        ``r0_ratio``）两组，大 / 中 / 小单六列**整列缺席**——上游看到的是这几个
        列名根本不在返回表里（不是 NaN 列），按 ``in frame.columns`` 判断即可。
        口径转换（新浪小数 → 仓内百分数）全部由 ``CAPITAL_FLOW_CONTRACT`` 的
        ``RATIO_TO_PERCENT`` 声明，这里一行乘除都不写。
        """
        from src.market import sina

        plain = normalize_code(code)
        symbol = to_sina_symbol(plain)
        try:
            raw = sina.fetch_capital_flow(symbol)
        except sina.SinaFetchError as exc:
            raise AdapterError(f"新浪资金流 {plain} 失败：{exc}") from exc
        except Exception as exc:
            raise AdapterError(
                f"新浪资金流 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc
        try:
            return normalize(
                raw,
                CAPITAL_FLOW_CONTRACT,
                who=f"新浪 {plain} 资金流",
                empty_label=f"新浪 {plain} 资金流",
            )
        except NormalizeError as exc:
            raise AdapterError(str(exc)) from exc

    @classmethod
    def _normalize_daily(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """新浪直连已产出标准列名；turnover 已是小数，勿再 /100。"""
        return cls._normalize_daily_frame(frame, who="新浪")
