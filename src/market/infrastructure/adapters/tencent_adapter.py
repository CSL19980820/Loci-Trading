"""腾讯财经直连适配器。

薄包装 ``src.market.infrastructure.tencent``：hist_daily 分页拼全历史；spot_batch 走 qt.gtimg.cn。
"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    ProbeHint,
)
from src.market.infrastructure.store import to_sina_symbol


class TencentAdapter(MarketAdapter):
    """腾讯财经 —— hist_daily / spot_batch。"""

    meta = AdapterMeta(
        id="tencent",
        label="腾讯财经",
        lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH),
        description=(
            "qt.gtimg 现价 + ifzq 日 K；分页拼全历史，不经 akshare。"
            "主 path 被 WAF 时换同 host kline；握手超时跳过该 host，直连 ifzq 快败，"
            "近窗再失败走 flashdata。日 K 无成交额，amount 由 close×volume 估算"
            "（现价通道的 amount 是源生值）。"
        ),
        base_url="https://proxy.finance.qq.com",
        probe_hints={LANE_HIST_DAILY: ProbeHint(note="30d", recent_count=30)},
        estimated_fields=("amount",),
    )

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        from src.market import tencent

        symbol = to_sina_symbol(code, instrument_type=instrument_type)
        try:
            frame = tencent.fetch_daily(symbol)
        except tencent.TencentFetchError as exc:
            raise AdapterError(str(exc)) from exc
        except Exception as exc:
            raise AdapterError(
                f"腾讯日线异常：{type(exc).__name__}: {exc}"
            ) from exc
        return self._normalize_daily(frame)

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        """近窗只打一页；超过单页上限时退回分页全历史。"""
        from src.market import tencent

        if bars > tencent.DAILY_PAGE_SIZE:
            return self.fetch_daily(code, instrument_type=instrument_type)
        symbol = to_sina_symbol(code, instrument_type=instrument_type)
        try:
            frame = tencent.fetch_daily_recent(symbol, count=max(1, bars))
        except tencent.TencentFetchError as exc:
            raise AdapterError(str(exc)) from exc
        except Exception as exc:
            raise AdapterError(f"腾讯日线异常：{type(exc).__name__}: {exc}") from exc
        return self._normalize_daily(frame)

    def _fetch_daily_for_probe(self, code: str) -> pd.DataFrame:
        from src.market import tencent

        symbol = to_sina_symbol(code)
        frame = tencent.fetch_daily_recent(symbol, count=30)
        return self._normalize_daily(frame)

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 80,
    ) -> list[dict]:
        from src.market import tencent

        return self._live_via_symbols(
            codes,
            tencent.fetch_live_hq,
            instrument_types=instrument_types,
            batch_size=batch_size,
            who="腾讯",
        )

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 80,
    ) -> pd.DataFrame:
        from src.market import tencent

        _ = batch_size  # 底层 tencent.fetch_spot 自行分批
        return self._spot_via_symbols(
            codes,
            tencent.fetch_spot,
            instrument_types=instrument_types,
            batch_size=None,
            who="腾讯",
            fetch_error_type=tencent.TencentFetchError,
        )

    @classmethod
    def _normalize_daily(cls, frame: pd.DataFrame) -> pd.DataFrame:
        return cls._normalize_daily_frame(frame, who="腾讯")
