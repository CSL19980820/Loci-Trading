"""分时昨收 / 复权缩放：源无前复权分时，用本地因子对齐日 K。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pandas as pd

from src.market.application.minute import (
    adjust_ratio_on_date,
    apply_minute_adjust,
    unadjusted_prev_close,
)


class UnadjustedPrevCloseTests(unittest.TestCase):
    def test_reads_latest_close_before_trade_date(self) -> None:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"close": 80.75}
        self.assertEqual(unadjusted_prev_close(conn, "301528", "2026-06-05"), 80.75)
        conn.execute.assert_called_once()
        sql, params = conn.execute.call_args.args
        self.assertIn("trade_date < ?", sql)
        self.assertEqual(params, ("301528", "2026-06-05"))

    def test_returns_none_when_missing_or_invalid(self) -> None:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        self.assertIsNone(unadjusted_prev_close(conn, "301528", "2026-06-05"))
        self.assertIsNone(unadjusted_prev_close(conn, "", "2026-06-05"))
        self.assertIsNone(unadjusted_prev_close(conn, "301528", ""))


class MinuteAdjustTests(unittest.TestCase):
    def test_none_keeps_raw_prices(self) -> None:
        store = MagicMock()
        frame = pd.DataFrame({"datetime": ["2026-06-05 09:31"], "close": [91.75]})
        out, prev = apply_minute_adjust(
            store, "301528", "2026-06-05", frame, adjust="none", prev_close=80.75
        )
        self.assertAlmostEqual(float(out["close"].iloc[0]), 91.75)
        self.assertEqual(prev, 80.75)
        store._factor_series.assert_not_called()

    def test_qfq_scales_prices_and_prev_close(self) -> None:
        store = MagicMock()
        store.conn.execute.return_value.fetchone.side_effect = [
            {"d": "2026-07-31"},  # latest anchor
            {"trade_date": "2026-06-04"},  # prev day
            {"d": "2026-07-31"},  # latest again for prev ratio
        ]
        store._factor_series.side_effect = [
            pd.Series([1.2, 1.5], index=["2026-06-05", "2026-07-31"]),
            pd.Series([1.2, 1.5], index=["2026-06-04", "2026-07-31"]),
        ]
        store._adjust_ratio.side_effect = [
            pd.Series([0.8, 1.0], index=["2026-06-05", "2026-07-31"]),
            pd.Series([0.8, 1.0], index=["2026-06-04", "2026-07-31"]),
        ]
        frame = pd.DataFrame(
            {
                "datetime": ["2026-06-05 09:31"],
                "close": [100.0],
                "avg_price": [99.0],
                "volume": [10.0],
            }
        )
        out, prev = apply_minute_adjust(
            store, "301528", "2026-06-05", frame, adjust="qfq", prev_close=80.0
        )
        self.assertAlmostEqual(float(out["close"].iloc[0]), 80.0)
        self.assertAlmostEqual(float(out["avg_price"].iloc[0]), 79.2)
        self.assertAlmostEqual(float(out["volume"].iloc[0]), 10.0)
        self.assertAlmostEqual(float(prev or 0), 64.0)

    def test_adjust_ratio_none_is_one(self) -> None:
        self.assertEqual(adjust_ratio_on_date(MagicMock(), "301528", "2026-06-05", "none"), 1.0)

    def test_adjust_ratio_when_trade_date_is_latest(self) -> None:
        store = MagicMock()
        store.conn.execute.return_value.fetchone.return_value = {"d": "2026-08-28"}
        store._factor_series.return_value = pd.Series([1.5], index=["2026-08-28"])
        store._adjust_ratio.return_value = pd.Series([1.0], index=["2026-08-28"])
        ratio = adjust_ratio_on_date(store, "301528", "2026-08-28", "qfq")
        self.assertAlmostEqual(ratio, 1.0)
        call_dates = store._factor_series.call_args[0][1]
        self.assertEqual(list(call_dates), ["2026-08-28"])

    def test_factor_series_handles_duplicate_dates(self) -> None:
        from src.market.infrastructure.store import MarketStore
        store = MarketStore(":memory:")
        try:
            store.conn.execute(
                "INSERT INTO adjust_factors(code, trade_date, hfq_factor, fetched_at) VALUES (?, ?, ?, ?)",
                ("000001", "2026-01-01", 1.0, "2026-01-01T00:00:00"),
            )
            store.conn.execute(
                "INSERT INTO adjust_factors(code, trade_date, hfq_factor, fetched_at) VALUES (?, ?, ?, ?)",
                ("000001", "2026-06-01", 1.2, "2026-06-01T00:00:00"),
            )
            # 传入含重复日期的序列（如 [2026-08-28, 2026-08-28]）
            dates = pd.Series(["2026-08-28", "2026-08-28"], dtype=str)
            factors = store._factor_series("000001", dates)
            self.assertEqual(len(factors), 2)
            self.assertAlmostEqual(float(factors.iloc[0]), 1.2)
            self.assertAlmostEqual(float(factors.iloc[1]), 1.2)
        finally:
            store.close()

if __name__ == "__main__":
    unittest.main()
