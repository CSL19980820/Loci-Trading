"""live-tape 选路：优先竞速 sina/tencent，避免东财全表拖垮托盘。"""
from __future__ import annotations

import time
import threading
import unittest
from unittest.mock import patch

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.registry import reset_registry
from src.market.infrastructure.adapters.router import (
    clear_sticky,
    fetch_live_quotes_routed,
    pin_sticky,
)
from src.market.infrastructure.adapters.types import AdapterMeta, LANE_SPOT_BATCH


def _quote(code: str, *, source: str) -> dict:
    return {
        "code": code,
        "name": code,
        "price": 10.0,
        "pct": 1.0,
        "change": 0.1,
        "prev_close": 9.9,
        "source": source,
    }


class _LiveOnlyAdapter(MarketAdapter):
    """只实现 live；日线 stub 满足抽象基类。"""

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        raise AdapterError(f"{self.meta.id} stub daily unused")


class _SlowEastmoney(_LiveOnlyAdapter):
    meta = AdapterMeta(
        id="eastmoney",
        label="东财慢源",
        lanes=(LANE_SPOT_BATCH,),
        description="模拟 SSL/全表超时",
    )

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        _ = codes, instrument_types, batch_size
        time.sleep(0.35)
        raise AdapterError("eastmoney simulated timeout")


class _FastSina(_LiveOnlyAdapter):
    meta = AdapterMeta(
        id="sina",
        label="新浪",
        lanes=(LANE_SPOT_BATCH,),
        description="快源",
    )

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        _ = instrument_types, batch_size
        return [_quote(c, source="sina") for c in codes]


class _FastTencent(_LiveOnlyAdapter):
    meta = AdapterMeta(
        id="tencent",
        label="腾讯",
        lanes=(LANE_SPOT_BATCH,),
        description="快源",
    )

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        _ = instrument_types, batch_size
        time.sleep(0.05)
        return [_quote(c, source="tencent") for c in codes]


class _SlowSina(_LiveOnlyAdapter):
    meta = AdapterMeta(
        id="sina",
        label="新浪慢源",
        lanes=(LANE_SPOT_BATCH,),
        description="模拟 preferred 源超时",
    )

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        _ = codes, instrument_types, batch_size
        time.sleep(0.35)
        raise AdapterError("sina simulated timeout")


class _BlockingSina(_LiveOnlyAdapter):
    meta = AdapterMeta(
        id="sina_blocking",
        label="新浪阻塞源",
        lanes=(LANE_SPOT_BATCH,),
        description="模拟长期未结束的首选源",
    )

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.calls = 0

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        _ = codes, instrument_types, batch_size
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=5)
        raise AdapterError("sina simulated long timeout")


class LiveQuotesRoutedTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sticky()
        reset_registry()

    def test_prefers_sina_over_slow_eastmoney_without_waiting(self) -> None:
        reset_registry([_SlowEastmoney(), _FastSina(), _FastTencent()])
        clear_sticky()
        with patch(
            "src.market.infrastructure.adapters.router.enabled_adapter_ids",
            return_value=["eastmoney", "sina", "tencent"],
        ):
            started = time.perf_counter()
            rows, winner = fetch_live_quotes_routed(["600519", "000001"])
            elapsed = time.perf_counter() - started

        self.assertIn(winner, {"sina", "tencent"})
        self.assertEqual(len(rows), 2)
        # 若仍先串行等东财 0.35s，这里会明显更慢
        self.assertLess(elapsed, 0.30)

    def test_eastmoney_sticky_does_not_block_preferred_race(self) -> None:
        reset_registry([_SlowEastmoney(), _FastSina()])
        pin_sticky(LANE_SPOT_BATCH, "eastmoney", ttl_sec=600)
        with patch(
            "src.market.infrastructure.adapters.router.enabled_adapter_ids",
            return_value=["eastmoney", "sina"],
        ):
            started = time.perf_counter()
            rows, winner = fetch_live_quotes_routed(["600519"])
            elapsed = time.perf_counter() - started

        self.assertEqual(winner, "sina")
        self.assertEqual(rows[0]["source"], "sina")
        self.assertLess(elapsed, 0.30)

    def test_fast_preferred_result_does_not_wait_for_slow_preferred_source(self) -> None:
        reset_registry([_SlowSina(), _FastTencent()])
        clear_sticky()
        with patch(
            "src.market.infrastructure.adapters.router.enabled_adapter_ids",
            return_value=["sina", "tencent"],
        ):
            started = time.perf_counter()
            rows, winner = fetch_live_quotes_routed(["600519"])
            elapsed = time.perf_counter() - started

        self.assertEqual(winner, "tencent")
        self.assertEqual(rows[0]["source"], "tencent")
        self.assertLess(elapsed, 0.30)

    def test_slow_preferred_source_is_not_started_again_while_previous_call_runs(self) -> None:
        started = threading.Event()
        release = threading.Event()
        slow = _BlockingSina(started, release)
        reset_registry([slow, _FastTencent()])
        clear_sticky()
        try:
            with patch(
                "src.market.infrastructure.adapters.router.enabled_adapter_ids",
                return_value=["sina_blocking", "tencent"],
            ), patch(
                "src.market.infrastructure.adapters.router._LIVE_QUOTE_PREFERRED",
                ("sina_blocking", "tencent"),
            ):
                for _ in range(4):
                    rows, winner = fetch_live_quotes_routed(["600519"])
                    self.assertEqual(winner, "tencent")
                    self.assertEqual(rows[0]["source"], "tencent")
            self.assertTrue(started.wait(timeout=1))
            self.assertEqual(slow.calls, 1)
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
