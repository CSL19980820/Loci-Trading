"""现货路由、粘性线路与同步侧路由。

从 `test_adapters_routing.py` 拆出（原 678 行）；日线竞速与合并用例仍在原文件。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any
import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.registry import enabled_adapter_ids, reset_registry
from src.market.infrastructure.adapters.router import (
    clear_sticky,
    fetch_daily_routed,
    fetch_spot_routed,
)
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.types import LANE_HIST_DAILY, LANE_SPOT_BATCH

from tests.market.adapter_fakes import _BlockingSpotAdapter, _FakeAdapter, _daily_frame


class FetchSpotRoutedTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_same_slow_source_is_not_called_concurrently(self) -> None:
        """源忙时 claim_wait_sec=0 应立刻跳过，而不是双开同一适配器。"""
        started = threading.Event()
        release = threading.Event()
        adapter = _BlockingSpotAdapter(started, release)
        reset_registry([adapter])

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    fetch_spot_routed,
                    ["600519"],
                    adapter_ids=[adapter.meta.id],
                )
                self.assertTrue(started.wait(timeout=1))
                second = pool.submit(
                    fetch_spot_routed,
                    ["600519"],
                    adapter_ids=[adapter.meta.id],
                    claim_wait_sec=0.0,
                )
                with self.assertRaises(AdapterError) as ctx:
                    second.result(timeout=2)
                self.assertTrue(
                    "等待来源空闲超时" in str(ctx.exception)
                    or "请求进行中" in str(ctx.exception)
                    or "全部" in str(ctx.exception)
                    or "失败" in str(ctx.exception),
                    msg=str(ctx.exception),
                )
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

    def test_pins_primary_and_prefers_sticky(self) -> None:
        """粘性钉的是协作合并主源（优先序），不是 RTT 最快源。"""
        from src.market.infrastructure.adapters.router import fetch_daily_routed, peek_sticky

        slow = _FakeAdapter("slow", delay=0.08, frame=_daily_frame(2))
        fast = _FakeAdapter("fast", delay=0.01, frame=_daily_frame(5))
        reset_registry([slow, fast])

        frame, winner = fetch_daily_routed(
            "600519", adapter_ids=["fast", "slow"], max_workers=2, cross_check=True
        )
        self.assertEqual(winner, "fast")
        self.assertEqual(peek_sticky(LANE_HIST_DAILY), "fast")
        self.assertGreaterEqual(len(frame), 2)

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
            "000001",
            adapter_ids=["slow", "fast"],
            sticky_ttl_sec=60.0,
            cross_check=True,
        )
        # sticky=fast → 优先序前置；显式交叉校验时协作合并仍打齐各源
        self.assertEqual(winner2, "fast")
        self.assertEqual(c_fast.hits, 1)
        self.assertEqual(c_slow.hits, 1)
        self.assertGreaterEqual(len(frame2), 2)

    def test_uncensored_codes_only_hit_primary(self) -> None:
        """未抽中交叉校验的票只打主源——这是全市场同步提速的关键契约。

        协作合并对每票都跑时，单票成本是「启用源数」倍，最慢的源会把整票
        拖到和它一样慢（证券宝实测 1.7~30s/票）。抽样后多数票只付一次主源。
        """
        from src.market.infrastructure.adapters.router import (
            fetch_daily_routed,
            should_cross_check,
        )

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

        primary = Counting(_FakeAdapter("primary", frame=_daily_frame(4)))
        backup = Counting(_FakeAdapter("backup", frame=_daily_frame(4)))
        reset_registry([primary, backup])

        # 000001 不被 50 整除 → 不抽中交叉校验
        self.assertFalse(should_cross_check("000001"))
        frame, winner = fetch_daily_routed(
            "000001", adapter_ids=["primary", "backup"]
        )
        self.assertEqual(winner, "primary")
        self.assertEqual(primary.hits, 1)
        self.assertEqual(backup.hits, 0, "未抽中的票不该再打第二个源")
        self.assertEqual(len(frame), 4)

        # 抽中的票（能被 50 整除）仍走协作合并，打齐各源
        self.assertTrue(should_cross_check("000100"))
        primary.hits = 0
        backup.hits = 0
        fetch_daily_routed("000100", adapter_ids=["primary", "backup"])
        self.assertEqual(primary.hits, 1)
        self.assertEqual(backup.hits, 1, "抽中的票必须真的做交叉校验")

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
