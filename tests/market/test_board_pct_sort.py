"""行情台按涨跌幅分页排序。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.market import MarketStore


class BoardPctSortTests(unittest.TestCase):
    def test_page_instruments_by_pct_orders_gain_and_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.db"
            with MarketStore(str(db)) as store:
                store.conn.executemany(
                    "INSERT INTO trading_calendar(trade_date, updated_at) VALUES (?, ?)",
                    [
                        ("2026-07-29", "2026-07-29T00:00:00"),
                        ("2026-07-30", "2026-07-30T00:00:00"),
                        ("2026-07-31", "2026-07-31T00:00:00"),
                    ],
                )
                for code, name in (
                    ("600001", "涨停样"),
                    ("600002", "平盘样"),
                    ("600003", "下跌样"),
                ):
                    store.conn.execute(
                        "INSERT INTO instruments(code, name, market, board, industry,"
                        " instrument_type, status, updated_at)"
                        " VALUES (?, ?, 'SH', 'main', '测试', 'STOCK', 'normal',"
                        " '2026-07-31T00:00:00')",
                        (code, name),
                    )
                bars = [
                    ("600001", "2026-07-30", 10.0),
                    ("600001", "2026-07-31", 11.0),  # +10%
                    ("600002", "2026-07-30", 20.0),
                    ("600002", "2026-07-31", 20.0),  # 0%
                    ("600003", "2026-07-30", 30.0),
                    ("600003", "2026-07-31", 27.0),  # -10%
                ]
                for code, day, close in bars:
                    store.conn.execute(
                        "INSERT INTO quotes_daily(trade_date, code, open, high, low,"
                        " close, volume, amount, turnover, fetched_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, 1000, 10000, 0.01,"
                        " '2026-07-31T00:00:00')",
                        (day, code, close, close, close, close),
                    )
                store.conn.commit()

                _total, gainers = store.page_instruments_by_pct(
                    sort="pct_desc", limit=10
                )
                self.assertEqual(
                    [row["code"] for row in gainers],
                    ["600001", "600002", "600003"],
                )
                _total, losers = store.page_instruments_by_pct(sort="pct_asc", limit=10)
                self.assertEqual(
                    [row["code"] for row in losers],
                    ["600003", "600002", "600001"],
                )


if __name__ == "__main__":
    unittest.main()
