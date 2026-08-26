from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

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
                    "industry": "白酒",
                    "instrument_type": "STOCK",
                    "status": "normal",
                },
                {
                    "code": "000001",
                    "name": "平安银行",
                    "market": "SZ",
                    "board": "main",
                    "industry": "银行",
                    "instrument_type": "STOCK",
                    "status": "normal",
                },
            ]
        )
        self.store.upsert_quotes("600519", _quotes(self.dates))
        # 000001 的 turnover 列被数据源写成 0.05，与同一行的量额自相矛盾：
        # 0.05 换手意味着成交 8.6×1e9×0.05=4.3 亿，而这一行记的成交额只有
        # 1000 万（差 43 倍）。读侧口径以成交额为准，不采信这种脏列。
        self.store.upsert_quotes(
            "000001",
            _quotes(self.dates, base=8.0).assign(turnover=0.05),
        )
        total, rows = self.store.page_instruments(q="茅台", limit=10)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["code"], "600519")
        page_total, page_rows = self.store.page_instruments(offset=0, limit=1)
        self.assertEqual(page_total, 2)
        self.assertEqual(len(page_rows), 1)
        bank_total, bank_rows = self.store.page_instruments(industry="银行", limit=10)
        self.assertEqual(bank_total, 1)
        self.assertEqual(bank_rows[0]["code"], "000001")
        by_turn_total, by_turn = self.store.page_instruments_by_turnover(
            sort="turnover_desc", limit=10
        )
        self.assertEqual(by_turn_total, 2)
        self.assertEqual(by_turn[0]["code"], "000001")
        latest = self.store.latest_bars(["600519", "000001"])
        self.assertEqual(latest["600519"]["trade_date"], "2026-01-08")
        self.assertIsNotNone(latest["600519"]["pct"])
        self.assertIsNotNone(latest["600519"].get("turnover"))
        # 换手率口径 = 成交额/(收盘×流通股本)，与 page_instruments_by_turnover
        # 的排序表达式、spot 入库与 backfill 写入的值是同一个公式。
        self.assertAlmostEqual(
            float(latest["000001"]["turnover"]), 10_000_000.0 / (8.6 * 1e9)
        )

    def test_latest_bars_turnover_falls_back_to_the_stored_column(self) -> None:
        """没有流通股本时才用源给的 turnover——兜底不能一起丢掉。"""
        frame = _quotes(self.dates).assign(outstanding_share=None, turnover=0.05)
        self.store.upsert_quotes("600519", frame, source="eastmoney")

        latest = self.store.latest_bars(["600519"])

        self.assertAlmostEqual(float(latest["600519"]["turnover"]), 0.05)

    def test_upsert_overwrites_corrected_data(self) -> None:
        """数据源事后修正过的行必须被覆盖，而不是留着旧值。

        修正后的 OHLC 须自洽；非法行会被 ``partition_valid_ohlc_rows`` 丢弃，
        不能靠「只改 close」验证覆盖语义。
        """
        self.store.upsert_quotes("600519", _quotes(self.dates), source="a")
        fixed = _quotes(self.dates)
        fixed.loc[0, "open"] = 990.0
        fixed.loc[0, "high"] = 1005.0
        fixed.loc[0, "low"] = 980.0
        fixed.loc[0, "close"] = 999.0
        self.store.upsert_quotes("600519", fixed, source="b")
        history = self.store.history("600519", adjust="none")
        self.assertAlmostEqual(float(history.iloc[0]["close"]), 999.0)

    def test_upsert_preserves_shares_when_incoming_null(self) -> None:
        """spot / 无股本源带 NULL 时不得抹掉已有流通股本与换手率。"""
        self.store.upsert_quotes("600519", _quotes(self.dates[:1]), source="hist")
        wiped = pd.DataFrame(
            [
                {
                    "date": self.dates[0],
                    "open": 10.0,
                    "high": 13.0,
                    "low": 9.0,
                    "close": 12.5,
                    "volume": 2_000_000.0,
                    "amount": 20_000_000.0,
                    "outstanding_share": None,
                    "turnover": None,
                }
            ]
        )
        self.store.upsert_quotes("600519", wiped, source="sina_spot")
        row = self.store.history("600519", adjust="none").iloc[0]
        self.assertAlmostEqual(float(row["close"]), 12.5)
        self.assertAlmostEqual(float(row["outstanding_share"]), 1e9)
        self.assertAlmostEqual(float(row["turnover"]), 0.001)
        self.assertEqual(str(row["source"]), "sina_spot")

    def test_upsert_quote_bars_batch_keeps_per_code_rows(self) -> None:
        """多票同日一批写入不得按 trade_date 全局去重掉其它代码。"""
        day = "2026-08-04"
        written = self.store.upsert_quote_bars(
            [
                {
                    "code": "600519",
                    "date": day,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1e6,
                    "amount": 1e7,
                },
                {
                    "code": "000001",
                    "date": day,
                    "open": 8.0,
                    "high": 8.5,
                    "low": 7.5,
                    "close": 8.2,
                    "volume": 2e6,
                    "amount": 1.6e7,
                },
                {
                    "code": "600519",
                    "date": day,
                    "open": 10.0,
                    "high": 11.2,
                    "low": 9.0,
                    "close": 11.0,
                    "volume": 1.1e6,
                    "amount": 1.2e7,
                },
            ],
            source="sina_spot",
        )
        self.assertEqual(written, 2)
        self.assertAlmostEqual(
            float(self.store.history("600519", adjust="none").iloc[-1]["close"]),
            11.0,
        )
        self.assertAlmostEqual(
            float(self.store.history("000001", adjust="none").iloc[-1]["close"]),
            8.2,
        )
        self.store.set_watermarks(
            [("600519", day), ("000001", day)],
            status="ok",
            source="sina_spot",
        )
        self.assertEqual(self.store.watermark("000001")["last_trade_date"], day)

    def test_calendar_is_maintained_on_write(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.upsert_quotes("000001", _quotes(self.dates[:2]))
        self.assertEqual(self.store.trading_days(), self.dates)

    def test_coverage_refreshes_quote_row_count_after_same_day_append(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.assertEqual(self.store.coverage()["rows"], len(self.dates))

        self.store.upsert_quotes("000001", _quotes([self.dates[-1]], base=8.0))

        self.assertEqual(self.store.coverage()["rows"], len(self.dates) + 1)

    def test_coverage_rebuilds_legacy_quote_row_cache(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.conn.execute(
            "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("quotes_daily_rows_v1", f"{self.dates[-1]}|999"),
        )
        self.store.conn.commit()

        self.assertEqual(self.store.coverage()["rows"], len(self.dates))

    def test_data_snapshot_tracks_market_content_without_exposing_path(self) -> None:
        before = self.store.data_snapshot()
        self.assertEqual(before["rows"], 0)
        self.assertNotIn("db_path", before)
        self.assertEqual(before["quotes"]["rows"], 0)
        self.assertEqual(before["adjust_factors"]["rows"], 0)
        self.assertEqual(before["instruments"]["rows"], 0)
        self.store.upsert_quotes("600519", _quotes(self.dates), source="test")
        after = self.store.data_snapshot()
        self.assertEqual(after["rows"], len(self.dates))
        self.assertEqual(after["last_date"], self.dates[-1])
        self.assertEqual(after["quotes"]["rows"], len(self.dates))
        self.assertEqual(after["quotes"]["last_date"], self.dates[-1])
        self.assertNotEqual(before["market_revision"], after["market_revision"])

    def test_data_snapshot_revision_changes_when_only_adjust_factors_change(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates), source="test")
        self.store.upsert_adjust_factors(
            "600519",
            pd.DataFrame({"date": ["2026-01-05"], "hfq_factor": [1.0]}),
            source="factor-a",
        )
        before = self.store.data_snapshot()
        self.store.upsert_adjust_factors(
            "600519",
            pd.DataFrame({"date": ["2026-01-05"], "hfq_factor": [1.5]}),
            source="factor-b",
        )
        after = self.store.data_snapshot()
        self.assertEqual(before["quotes"], after["quotes"])
        self.assertEqual(before["instruments"], after["instruments"])
        self.assertNotEqual(
            before["adjust_factors"]["content_digest"],
            after["adjust_factors"]["content_digest"],
        )
        self.assertNotEqual(before["market_revision"], after["market_revision"])

    def test_data_snapshot_revision_changes_when_only_instrument_metadata_change(self) -> None:
        self.store.upsert_instruments(
            [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "market": "SH",
                    "board": "main",
                    "industry": "白酒",
                    "instrument_type": "STOCK",
                    "status": "normal",
                }
            ]
        )
        before = self.store.data_snapshot()
        self.store.upsert_instruments(
            [
                {
                    "code": "600519",
                    "name": "贵州茅台股份",
                    "market": "SH",
                    "board": "main",
                    "industry": "高端白酒",
                    "instrument_type": "STOCK",
                    "status": "normal",
                }
            ]
        )
        after = self.store.data_snapshot()
        self.assertEqual(before["quotes"], after["quotes"])
        self.assertEqual(before["adjust_factors"], after["adjust_factors"])
        self.assertNotEqual(
            before["instruments"]["content_digest"],
            after["instruments"]["content_digest"],
        )
        self.assertNotEqual(before["market_revision"], after["market_revision"])

    def test_data_snapshot_revision_changes_when_quote_is_overwritten_in_same_timestamp(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates), source="test")
        before = self.store.data_snapshot()
        fetched_at = self.store.conn.execute(
            "SELECT fetched_at FROM quotes_daily WHERE code = '600519' LIMIT 1"
        ).fetchone()[0]

        fixed = _quotes(self.dates)
        fixed.loc[0, "close"] = 999.0
        self.store.upsert_quotes("600519", fixed, source="repair")
        self.store.conn.execute(
            "UPDATE quotes_daily SET fetched_at = ? WHERE code = '600519'",
            (fetched_at,),
        )
        self.store.conn.commit()
        after = self.store.data_snapshot()

        self.assertEqual(before["fetched_at"], after["fetched_at"])
        self.assertNotEqual(before["market_revision"], after["market_revision"])

    def test_data_snapshot_does_not_scan_table_digests(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates), source="test")
        with mock.patch.object(
            self.store, "_revision_digest", wraps=self.store._revision_digest
        ) as revision_digest:
            snapshot = self.store.data_snapshot()
        self.assertTrue(snapshot["market_revision"])
        self.assertEqual(
            {call.args[0] for call in revision_digest.call_args_list},
            {"market_revision", "adjust_factors_revision", "instruments_revision"},
        )

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

    def test_trading_days_filtered_miss_does_not_rebuild(self) -> None:
        """热库常见：日历有今日、尚无下一交易日。带 start 的空结果不得全表重建。"""
        self.store.upsert_quotes("600519", _quotes(self.dates))
        before = self.store.conn.execute(
            "SELECT COUNT(*) FROM trading_calendar"
        ).fetchone()[0]
        self.assertEqual(self.store.trading_days(start="2099-01-01"), [])
        after = self.store.conn.execute(
            "SELECT COUNT(*) FROM trading_calendar"
        ).fetchone()[0]
        self.assertEqual(after, before)

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

    def test_write_transaction_takes_the_write_lock_up_front(self) -> None:
        """写事务必须 BEGIN IMMEDIATE，否则 busy_timeout 形同虚设。

        WAL 下 ``BEGIN``（DEFERRED）先读后写时，若别的连接在中间提交过，
        升级写锁会立刻拿到 SQLITE_BUSY——这类快照失效**不会**走 busy_timeout
        重试，四个同步 worker 会随机抛 "database is locked"。
        """
        import sqlite3

        other = MarketStore(self.db)
        other.conn.execute("PRAGMA busy_timeout=200")
        try:
            with self.store._transaction() as cursor:
                cursor.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()
                with self.assertRaises(sqlite3.OperationalError):
                    other.conn.execute(
                        "INSERT INTO meta(key, value, updated_at)"
                        " VALUES('probe', '1', datetime('now'))"
                    )
                    other.conn.commit()
                cursor.execute(
                    "INSERT INTO meta(key, value, updated_at)"
                    " VALUES('ours', '1', datetime('now'))"
                )
        finally:
            other.conn.rollback()
            other.close()
        row = self.store.conn.execute(
            "SELECT value FROM meta WHERE key = 'ours'"
        ).fetchone()
        self.assertEqual(str(row[0]), "1")


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
        panels = self.store.load_panel(
            fields=("close", "volume"), start=self.dates[0], adjust="none"
        )
        close = panels["close"]
        self.assertEqual(list(close.index), self.dates)
        self.assertEqual(sorted(close.columns), ["000001", "300750", "600519"])
        self.assertEqual(close.shape, (len(self.dates), 3))

    def test_min_bars_drops_recently_listed_names(self) -> None:
        """K 线不够长的票留在池子里只会让指标全空，污染筛选结果。"""
        panels = self.store.load_panel(
            fields=("close",), start=self.dates[0], adjust="none", min_bars=10
        )
        self.assertNotIn("300750", panels["close"].columns)
        self.assertIn("600519", panels["close"].columns)

    def test_panel_matches_single_stock_history(self) -> None:
        """面板与单票查询必须给出同一组数字，否则两条路径会分叉。"""
        panels = self.store.load_panel(fields=("close",), start=self.dates[0], adjust="none")
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
        panels = self.store.load_panel(fields=("close",), start=self.dates[0], adjust="qfq")
        raw = self.store.load_panel(fields=("close",), start=self.dates[0], adjust="none")
        # 有因子的票被折算，没有因子的票原样。
        self.assertAlmostEqual(
            panels["close"]["600519"].iloc[0], raw["close"]["600519"].iloc[0] / 2
        )
        self.assertAlmostEqual(
            panels["close"]["000001"].iloc[0], raw["close"]["000001"].iloc[0]
        )

    def test_panel_factor_query_is_scoped_to_the_requested_window(self) -> None:
        """窄窗单票回测不应把全市场全历史复权因子搬进 pandas。"""
        start, end = self.dates[10], self.dates[15]
        self.store.upsert_adjust_factors(
            "600519",
            pd.DataFrame(
                {
                    "date": [self.dates[0], self.dates[12], self.dates[-1]],
                    "hfq_factor": [1.0, 2.0, 4.0],
                }
            ),
        )
        self.store.upsert_adjust_factors(
            "000001",
            pd.DataFrame({"date": self.dates, "hfq_factor": [1.0] * len(self.dates)}),
        )
        traced: list[str] = []
        self.store.conn.set_trace_callback(traced.append)
        try:
            panels = self.store.load_panel(
                fields=("close",),
                codes=("600519",),
                start=start,
                end=end,
                adjust="qfq",
            )
        finally:
            self.store.conn.set_trace_callback(None)

        history = self.store.history("600519", start=start, end=end, adjust="qfq")
        np.testing.assert_allclose(
            panels["close"]["600519"].to_numpy(dtype=float),
            history["close"].to_numpy(dtype=float),
        )
        factor_sql = [sql for sql in traced if "adjust_factors" in sql]
        self.assertEqual(len(factor_sql), 1)
        self.assertIn("WITH requested(code)", factor_sql[0])
        self.assertIn("JOIN requested", factor_sql[0])

    def test_rejects_unknown_field(self) -> None:
        with self.assertRaises(MarketError):
            self.store.load_panel(fields=("close", "not_a_field"))

    def test_empty_range_returns_empty_panels(self) -> None:
        panels = self.store.load_panel(fields=("close",), start="2030-01-01")
        self.assertTrue(panels["close"].empty)


if __name__ == "__main__":
    unittest.main()


