"""数据线路适配器层单测 —— 不打真网。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from typing import Any
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    all_adapters,
    enabled_adapter_ids,
    get_adapter,
    list_catalog,
    reset_registry,
)
from src.market.infrastructure.adapters.router import (
    clear_sticky,
    fetch_capital_flow_routed,
    fetch_daily_best,
    fetch_daily_routed,
    fetch_live_quotes_routed,
    fetch_minute_routed,
    fetch_spot_routed,
    probe_lane,
)
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_MINUTE,
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
    ) -> None:
        self.meta = AdapterMeta(
            id=adapter_id,
            label=adapter_id,
            lanes=lanes,
            description="fake",
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


class FetchDailyBestTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_winner_is_fastest_success(self) -> None:
        reset_registry(
            [
                _FakeAdapter("slow", delay=0.12, frame=_daily_frame(2)),
                _FakeAdapter("fast", delay=0.02, frame=_daily_frame(5)),
            ]
        )
        frame, winner = fetch_daily_best("600519", max_workers=2)
        self.assertEqual(winner, "fast")
        self.assertEqual(len(frame), 5)

    def test_fast_success_does_not_wait_for_slow_success(self) -> None:
        reset_registry(
            [
                _FakeAdapter("slow", delay=0.35, frame=_daily_frame(2)),
                _FakeAdapter("fast", delay=0.02, frame=_daily_frame(5)),
            ]
        )
        started = time.perf_counter()
        frame, winner = fetch_daily_best("600519", max_workers=2)
        elapsed = time.perf_counter() - started

        self.assertEqual(winner, "fast")
        self.assertEqual(len(frame), 5)
        self.assertLess(elapsed, 0.25)

    def test_all_fail_raises(self) -> None:
        reset_registry(
            [
                _FakeAdapter("a", fail=True),
                _FakeAdapter("b", fail=True),
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            fetch_daily_best("600519")
        self.assertIn("全部 hist_daily", str(ctx.exception))

    def test_cancelled_queued_adapter_releases_request_gate(self) -> None:
        queued = [
            _FakeAdapter(f"queued_gate_{index}", delay=0.2, frame=_daily_frame(1))
            for index in range(5)
        ]
        fast = _FakeAdapter("fast_gate", frame=_daily_frame(2))
        reset_registry([fast, *queued])

        frame, winner = fetch_daily_best(
            "600519",
            adapter_ids=[fast.meta.id, *(adapter.meta.id for adapter in queued)],
            max_workers=1,
        )
        self.assertEqual(winner, fast.meta.id)
        self.assertEqual(len(frame), 2)

        # 线程池只能启动第一个 queued，其余 future 会在获胜后取消；被取消的
        # adapter 仍必须能在后续请求中重新获得 gate。
        frame, winner = fetch_daily_best(
            "600519", adapter_ids=[queued[-1].meta.id], max_workers=1
        )
        self.assertEqual(winner, queued[-1].meta.id)
        self.assertEqual(len(frame), 1)


class FetchSpotRoutedTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_same_slow_source_is_not_called_concurrently(self) -> None:
        started = threading.Event()
        release = threading.Event()
        adapter = _BlockingSpotAdapter(started, release)
        reset_registry([adapter])

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    fetch_spot_routed, ["600519"], adapter_ids=[adapter.meta.id]
                )
                self.assertTrue(started.wait(timeout=1))
                second = pool.submit(
                    fetch_spot_routed, ["600519"], adapter_ids=[adapter.meta.id]
                )
                with self.assertRaises(AdapterError) as ctx:
                    second.result(timeout=1)
                self.assertIn("请求进行中", str(ctx.exception))
                release.set()
                _frame, winner = first.result(timeout=2)
            self.assertEqual(winner, adapter.meta.id)
            self.assertEqual(adapter.calls, 1)
        finally:
            release.set()


class SinaAdapterWrapTests(unittest.TestCase):
    """确认 adapter 走现有 Source，不打真网。"""

    def test_fetch_daily_delegates_and_normalizes(self) -> None:
        class StubSource:
            def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
                self.seen = (code, instrument_type)
                return _daily_frame(turnover=0.01)

        stub: Any = StubSource()
        adapter = SinaAdapter(source=stub)  # type: ignore[arg-type]
        frame = adapter.fetch_daily("600519")
        self.assertEqual(stub.seen, ("600519", "STOCK"))
        self.assertAlmostEqual(float(frame["turnover"].iloc[0]), 0.01)


class StickyRouteTests(unittest.TestCase):
    def tearDown(self) -> None:
        from src.market.infrastructure.adapters.router import clear_sticky

        clear_sticky()
        reset_registry()

    def test_pins_winner_and_prefers_sticky(self) -> None:
        from src.market.infrastructure.adapters.router import fetch_daily_routed, peek_sticky

        slow = _FakeAdapter("slow", delay=0.08, frame=_daily_frame(2))
        fast = _FakeAdapter("fast", delay=0.01, frame=_daily_frame(5))
        reset_registry([slow, fast])

        frame, winner = fetch_daily_routed(
            "600519", adapter_ids=["slow", "fast"], max_workers=2
        )
        self.assertEqual(winner, "fast")
        self.assertEqual(peek_sticky(LANE_HIST_DAILY), "fast")
        self.assertEqual(len(frame), 5)

        class Counting(MarketAdapter):
            def __init__(self, inner: _FakeAdapter) -> None:
                self.inner = inner
                self.meta = inner.meta
                self.hits = 0

            def fetch_daily(
                self, code: str, *, instrument_type: str = "STOCK"
            ) -> pd.DataFrame:
                self.hits += 1
                return self.inner.fetch_daily(code, instrument_type=instrument_type)

        c_slow = Counting(slow)
        c_fast = Counting(fast)
        reset_registry([c_slow, c_fast])
        frame2, winner2 = fetch_daily_routed(
            "000001", adapter_ids=["slow", "fast"], sticky_ttl_sec=60.0
        )
        self.assertEqual(winner2, "fast")
        self.assertEqual(c_fast.hits, 1)
        self.assertEqual(c_slow.hits, 0)
        self.assertEqual(len(frame2), 5)

    def test_sticky_failure_re_races(self) -> None:
        from src.market.infrastructure.adapters.router import fetch_daily_routed, pin_sticky

        pin_sticky(LANE_HIST_DAILY, "broken", ttl_sec=60.0)
        broken = _FakeAdapter("broken", fail=True)
        ok = _FakeAdapter("ok", frame=_daily_frame(3))
        reset_registry([broken, ok])
        frame, winner = fetch_daily_routed(
            "600519", adapter_ids=["broken", "ok"], max_workers=2
        )
        self.assertEqual(winner, "ok")
        self.assertEqual(len(frame), 3)

    def test_enabled_prefs_filter(self) -> None:
        from unittest.mock import patch

        from src.market.infrastructure.adapters.registry import enabled_adapter_ids
        from src.market.infrastructure.adapters.router import fetch_daily_routed

        reset_registry(
            [
                _FakeAdapter("sina", frame=_daily_frame(1)),
                _FakeAdapter("eastmoney", frame=_daily_frame(2)),
            ]
        )
        with patch(
            "src.shared.paths.load_config",
            return_value={"lane_providers": {"sina": {"enabled": False}}},
        ):
            self.assertEqual(enabled_adapter_ids(LANE_HIST_DAILY), ["eastmoney"])
            _frame, winner = fetch_daily_routed("600519")
        self.assertEqual(winner, "eastmoney")

    def test_per_lane_prefs_only_mute_that_lane(self) -> None:
        """逐工具开关：关掉 sina 的日 K 不影响它的实时快照。"""
        from unittest.mock import patch

        from src.market.infrastructure.adapters.registry import (
            enabled_adapter_ids,
            lane_provider_enabled,
            provider_disabled_lanes,
            provider_master_enabled,
        )

        reset_registry(
            [
                _FakeAdapter("sina", lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH)),
                _FakeAdapter("eastmoney", lanes=(LANE_HIST_DAILY,)),
            ]
        )
        config = {"lane_providers": {"sina": {"lanes": {LANE_HIST_DAILY: False}}}}
        with patch("src.shared.paths.load_config", return_value=config):
            self.assertEqual(enabled_adapter_ids(LANE_HIST_DAILY), ["eastmoney"])
            self.assertEqual(enabled_adapter_ids(LANE_SPOT_BATCH), ["sina"])
            self.assertFalse(lane_provider_enabled("sina", LANE_HIST_DAILY))
            self.assertTrue(lane_provider_enabled("sina", LANE_SPOT_BATCH))
            # 源总开关仍是开的：停用的是工具，不是整家
            self.assertTrue(provider_master_enabled("sina"))
            self.assertEqual(provider_disabled_lanes("sina"), [LANE_HIST_DAILY])

    def test_master_switch_overrides_per_lane_prefs(self) -> None:
        from unittest.mock import patch

        from src.market.infrastructure.adapters.registry import enabled_adapter_ids

        reset_registry([_FakeAdapter("sina", lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH))])
        config = {
            "lane_providers": {"sina": {"enabled": False, "lanes": {LANE_HIST_DAILY: True}}}
        }
        with patch("src.shared.paths.load_config", return_value=config):
            self.assertEqual(enabled_adapter_ids(LANE_HIST_DAILY), [])
            self.assertEqual(enabled_adapter_ids(LANE_SPOT_BATCH), [])


class SyncRoutedTests(unittest.TestCase):
    """默认 sync 走 fetch_daily_routed（不注入 sources）。"""

    def tearDown(self) -> None:
        from src.market.infrastructure.adapters.router import clear_sticky

        clear_sticky()
        reset_registry()

    def test_sync_quotes_uses_routed_path(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from src.market.infrastructure.store import MarketStore
        from src.market.infrastructure.sync import sync_quotes

        temp = tempfile.TemporaryDirectory()
        try:
            db = Path(temp.name) / "m.db"
            with patch(
                "src.market.infrastructure.adapters.fetch_daily_routed",
                return_value=(_daily_frame(4), "sina"),
            ) as mocked:
                report = sync_quotes(
                    lambda: MarketStore(db),
                    ["600519"],
                    workers=1,
                    min_interval=0.0,
                    with_factors=False,
                    with_today_spot=False,
                    force=True,
                )
            mocked.assert_called()
            self.assertEqual(report.succeeded, 1)
            self.assertEqual(report.failed, 0)
        finally:
            temp.cleanup()

    def test_apply_today_spot_uses_spot_routed(self) -> None:
        import tempfile
        from datetime import date
        from pathlib import Path
        from unittest.mock import patch

        from src.market.infrastructure.store import MarketStore
        from src.market.infrastructure.sync import apply_today_spot

        temp = tempfile.TemporaryDirectory()
        try:
            db = Path(temp.name) / "m.db"
            store = MarketStore(db)
            store.upsert_quotes("600519", _daily_frame(2), source="hist")
            today = date.today()
            # 模拟交易时段：日历里先有今天（非交易日会被 apply_today_spot 钳制跳过）
            store.upsert_quotes(
                "600519",
                pd.DataFrame(
                    [
                        {
                            "date": today,
                            "open": 1.0,
                            "high": 2.0,
                            "low": 0.5,
                            "close": 1.5,
                            "volume": 100.0,
                            "amount": 150.0,
                            "outstanding_share": 1e9,
                            "turnover": 0.001,
                        }
                    ]
                ),
                source="hist",
            )
            fake = pd.DataFrame(
                [
                    {
                        "code": "600519",
                        "date": today,
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100.0,
                        "amount": 150.0,
                    }
                ]
            )
            with patch(
                "src.market.infrastructure.adapters.fetch_spot_routed",
                return_value=(fake, "sina"),
            ) as mocked:
                n = apply_today_spot(store, ["600519"])
            mocked.assert_called_once()
            self.assertEqual(n, 1)
            store.close()
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
