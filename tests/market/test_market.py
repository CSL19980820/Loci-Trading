from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.market.infrastructure.store import MarketStore, MarketError, normalize_code, to_sina_symbol


def _quotes(dates: list[str], base: float = 10.0) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": np.linspace(base, base + n * 0.1, n),
            "high": np.linspace(base + 0.5, base + 0.5 + n * 0.1, n),
            "low": np.linspace(base - 0.5, base - 0.5 + n * 0.1, n),
            "close": np.linspace(base + 0.2, base + 0.2 + n * 0.1, n),
            "volume": np.full(n, 1_000_000.0),
            "amount": np.full(n, 10_000_000.0),
            "outstanding_share": np.full(n, 1e9),
            "turnover": np.full(n, 0.001),
        }
    )


class CodeNormalisationTests(unittest.TestCase):
    def test_accepts_common_shapes(self) -> None:
        for value in ("600519", "sh600519", "SH600519", "600519.SH", " 600519 "):
            self.assertEqual(normalize_code(value), "600519")

    def test_rejects_garbage(self) -> None:
        for value in ("60051", "abcdef", "", "6005190"):
            with self.subTest(value=value), self.assertRaises(MarketError):
                normalize_code(value)

    def test_exchange_prefix(self) -> None:
        self.assertEqual(to_sina_symbol("600519"), "sh600519")  # 沪主板
        self.assertEqual(to_sina_symbol("688981"), "sh688981")  # 科创板
        self.assertEqual(to_sina_symbol("000001"), "sz000001")  # 深主板
        self.assertEqual(to_sina_symbol("300750"), "sz300750")  # 创业板
        self.assertEqual(to_sina_symbol("830799"), "bj830799")  # 北交所

    def test_index_codes_are_not_guessed_from_prefix(self) -> None:
        """000001 既是上证指数也是平安银行，只能靠 instrument_type 区分。"""
        self.assertEqual(to_sina_symbol("000001", instrument_type="STOCK"), "sz000001")
        self.assertEqual(to_sina_symbol("000001", instrument_type="INDEX"), "sh000001")
        self.assertEqual(to_sina_symbol("000300", instrument_type="INDEX"), "sh000300")
        self.assertEqual(to_sina_symbol("399006", instrument_type="INDEX"), "sz399006")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.store = MarketStore(self.db)
        self.dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_page_instruments_and_latest_bars(self) -> None:
        self.store.upsert_instruments(
            [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "market": "SH",
                    "board": "main",
                    "instrument_type": "STOCK",
                    "status": "normal",
                },
                {
                    "code": "000001",
                    "name": "平安银行",
                    "market": "SZ",
                    "board": "main",
                    "instrument_type": "STOCK",
                    "status": "normal",
                },
            ]
        )
        self.store.upsert_quotes("600519", _quotes(self.dates))
        total, rows = self.store.page_instruments(q="茅台", limit=10)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["code"], "600519")
        page_total, page_rows = self.store.page_instruments(offset=0, limit=1)
        self.assertEqual(page_total, 2)
        self.assertEqual(len(page_rows), 1)
        latest = self.store.latest_bars(["600519", "000001"])
        self.assertEqual(latest["600519"]["trade_date"], "2026-01-08")
        self.assertIsNotNone(latest["600519"]["pct"])
        self.assertNotIn("000001", latest)

    def test_upsert_overwrites_corrected_data(self) -> None:
        """数据源事后修正过的行必须被覆盖，而不是留着旧值。"""
        self.store.upsert_quotes("600519", _quotes(self.dates), source="a")
        fixed = _quotes(self.dates)
        fixed.loc[0, "close"] = 999.0
        self.store.upsert_quotes("600519", fixed, source="b")
        history = self.store.history("600519", adjust="none")
        self.assertAlmostEqual(float(history.iloc[0]["close"]), 999.0)

    def test_calendar_is_maintained_on_write(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.upsert_quotes("000001", _quotes(self.dates[:2]))
        self.assertEqual(self.store.trading_days(), self.dates)

    def test_shift_trading_days_skips_non_trading_gaps(self) -> None:
        """按自然日加减会跨过周末与长假，必须走交易日历。"""
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.assertEqual(self.store.shift_trading_days("2026-01-05", 2), "2026-01-07")
        self.assertEqual(self.store.shift_trading_days("2026-01-08", -3), "2026-01-05")
        self.assertIsNone(self.store.shift_trading_days("2026-01-08", 5))
        self.assertIsNone(self.store.shift_trading_days("1999-01-01", 1))

    def test_rebuild_calendar_recovers_from_drift(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.conn.execute("DELETE FROM trading_calendar")
        self.store.conn.commit()
        self.assertEqual(self.store.rebuild_calendar(), len(self.dates))

    def test_trading_days_self_heals_for_legacy_databases(self) -> None:
        """老库没有日历表时应自动补，而不是返回空列表把上层坑了。"""
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.conn.execute("DELETE FROM trading_calendar")
        self.store.conn.commit()
        self.assertEqual(self.store.trading_days(), self.dates)

    def test_watermark_tracks_failures(self) -> None:
        self.store.set_watermark("600519", last_trade_date="2026-01-08", status="ok")
        self.store.set_watermark("000001", status="failed", message="接口超时")
        self.assertEqual(self.store.watermark("600519")["status"], "ok")
        self.assertEqual(self.store.watermark("000001")["status"], "failed")
        self.assertEqual(self.store.coverage()["failed_codes"], 1)

    def test_failed_retry_keeps_previous_last_trade_date(self) -> None:
        """失败重试不该把已经同步到的进度抹掉。"""
        self.store.set_watermark("600519", last_trade_date="2026-01-08", status="ok")
        self.store.set_watermark("600519", status="failed", message="限流")
        self.assertEqual(self.store.watermark("600519")["last_trade_date"], "2026-01-08")


class AdjustmentTests(unittest.TestCase):
    """复权是最容易出静默错误的地方，逐条钉死。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")
        self.dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
        self.store.upsert_quotes("600519", _quotes(self.dates))
        # 1 月 7 日除权，因子从 1.0 跳到 2.0
        self.store.upsert_adjust_factors(
            "600519",
            pd.DataFrame({"date": ["2026-01-05", "2026-01-07"], "hfq_factor": [1.0, 2.0]}),
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_qfq_keeps_the_latest_bar_at_the_real_traded_price(self) -> None:
        """前复权的定义就是最新一根等于真实成交价。"""
        raw = self.store.history("600519", adjust="none")
        qfq = self.store.history("600519", adjust="qfq")
        self.assertAlmostEqual(
            float(qfq.iloc[-1]["close"]), float(raw.iloc[-1]["close"]), places=6
        )

    def test_qfq_scales_pre_exdividend_bars_down(self) -> None:
        raw = self.store.history("600519", adjust="none")
        qfq = self.store.history("600519", adjust="qfq")
        # 除权前因子 1.0、之后 2.0，故除权前价格被折半。
        self.assertAlmostEqual(float(qfq.iloc[0]["close"]), float(raw.iloc[0]["close"]) / 2)

    def test_hfq_history_is_stable_when_new_dividends_arrive(self) -> None:
        """后复权的历史值不随新的除权改变——这正是选它做存储口径的原因。

        前复权会在每次除权后整体重算，若把复权价固化入库，
        新的除权就会让全部历史缓存静默出错。
        """
        before = self.store.history("600519", adjust="hfq")["close"].tolist()
        self.store.upsert_quotes("600519", _quotes(["2026-01-09"], base=20.0))
        self.store.upsert_adjust_factors(
            "600519", pd.DataFrame({"date": ["2026-01-09"], "hfq_factor": [4.0]})
        )
        after = self.store.history("600519", adjust="hfq")["close"].tolist()
        self.assertEqual(before, after[: len(before)])

    def test_missing_factors_fall_back_to_no_adjustment(self) -> None:
        self.store.upsert_quotes("000001", _quotes(self.dates))
        raw = self.store.history("000001", adjust="none")["close"].tolist()
        qfq = self.store.history("000001", adjust="qfq")["close"].tolist()
        self.assertEqual(raw, qfq)

    def test_unknown_adjust_mode_is_rejected(self) -> None:
        with self.assertRaises(MarketError):
            self.store.history("600519", adjust="mystery")


class PanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")
        self.dates = [f"2026-01-{day:02d}" for day in range(5, 25)]
        self.store.upsert_quotes("600519", _quotes(self.dates, base=100.0))
        self.store.upsert_quotes("000001", _quotes(self.dates, base=10.0))
        self.store.upsert_quotes("300750", _quotes(self.dates[:6], base=50.0))  # 次新股

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_panel_shape_is_dates_by_codes(self) -> None:
        panels = self.store.load_panel(fields=("close", "volume"), adjust="none")
        close = panels["close"]
        self.assertEqual(list(close.index), self.dates)
        self.assertEqual(sorted(close.columns), ["000001", "300750", "600519"])
        self.assertEqual(close.shape, (len(self.dates), 3))

    def test_min_bars_drops_recently_listed_names(self) -> None:
        """K 线不够长的票留在池子里只会让指标全空，污染筛选结果。"""
        panels = self.store.load_panel(fields=("close",), adjust="none", min_bars=10)
        self.assertNotIn("300750", panels["close"].columns)
        self.assertIn("600519", panels["close"].columns)

    def test_panel_matches_single_stock_history(self) -> None:
        """面板与单票查询必须给出同一组数字，否则两条路径会分叉。"""
        panels = self.store.load_panel(fields=("close",), adjust="none")
        history = self.store.history("600519", adjust="none")
        np.testing.assert_allclose(
            panels["close"]["600519"].to_numpy(dtype=float),
            history["close"].to_numpy(dtype=float),
        )

    def test_panel_applies_adjustment_per_code(self) -> None:
        self.store.upsert_adjust_factors(
            "600519",
            pd.DataFrame({"date": [self.dates[0], self.dates[10]], "hfq_factor": [1.0, 2.0]}),
        )
        panels = self.store.load_panel(fields=("close",), adjust="qfq")
        raw = self.store.load_panel(fields=("close",), adjust="none")
        # 有因子的票被折算，没有因子的票原样。
        self.assertAlmostEqual(
            panels["close"]["600519"].iloc[0], raw["close"]["600519"].iloc[0] / 2
        )
        self.assertAlmostEqual(
            panels["close"]["000001"].iloc[0], raw["close"]["000001"].iloc[0]
        )

    def test_rejects_unknown_field(self) -> None:
        with self.assertRaises(MarketError):
            self.store.load_panel(fields=("close", "not_a_field"))

    def test_empty_range_returns_empty_panels(self) -> None:
        panels = self.store.load_panel(fields=("close",), start="2030-01-01")
        self.assertTrue(panels["close"].empty)


if __name__ == "__main__":
    unittest.main()


class IncrementalSyncTests(unittest.TestCase):
    """增量同步的跳过判据。判错就是每天静默地什么都不做。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.store = MarketStore(self.db)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _sync(self, *, synced_on: str, stale_after_days: int | None = None) -> int:
        """把 watermark 的同步时间改成指定日期，再看会不会被跳过。"""
        from src.market.infrastructure.sync import sync_quotes

        self.store.set_watermark("600519", last_trade_date="2026-03-01", status="ok")
        self.store.conn.execute(
            "UPDATE ingest_watermark SET last_synced_at = ? WHERE code = '600519'",
            (f"{synced_on}T10:00:00+08:00",),
        )
        self.store.conn.commit()

        calls: list[str] = []

        class Recorder:
            name = "recorder"

            def fetch_daily(self, code, *, instrument_type="STOCK"):
                calls.append(code)
                return _quotes(["2026-03-02"])

            def fetch_adjust_factors(self, code):
                return pd.DataFrame(columns=["date", "hfq_factor"])

        kwargs = {} if stale_after_days is None else {"stale_after_days": stale_after_days}
        sync_quotes(
            lambda: MarketStore(self.db), ["600519"],
            sources=[Recorder()], workers=1, min_interval=0.0,
            with_factors=False, with_today_spot=False, **kwargs,
        )
        return len(calls)

    def test_skips_only_what_was_synced_today(self) -> None:
        from datetime import date, timedelta

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        self.assertEqual(self._sync(synced_on=today), 0, "今天同步过的应跳过")
        self.assertEqual(
            self._sync(synced_on=yesterday), 1,
            "昨天同步过的今天必须重新取——默认跳过它会让每日同步静默失效",
        )

    def test_force_ignores_the_watermark(self) -> None:
        from datetime import date
        from src.market.infrastructure.sync import sync_quotes

        self.store.set_watermark("600519", status="ok")

        calls: list[str] = []

        class Recorder:
            name = "recorder"

            def fetch_daily(self, code, *, instrument_type="STOCK"):
                calls.append(code)
                return _quotes(["2026-03-02"])

            def fetch_adjust_factors(self, code):
                return pd.DataFrame(columns=["date", "hfq_factor"])

        sync_quotes(
            lambda: MarketStore(self.db), ["600519"], sources=[Recorder()],
            workers=1, min_interval=0.0, force=True, with_factors=False,
            with_today_spot=False,
        )
        self.assertEqual(len(calls), 1)


class TodaySpotTests(unittest.TestCase):
    """历史日 K 不含当日时，用实时行情补齐。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "market.db"
        self.store = MarketStore(self.db)
        self.store.upsert_quotes(
            "600519",
            _quotes(["2026-07-22", "2026-07-23", "2026-07-24"]),
            source="hist",
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_apply_today_spot_appends_realtime_bar(self) -> None:
        from datetime import date
        from unittest.mock import patch

        from src.market.infrastructure.sync import apply_today_spot

        today = date.today()
        fake = pd.DataFrame(
            [
                {
                    "code": "600519",
                    "date": today,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1_000_000.0,
                    "amount": 10_000_000.0,
                }
            ]
        )
        with patch(
            "src.market.infrastructure.adapters.fetch_spot_routed",
            return_value=(fake, "sina"),
        ):
            written = apply_today_spot(self.store, ["600519"])

        self.assertEqual(written, 1)
        self.assertEqual(self.store.coverage()["last_date"], today.isoformat())
        history = self.store.history("600519", adjust="none")
        last = history.iloc[-1]
        self.assertEqual(str(last["trade_date"]), today.isoformat())
        self.assertAlmostEqual(float(last["close"]), 10.5)
        # 换手率沿用上一交易日流通股本。
        self.assertAlmostEqual(float(last["turnover"]), 1_000_000.0 / 1e9)
        mark = self.store.watermark("600519")
        self.assertEqual(mark["last_trade_date"], today.isoformat())
        self.assertEqual(mark["source"], "sina_spot")
