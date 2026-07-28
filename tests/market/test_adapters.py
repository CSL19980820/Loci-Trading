"""数据线路适配器层单测 —— 不打真网。"""
from __future__ import annotations

import time
import unittest
from typing import Any
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    all_adapters,
    get_adapter,
    list_catalog,
    reset_registry,
)
from src.market.infrastructure.adapters.router import fetch_daily_best, probe_lane
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

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise AdapterError(f"{self.meta.id} 故意失败")
        return self.frame.copy()

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


class RegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_default_catalog_has_chinese_labels(self) -> None:
        catalog = list_catalog()
        ids = {item["id"] for item in catalog}
        self.assertEqual(ids, {"sina", "eastmoney", "tencent", "exchange_list"})
        labels = {item["id"]: item["label"] for item in catalog}
        self.assertEqual(labels["sina"], "新浪直连")
        self.assertEqual(labels["eastmoney"], "东财")
        self.assertEqual(labels["tencent"], "腾讯财经")
        self.assertEqual(labels["exchange_list"], "交易所列表")

    def test_adapters_for_lane(self) -> None:
        hist = {a.meta.id for a in adapters_for_lane(LANE_HIST_DAILY)}
        self.assertEqual(hist, {"sina", "eastmoney", "tencent"})
        spot = {a.meta.id for a in adapters_for_lane(LANE_SPOT_BATCH)}
        self.assertEqual(spot, {"sina", "eastmoney", "tencent"})
        minute = {a.meta.id for a in adapters_for_lane(LANE_MINUTE)}
        self.assertEqual(minute, {"eastmoney"})
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


class NormalizeUnitTests(unittest.TestCase):
    def test_eastmoney_turnover_percent_to_fraction(self) -> None:
        """东财换手率是百分数：5.0 → 0.05。"""
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


def _tencent_spot_line(
    symbol: str = "sh600519",
    *,
    name: str = "贵州茅台",
    code: str = "600519",
    price: float = 1320.0,
    prev: float = 1289.5,
    open_: float = 1299.0,
    high: float = 1320.0,
    low: float = 1289.52,
    lots: float = 531.0,
    amount: float = 6960058121.0,
) -> str:
    fields = [""] * 38
    fields[0] = "1"
    fields[1] = name
    fields[2] = code
    fields[3] = f"{price:.2f}"
    fields[4] = f"{prev:.2f}"
    fields[5] = f"{open_:.2f}"
    fields[30] = "20260728143000"
    fields[31] = f"{price - prev:.2f}"
    fields[32] = f"{(price - prev) / prev * 100:.2f}"
    fields[33] = f"{high:.2f}"
    fields[34] = f"{low:.2f}"
    fields[35] = f"{price:.2f}/{lots:.0f}/{amount:.0f}"
    fields[36] = f"{lots:.0f}"
    fields[37] = f"{amount / 10000:.0f}"
    return f'v_{symbol}="' + "~".join(fields) + '";'


class TencentModuleTests(unittest.TestCase):
    def test_parse_spot_line(self) -> None:
        from src.market import tencent

        row = tencent._parse_spot_row(_tencent_spot_line())
        assert row is not None
        self.assertEqual(row["symbol"], "sh600519")
        self.assertAlmostEqual(row["close"], 1320.0)
        self.assertAlmostEqual(row["volume"], 53100.0)
        self.assertAlmostEqual(row["amount"], 6960058121.0)

    def test_parse_live_row(self) -> None:
        from src.market import tencent

        row = tencent._parse_live_row(_tencent_spot_line())
        assert row is not None
        self.assertEqual(row["source"], "tencent")
        self.assertAlmostEqual(row["price"], 1320.0)

    def test_parse_daily_rows(self) -> None:
        from src.market import tencent

        raw = [["2026-07-28", "1299.000", "1320.000", "1320.000", "1289.520", "531.000"]]
        frame = tencent._parse_daily_rows(raw)
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(float(frame["volume"].iloc[0]), 53100.0)
        self.assertAlmostEqual(float(frame["close"].iloc[0]), 1320.0)

    def test_fetch_spot_mocked(self) -> None:
        from src.market import tencent

        with mock.patch(
            "src.market.infrastructure.tencent._get",
            return_value=_tencent_spot_line(),
        ):
            frame = tencent.fetch_spot(["sh600519"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["symbol"], "sh600519")

    def test_fetch_daily_recent_mocked(self) -> None:
        from src.market import tencent

        payload = (
            '{"code":0,"data":{"sh600519":{"day":'
            '[["2026-07-28","1299.000","1320.000","1320.000","1289.520","531.000"]]'
            "}}}"
        )
        with mock.patch("src.market.infrastructure.tencent._get", return_value=payload):
            frame = tencent.fetch_daily_recent("sh600519", count=5)
        self.assertEqual(len(frame), 1)
        adapter = TencentAdapter()
        out = adapter._normalize_daily(frame)
        self.assertIn("amount", out.columns)

    def test_adapter_fetch_spot_mocked(self) -> None:
        adapter = TencentAdapter()
        spot = pd.DataFrame(
            [
                {
                    "symbol": "sh600519",
                    "date": pd.Timestamp("2026-07-28").date(),
                    "open": 1299.0,
                    "high": 1320.0,
                    "low": 1289.52,
                    "close": 1320.0,
                    "volume": 53100.0,
                    "amount": 6960058121.0,
                }
            ]
        )
        with mock.patch("src.market.infrastructure.tencent.fetch_spot", return_value=spot):
            frame = adapter.fetch_spot(["600519"])
        self.assertEqual(frame.iloc[0]["code"], "600519")


def _spot_em_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "最新价": 1800.0,
                "今开": 1790.0,
                "最高": 1810.0,
                "最低": 1785.0,
                "昨收": 1795.0,
                "成交量": 10000.0,
                "成交额": 1.8e7,
                "涨跌幅": 0.28,
                "涨跌额": 5.0,
            },
            {
                "代码": "000001",
                "名称": "平安银行",
                "最新价": 10.5,
                "今开": 10.4,
                "最高": 10.6,
                "最低": 10.3,
                "昨收": 10.4,
                "成交量": 500000.0,
                "成交额": 5.25e6,
                "涨跌幅": 0.96,
                "涨跌额": 0.1,
            },
        ]
    )


