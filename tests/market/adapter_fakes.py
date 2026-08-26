"""适配器路由测试共用的假适配器与面板夹具。

原先内联在 `test_adapters_routing.py`，该文件拆分后由多个测试模块共用。
"""
from __future__ import annotations

import threading
import time

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    ProbeResult,
)


def _daily_frame(n: int = 3, *, turnover: float = 0.05) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [f"2026-01-{i:02d}" for i in range(1, n + 1)],
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.5] * n,
            "volume": [1_000_000.0] * n,
            "amount": [10_000_000.0] * n,
            "turnover": [turnover] * n,
            "outstanding_share": [1e9] * n,
        }
    )


class _FakeAdapter(MarketAdapter):
    """可控延迟 / 成败的假适配器，专供 registry / probe 并行测试。"""

    def __init__(
        self,
        adapter_id: str,
        *,
        lanes: tuple[str, ...] = (LANE_HIST_DAILY,),
        delay: float = 0.0,
        fail: bool = False,
        frame: pd.DataFrame | None = None,
        live_rows: list[dict[str, object]] | None = None,
        live_call_order: list[str] | None = None,
        estimated_fields: tuple[str, ...] = (),
    ) -> None:
        self.meta = AdapterMeta(
            id=adapter_id,
            label=adapter_id,
            lanes=lanes,
            description="fake",
            estimated_fields=estimated_fields,
        )
        self.delay = delay
        self.fail = fail
        self.frame = frame if frame is not None else _daily_frame()
        self.probe_calls = 0
        self.fetch_calls = 0
        self.live_rows = list(live_rows or [])
        self.live_call_order = live_call_order
        self.live_fetch_calls = 0

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        self.fetch_calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise AdapterError(f"{self.meta.id} 故意失败")
        return self.frame.copy()

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        _ = codes, instrument_types, batch_size
        self.live_fetch_calls += 1
        if self.live_call_order is not None:
            self.live_call_order.append(self.meta.id)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise AdapterError(f"{self.meta.id} 故意失败")
        return list(self.live_rows)


class _BlockingSpotAdapter(MarketAdapter):
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.meta = AdapterMeta(
            id="blocking_spot",
            label="blocking spot",
            lanes=(LANE_SPOT_BATCH,),
            description="blocking spot test adapter",
        )
        self.started = started
        self.release = release
        self.calls = 0

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        raise AdapterError("unused")

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        _ = instrument_types, batch_size
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=5)
        return pd.DataFrame({"code": codes, "close": [10.0] * len(codes)})

    def probe(self, lane: str) -> ProbeResult:
        self.probe_calls += 1
        if self.delay:
            time.sleep(self.delay)
        if lane not in self.meta.lanes:
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=False,
                unsupported=True,
                error="unsupported",
            )
        if self.fail:
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=False,
                error="fail",
            )
        return ProbeResult(
            adapter_id=self.meta.id,
            lane=lane,
            ok=True,
            rtt_ms=self.delay * 1000.0,
            rows=len(self.frame),
        )


class _CodeProbeAdapter(MarketAdapter):
    meta = AdapterMeta("code_probe", "code_probe", (LANE_HIST_DAILY,))

    def __init__(self) -> None:
        self.code_seen: str | None = None

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        self.code_seen = code
        return _daily_frame()
