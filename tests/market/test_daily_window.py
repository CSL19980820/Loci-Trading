"""日 K 近窗增量：盘中同步不该每天重拉全历史。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import MarketAdapter, window_start_date
from src.market.infrastructure.adapters.registry import reset_registry
from src.market.infrastructure.adapters.router import fetch_daily_best
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import AdapterMeta, LANE_HIST_DAILY
from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.sync import sync_quotes


def _bars(dates: list[str]) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.5] * n,
            "volume": [1_000_000.0] * n,
            "amount": [10_500_000.0] * n,
            "outstanding_share": [1e9] * n,
            "turnover": [0.001] * n,
        }
    )


class _WindowAdapter(MarketAdapter):
    def __init__(self, adapter_id: str = "fake") -> None:
        self.meta = AdapterMeta(
            id=adapter_id, label=adapter_id, lanes=(LANE_HIST_DAILY,), description="fake"
        )
        self.full_calls = 0
        self.window_bars: list[int] = []

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        self.full_calls += 1
        return _bars(["2026-01-05", "2026-01-06"])

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        self.window_bars.append(bars)
        return _bars(["2026-01-06"])


class _FullOnlyAdapter(MarketAdapter):
    """没实现近窗的第三方源：必须仍能拿到可落库的一张表。"""

    meta = AdapterMeta(
        id="fullonly", label="fullonly", lanes=(LANE_HIST_DAILY,), description="fake"
    )

    def __init__(self) -> None:
        self.calls = 0

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        self.calls += 1
        return _bars(["2026-01-05", "2026-01-06"])


class RouterWindowTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_router_asks_the_adapter_for_a_window(self) -> None:
        adapter = _WindowAdapter()
        reset_registry([adapter])

        frame, winner = fetch_daily_best("600519", recent_bars=30)

        self.assertEqual(winner, "fake")
        self.assertEqual(adapter.window_bars, [30])
        self.assertEqual(adapter.full_calls, 0)
        self.assertEqual(len(frame), 1)

    def test_adapter_without_window_support_returns_full_history(self) -> None:
        adapter = _FullOnlyAdapter()
        reset_registry([adapter])

        frame, _winner = fetch_daily_best("600519", recent_bars=30)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(len(frame), 2)

    def test_tencent_window_fetches_a_single_page(self) -> None:
        with mock.patch(
            "src.market.infrastructure.tencent.fetch_daily_recent",
            return_value=_bars(["2026-01-06"]),
        ) as recent, mock.patch(
            "src.market.infrastructure.tencent.fetch_daily",
            side_effect=AssertionError("近窗不该分页拉全历史"),
        ):
            frame = TencentAdapter().fetch_daily_window("600519", bars=25)

        self.assertEqual(len(frame), 1)
        self.assertEqual(recent.call_args.kwargs["count"], 25)

    def test_tencent_window_beyond_one_page_falls_back_to_full(self) -> None:
        with mock.patch(
            "src.market.infrastructure.tencent.fetch_daily",
            return_value=_bars(["2026-01-05", "2026-01-06"]),
        ) as full:
            frame = TencentAdapter().fetch_daily_window("600519", bars=5000)

        self.assertEqual(len(frame), 2)
        full.assert_called_once()

    def test_tencent_window_skips_same_host_after_connect_timeout(self) -> None:
        from src.market import tencent

        calls: list[str] = []
        payload = (
            '{"code":0,"data":{"sh600611":{"day":'
            '[["2026-08-12","3.80","3.85","3.90","3.75","100"]]'
            "}}}"
        )

        def primary_timeout(url: str, **kwargs: object) -> str:
            calls.append(url)
            if url == tencent.DAILY_URL:
                raise tencent.TencentFetchError("请求失败：ConnectTimeout")
            if tencent._is_direct_ifzq(url):
                self.assertEqual(kwargs.get("connect_timeout"), tencent.IFZQ_CONNECT_TIMEOUT)
                self.assertEqual(kwargs.get("retries"), 0)
            return payload

        with mock.patch(
            "src.market.infrastructure.tencent._get", side_effect=primary_timeout
        ):
            frame = tencent.fetch_daily_recent("sh600611", count=20)

        self.assertEqual(len(frame), 1)
        self.assertEqual(calls, [tencent.DAILY_URL, tencent.DAILY_URL_FALLBACK])
        self.assertNotIn(tencent.DAILY_URL_PROXY_KLINE, calls)

    def test_tencent_window_tries_proxy_kline_after_primary_waf(self) -> None:
        from src.market import tencent

        calls: list[str] = []
        payload = (
            '{"code":0,"data":{"sh600611":{"day":'
            '[["2026-08-12","3.80","3.85","3.90","3.75","100"]]'
            "}}}"
        )

        def waf_then_ok(url: str, **kwargs: object) -> str:
            calls.append(url)
            if url == tencent.DAILY_URL:
                raise tencent.TencentFetchError("返回 501")
            if tencent._is_direct_ifzq(url):
                self.assertEqual(kwargs.get("connect_timeout"), tencent.IFZQ_CONNECT_TIMEOUT)
                self.assertEqual(kwargs.get("retries"), 0)
            return payload

        with mock.patch(
            "src.market.infrastructure.tencent._get", side_effect=waf_then_ok
        ):
            frame = tencent.fetch_daily_recent("sh600611", count=20)

        self.assertEqual(len(frame), 1)
        self.assertEqual(calls, [tencent.DAILY_URL, tencent.DAILY_URL_PROXY_KLINE])

    def test_tencent_window_uses_flashdata_when_ifzq_hosts_fail(self) -> None:
        from src.market import tencent

        calls: list[str] = []
        flash = "start=250101\n250812 3.80 3.85 3.90 3.75 100\n"

        def boom(url: str, **_kwargs: object) -> str:
            calls.append(url)
            if "flashdata" in url:
                return flash
            raise tencent.TencentFetchError("请求失败：ConnectTimeout")

        with mock.patch("src.market.infrastructure.tencent._get", side_effect=boom):
            frame = tencent.fetch_daily_recent("sz300021", count=20)

        self.assertEqual(len(frame), 1)
        self.assertEqual(pd.Timestamp(frame["date"].iloc[0]).strftime("%Y-%m-%d"), "2025-08-12")
        self.assertAlmostEqual(float(frame["volume"].iloc[0]), 10000.0)
        self.assertTrue(any("flashdata" in url for url in calls))
        self.assertNotIn(tencent.DAILY_URL_PROXY_KLINE, calls)

    def test_tencent_page_reads_qfqday_when_day_missing(self) -> None:
        from src.market import tencent

        payload = (
            '{"code":0,"data":{"sz300021":{"qfqday":'
            '[["2026-08-12","3.80","3.85","3.90","3.75","100"]]'
            "}}}"
        )
        with mock.patch("src.market.infrastructure.tencent._get", return_value=payload):
            frame = tencent.fetch_daily_recent("sz300021", count=5)
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(float(frame["close"].iloc[0]), 3.85)


class IncrementalWindowTests(unittest.TestCase):
    """全市场每天重拉全历史 = 把来源打到超时 + 白写几百万行。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.store = MarketStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _seed(self, *, earliest: str, last: str) -> None:
        self.store.upsert_quotes("600519", _bars([earliest, last]), source="hist")
        self.store.set_watermark("600519", last_trade_date=last, status="ok")
        # 今天同步过的会被 watermark 直接跳过；这里模拟「今天还没同步」。
        self.store.conn.execute(
            "UPDATE ingest_watermark SET last_synced_at = ? WHERE code = '600519'",
            (f"{(date.today() - timedelta(days=1)).isoformat()}T15:30:00+08:00",),
        )
        self.store.conn.commit()

    def _sync_bars(self, *, force: bool = False) -> int | None:
        """跑一次同步，回报路由实际收到的 recent_bars。"""
        with mock.patch(
            "src.market.infrastructure.adapters.fetch_daily_routed",
            return_value=(_bars(["2026-01-06"]), "tencent"),
        ) as routed:
            sync_quotes(
                lambda: MarketStore(self.db),
                ["600519"],
                workers=1,
                min_interval=0.0,
                with_factors=False,
                with_today_spot=False,
                force=force,
            )
        routed.assert_called_once()
        return routed.call_args.kwargs["recent_bars"]

    def test_current_history_only_pulls_a_recent_window(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self._seed(earliest="2020-01-02", last=yesterday)

        self.assertEqual(self._sync_bars(), 20)

    def test_gap_widens_the_window(self) -> None:
        last = (date.today() - timedelta(days=40)).isoformat()
        self._seed(earliest="2020-01-02", last=last)

        self.assertEqual(self._sync_bars(), 45)

    def test_no_watermark_pulls_full_history(self) -> None:
        self.assertIsNone(self._sync_bars())

    def test_fresh_listing_pulls_full_history(self) -> None:
        """库里只有几天数据时用近窗，会把上市以来的历史永久钉死在几十根。"""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self._seed(earliest=(date.today() - timedelta(days=3)).isoformat(), last=yesterday)

        self.assertIsNone(self._sync_bars())

    def test_long_outage_pulls_full_history(self) -> None:
        stale = (date.today() - timedelta(days=400)).isoformat()
        self._seed(earliest="2020-01-02", last=stale)

        self.assertIsNone(self._sync_bars())

    def test_force_pulls_full_history(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self._seed(earliest="2020-01-02", last=yesterday)

        self.assertIsNone(self._sync_bars(force=True))

    def test_receipt_request_start_matches_the_window(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self._seed(earliest="2020-01-02", last=yesterday)
        self._sync_bars()

        row = self.store.conn.execute(
            "SELECT request_start FROM source_route_receipts"
            " WHERE code = '600519' AND state = 'selected'"
            " ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(str(row[0]), window_start_date(20).isoformat())


if __name__ == "__main__":
    unittest.main()