class EastmoneySpotMinuteCapitalTests(unittest.TestCase):
    def test_fetch_spot_filters_codes(self) -> None:
        adapter = EastmoneyAdapter()
        with mock.patch.object(
            adapter, "_fetch_spot_em", return_value=_spot_em_frame()
        ):
            out = adapter.fetch_spot(["600519", "999999"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["code"], "600519")
        for col in ("open", "high", "low", "close", "volume", "amount", "date"):
            self.assertIn(col, out.columns)

    def test_fetch_live_quotes_rich_fields(self) -> None:
        adapter = EastmoneyAdapter()
        with mock.patch.object(
            adapter, "_fetch_spot_em", return_value=_spot_em_frame()
        ):
            rows = adapter.fetch_live_quotes(["600519"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["code"], "600519")
        self.assertEqual(row["name"], "贵州茅台")
        self.assertEqual(row["price"], 1800.0)
        self.assertEqual(row["prev_close"], 1795.0)
        self.assertEqual(row["source"], "eastmoney")

    def test_fetch_minute_normalizes(self) -> None:
        raw = pd.DataFrame(
            {
                "时间": ["2026-07-28 09:31:00", "2026-07-28 09:32:00"],
                "开盘": [10.0, 10.1],
                "收盘": [10.05, 10.2],
                "最高": [10.1, 10.25],
                "最低": [9.95, 10.05],
                "成交量": [1000, 1200],
                "成交额": [10050.0, 12240.0],
                "均价": [10.02, 10.15],
            }
        )
        adapter = EastmoneyAdapter()
        with mock.patch(
            "src.market.infrastructure.adapters.eastmoney_adapter._import_akshare"
        ) as mocked:
            mocked.return_value.stock_zh_a_hist_min_em.return_value = raw
            out = adapter.fetch_minute("600519", period="1", days=1)
        self.assertEqual(len(out), 2)
        self.assertIn("datetime", out.columns)
        self.assertAlmostEqual(float(out["close"].iloc[0]), 10.05)

    def test_fetch_capital_flow_normalizes(self) -> None:
        raw = pd.DataFrame(
            {
                "日期": ["2026-07-25", "2026-07-28"],
                "收盘价": [10.0, 10.5],
                "涨跌幅": [1.0, 5.0],
                "主力净流入-净额": [1e6, 2e6],
                "主力净流入-净占比": [5.0, 8.0],
            }
        )
        adapter = EastmoneyAdapter()
        with mock.patch(
            "src.market.infrastructure.adapters.eastmoney_adapter._import_akshare"
        ) as mocked:
            mocked.return_value.stock_individual_fund_flow.return_value = raw
            out = adapter.fetch_capital_flow("600519")
        self.assertEqual(len(out), 2)
        self.assertIn("date", out.columns)
        self.assertIn("main_net_inflow", out.columns)
        self.assertAlmostEqual(float(out["main_net_inflow"].iloc[1]), 2e6)

    def test_probe_spot_batch_mocked(self) -> None:
        adapter = EastmoneyAdapter()
        with mock.patch.object(
            adapter, "_fetch_spot_em", return_value=_spot_em_frame()
        ):
            result = adapter.probe(LANE_SPOT_BATCH)
        self.assertTrue(result.ok)
        self.assertEqual(result.lane, LANE_SPOT_BATCH)
        self.assertEqual(result.rows, 1)

    def test_probe_minute_and_capital_mocked(self) -> None:
        adapter = EastmoneyAdapter()
        minute_raw = pd.DataFrame(
            {
                "时间": ["2026-07-28 09:31:00"],
                "开盘": [10.0],
                "收盘": [10.05],
                "最高": [10.1],
                "最低": [9.95],
                "成交量": [1000],
                "成交额": [10050.0],
            }
        )
        capital_raw = pd.DataFrame(
            {
                "日期": ["2026-07-28"],
                "收盘价": [10.5],
                "涨跌幅": [5.0],
                "主力净流入-净额": [2e6],
                "主力净流入-净占比": [8.0],
            }
        )
        with mock.patch(
            "src.market.infrastructure.adapters.eastmoney_adapter._import_akshare"
        ) as mocked:
            mocked.return_value.stock_zh_a_hist_min_em.return_value = minute_raw
            mocked.return_value.stock_individual_fund_flow.return_value = capital_raw
            min_result = adapter.probe(LANE_MINUTE)
            cap_result = adapter.probe(LANE_CAPITAL_FLOW)
        self.assertTrue(min_result.ok)
        self.assertTrue(cap_result.ok)


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
