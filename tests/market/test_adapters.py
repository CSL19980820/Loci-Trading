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


class RegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sticky()
        reset_registry()

    def test_default_catalog_has_chinese_labels(self) -> None:
        catalog = list_catalog()
        ids = {item["id"] for item in catalog}
        self.assertEqual(ids, {"sina", "eastmoney", "tencent", "tdx", "exchange_list"})
        labels = {item["id"]: item["label"] for item in catalog}
        self.assertEqual(labels["sina"], "新浪直连")
        self.assertEqual(labels["eastmoney"], "东财")
        self.assertEqual(labels["tencent"], "腾讯财经")
        self.assertEqual(labels["tdx"], "通达信")
        self.assertEqual(labels["exchange_list"], "交易所列表")

    def test_default_catalog_exposes_base_url_for_source_detail(self) -> None:
        base_urls = {item["id"]: item["base_url"] for item in list_catalog()}
        self.assertEqual(base_urls["sina"], "https://finance.sina.com.cn")
        self.assertEqual(base_urls["tencent"], "https://proxy.finance.qq.com")
        self.assertEqual(base_urls["eastmoney"], "https://www.eastmoney.com")
        # 三家交易所没有单一来源域名，留空好过挑一个冒充全部。
        self.assertEqual(base_urls["exchange_list"], "")

    def test_adapters_for_lane(self) -> None:
        hist = {a.meta.id for a in adapters_for_lane(LANE_HIST_DAILY)}
        self.assertEqual(hist, {"sina", "eastmoney", "tencent"})
        spot = {a.meta.id for a in adapters_for_lane(LANE_SPOT_BATCH)}
        self.assertEqual(spot, {"sina", "eastmoney", "tencent"})
        minute = [a.meta.id for a in adapters_for_lane(LANE_MINUTE)]
        self.assertEqual(set(minute), {"eastmoney", "sina", "tdx"})
        # 分时默认通达信最高优先（注册表顺序即 auto 路由顺序）。
        self.assertEqual(minute[0], "tdx")
        self.assertEqual(enabled_adapter_ids(LANE_MINUTE, config={})[0], "tdx")
        capital = {a.meta.id for a in adapters_for_lane(LANE_CAPITAL_FLOW)}
        self.assertEqual(capital, {"eastmoney"})
        instruments = {a.meta.id for a in adapters_for_lane(LANE_INSTRUMENTS)}
        self.assertEqual(instruments, {"exchange_list"})

    def test_get_adapter_and_all(self) -> None:
        self.assertEqual(get_adapter("sina").meta.id, "sina")
        with self.assertRaises(KeyError):
            get_adapter("nope")
        self.assertGreaterEqual(len(all_adapters()), 4)

    def test_reset_injects_fakes(self) -> None:
        reset_registry([_FakeAdapter("a"), _FakeAdapter("b", lanes=(LANE_SPOT_BATCH,))])
        self.assertEqual([a.meta.id for a in all_adapters()], ["a", "b"])
        self.assertEqual(len(adapters_for_lane(LANE_HIST_DAILY)), 1)

    def test_manual_route_without_fallback_excludes_other_enabled_adapters(self) -> None:
        first = _FakeAdapter("first")
        selected = _FakeAdapter("selected", fail=True)
        reset_registry([first, selected])
        config = {
            "lane_routes": {
                LANE_HIST_DAILY: {
                    "mode": "manual",
                    "provider_id": "selected",
                    "fallback": False,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            self.assertEqual(enabled_adapter_ids(LANE_HIST_DAILY), ["selected"])
            with self.assertRaises(AdapterError):
                fetch_daily_routed("600519")
        self.assertEqual(first.fetch_calls, 0)

    def test_manual_route_with_fallback_prefers_selected_then_default_order(self) -> None:
        reset_registry([_FakeAdapter("first"), _FakeAdapter("selected"), _FakeAdapter("third")])
        config = {
            "lane_routes": {
                LANE_HIST_DAILY: {
                    "mode": "manual",
                    "provider_id": "selected",
                    "fallback": True,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            self.assertEqual(
                enabled_adapter_ids(LANE_HIST_DAILY), ["selected", "first", "third"]
            )

    def test_manual_daily_fallback_keeps_slow_selected_source_when_it_succeeds(self) -> None:
        selected = _FakeAdapter("selected", delay=0.05)
        faster = _FakeAdapter("faster")
        reset_registry([selected, faster])
        config = {
            "lane_routes": {
                LANE_HIST_DAILY: {
                    "mode": "manual",
                    "provider_id": "selected",
                    "fallback": True,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            _, adapter_id = fetch_daily_routed("600519")
        self.assertEqual(adapter_id, "selected")
        self.assertEqual(faster.fetch_calls, 0)

    def test_manual_daily_fallback_uses_other_source_only_after_selected_fails(self) -> None:
        selected = _FakeAdapter("selected", fail=True)
        fallback = _FakeAdapter("fallback")
        reset_registry([selected, fallback])
        config = {
            "lane_routes": {
                LANE_HIST_DAILY: {
                    "mode": "manual",
                    "provider_id": "selected",
                    "fallback": True,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            _, adapter_id = fetch_daily_routed("600519")
        self.assertEqual(adapter_id, "fallback")
        self.assertEqual(selected.fetch_calls, 1)

    def test_manual_spot_live_without_fallback_never_calls_another_provider(self) -> None:
        selected = _FakeAdapter("sina", lanes=(LANE_SPOT_BATCH,), fail=True)
        fallback = _FakeAdapter(
            "tencent",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[{"code": "600519", "source": "tencent"}],
        )
        reset_registry([selected, fallback])
        config = {
            "lane_routes": {
                LANE_SPOT_BATCH: {
                    "mode": "manual",
                    "provider_id": "sina",
                    "fallback": False,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            with self.assertRaises(AdapterError):
                fetch_live_quotes_routed(["600519"])

        self.assertEqual(selected.live_fetch_calls, 1)
        self.assertEqual(fallback.live_fetch_calls, 0)

    def test_manual_spot_live_uses_selected_source_before_fast_sources(self) -> None:
        selected = _FakeAdapter(
            "eastmoney",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[{"code": "600519", "source": "eastmoney"}],
        )
        sina = _FakeAdapter(
            "sina",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[{"code": "600519", "source": "sina"}],
        )
        tencent = _FakeAdapter(
            "tencent",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[{"code": "600519", "source": "tencent"}],
        )
        reset_registry([selected, sina, tencent])
        config = {
            "lane_routes": {
                LANE_SPOT_BATCH: {
                    "mode": "manual",
                    "provider_id": "eastmoney",
                    "fallback": True,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            rows, adapter_id = fetch_live_quotes_routed(["600519"])

        self.assertEqual(adapter_id, "eastmoney")
        self.assertEqual(rows[0]["source"], "eastmoney")
        self.assertEqual(selected.live_fetch_calls, 1)
        self.assertEqual(sina.live_fetch_calls, 0)
        self.assertEqual(tencent.live_fetch_calls, 0)

    def test_manual_spot_live_falls_back_in_configured_order_after_empty_result(self) -> None:
        call_order: list[str] = []
        selected = _FakeAdapter(
            "eastmoney",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[],
            live_call_order=call_order,
        )
        sina = _FakeAdapter(
            "sina",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[{"code": "600519", "source": "sina"}],
            live_call_order=call_order,
        )
        tencent = _FakeAdapter(
            "tencent",
            lanes=(LANE_SPOT_BATCH,),
            live_rows=[{"code": "600519", "source": "tencent"}],
            live_call_order=call_order,
        )
        reset_registry([selected, sina, tencent])
        config = {
            "lane_routes": {
                LANE_SPOT_BATCH: {
                    "mode": "manual",
                    "provider_id": "eastmoney",
                    "fallback": True,
                }
            }
        }
        with mock.patch("src.shared.paths.load_config", return_value=config):
            rows, adapter_id = fetch_live_quotes_routed(["600519"])

        self.assertEqual(adapter_id, "sina")
        self.assertEqual(rows[0]["source"], "sina")
        self.assertEqual(call_order, ["eastmoney", "sina"])
        self.assertEqual(tencent.live_fetch_calls, 0)

    def test_auto_spot_live_keeps_sina_tencent_race(self) -> None:
        reset_registry(
            [
                _FakeAdapter("eastmoney", lanes=(LANE_SPOT_BATCH,)),
                _FakeAdapter("sina", lanes=(LANE_SPOT_BATCH,)),
                _FakeAdapter("tencent", lanes=(LANE_SPOT_BATCH,)),
            ]
        )
        raced_rows = [{"code": "600519", "source": "tencent"}]
        with mock.patch("src.shared.paths.load_config", return_value={}), mock.patch(
            "src.market.infrastructure.adapters.router._race_live_quotes",
            return_value=(raced_rows, "tencent"),
        ) as race:
            rows, adapter_id = fetch_live_quotes_routed(["600519"])

        self.assertEqual((rows, adapter_id), (raced_rows, "tencent"))
        self.assertEqual(race.call_args.args[0], ["sina", "tencent"])

    def test_minute_and_capital_routes_reject_disabled_or_incompatible_sources(self) -> None:
        reset_registry([_FakeAdapter("special", lanes=(LANE_MINUTE, LANE_CAPITAL_FLOW))])
        disabled = {"lane_providers": {"special": {"enabled": False}}}
        with mock.patch("src.shared.paths.load_config", return_value=disabled):
            with self.assertRaisesRegex(AdapterError, "没有启用的 minute_bars"):
                fetch_minute_routed("600519")
            with self.assertRaisesRegex(AdapterError, "没有启用的 capital_flow"):
                fetch_capital_flow_routed("600519")

        reset_registry([_FakeAdapter("hist_only")])
        with self.assertRaisesRegex(AdapterError, "没有启用的 minute_bars"):
            fetch_minute_routed("600519")


class ProbeLaneParallelTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_probe_lane_runs_in_parallel(self) -> None:
        """两个各 sleep 0.15s 的 probe，墙钟应明显小于串行之和。"""
        reset_registry(
            [
                _FakeAdapter("slow_a", delay=0.15),
                _FakeAdapter("slow_b", delay=0.15),
            ]
        )
        started = time.perf_counter()
        results = probe_lane(LANE_HIST_DAILY, max_workers=2)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))
        # 串行约 0.30s；并行应 < 0.28（留余量给调度抖动）
        self.assertLess(elapsed, 0.28)

    def test_probe_lane_preserves_order(self) -> None:
        reset_registry(
            [
                _FakeAdapter("first", delay=0.05),
                _FakeAdapter("second", delay=0.01),
            ]
        )
        results = probe_lane(LANE_HIST_DAILY)
        self.assertEqual([r.adapter_id for r in results], ["first", "second"])

    def test_probe_unsupported_lane_filtered_by_resolve(self) -> None:
        """只声明 spot 的 adapter 不会进 hist_daily 探测列表。"""
        reset_registry([_FakeAdapter("spot_only", lanes=(LANE_SPOT_BATCH,))])
        self.assertEqual(probe_lane(LANE_HIST_DAILY), [])

    def test_base_probe_and_router_pass_sample_code(self) -> None:
        adapter = _CodeProbeAdapter()
        reset_registry([adapter])
        result = probe_lane(LANE_HIST_DAILY, code="000001")
        self.assertTrue(result[0].ok)
        self.assertEqual(adapter.code_seen, "000001")


class NormalizeUnitTests(unittest.TestCase):
    def test_eastmoney_turnover_percent_to_fraction(self) -> None:
        """东财换手率是百分数：5.0 → 0.05；成交量手→股。"""
        raw = pd.DataFrame(
            {
                "日期": ["2026-01-05"],
                "开盘": [10.0],
                "最高": [11.0],
                "最低": [9.0],
                "收盘": [10.5],
                "成交量": [1000.0],
                "成交额": [1e6],
                "换手率": [5.0],
            }
        )
        out = EastmoneyAdapter._normalize_daily(raw)
        self.assertAlmostEqual(float(out["turnover"].iloc[0]), 0.05)
        self.assertAlmostEqual(float(out["volume"].iloc[0]), 100_000.0)
        for col in ("date", "open", "high", "low", "close", "volume", "amount"):
            self.assertIn(col, out.columns)

    def test_eastmoney_already_renamed_percent(self) -> None:
        """原始百分数（未走 Source）走默认 turnover_as_percent=True。"""
        raw = _daily_frame(turnover=12.3)
        out = EastmoneyAdapter._normalize_daily(raw)
        self.assertAlmostEqual(float(out["turnover"].iloc[0]), 0.123)

    def test_eastmoney_source_fraction_not_double_divided(self) -> None:
        """经 Source 已是小数时，adapter 不得再 /100。"""
        raw = _daily_frame(turnover=0.05)
        out = EastmoneyAdapter._normalize_daily(raw, turnover_as_percent=False)
        self.assertAlmostEqual(float(out["turnover"].iloc[0]), 0.05)

    def test_sina_turnover_stays_fraction(self) -> None:
        """新浪直连已是 volume/shares 小数，normalize 不得再 /100。"""
        raw = _daily_frame(turnover=0.05)
        out = SinaAdapter._normalize_daily(raw)
        self.assertAlmostEqual(float(out["turnover"].iloc[0]), 0.05)

    def test_sina_rejects_missing_columns(self) -> None:
        with self.assertRaises(AdapterError):
            SinaAdapter._normalize_daily(pd.DataFrame({"date": ["2026-01-01"]}))

    def test_tencent_turnover_stays_fraction(self) -> None:
        raw = _daily_frame(turnover=0.05)
        out = TencentAdapter._normalize_daily(raw)
        self.assertAlmostEqual(float(out["turnover"].iloc[0]), 0.05)

    def test_tencent_rejects_missing_columns(self) -> None:
        with self.assertRaises(AdapterError):
            TencentAdapter._normalize_daily(pd.DataFrame({"date": ["2026-01-01"]}))




if __name__ == "__main__":
    unittest.main()
