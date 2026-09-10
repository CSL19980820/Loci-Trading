"""quotes_daily 行数缓存（store_row_count）：写入路径增量维护，稳态不全表 COUNT。

生产库 1,664 万行，一次冷 COUNT 26～30 s；缓存若被每次写入作废，设置页 / 数据目录
接口就会在盘中每 5 分钟卡一次。这里钉住三件事：

1. 数字永远等于真 COUNT（追加、回填、重复写、新交易日、热库裁窗 / 重灌）；
2. 缓存建好之后，coverage 不再触发全表 COUNT；
3. 热库两条写路径（增量镜像、全量重建）之后数字仍然对。
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.market import MarketStore, mirror_recent_to_hot, mirror_to_hot, open_market_hot
from src.market.infrastructure.store_row_count import ROW_COUNT_KEY, read_base


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
        }
    )


def _true_count(store: MarketStore) -> int:
    return int(store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0])


class FullStoreRowCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")
        self.dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _assert_rows_match(self) -> None:
        self.assertEqual(self.store.coverage()["rows"], _true_count(self.store))

    def test_first_read_freezes_base_before_last_date(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.upsert_quotes("000001", _quotes(self.dates[-1:]))
        self.assertEqual(self.store.coverage()["rows"], 5)
        self.assertEqual(read_base(self.store.conn), (self.dates[-1], 3))

    def test_backfill_below_base_counts_only_new_rows(self) -> None:
        """回填历史（< 冻结线）：真正新增才计数，重复 upsert 不重复计。"""
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.assertEqual(self.store.coverage()["rows"], 4)

        self.store.upsert_quotes("000001", _quotes(self.dates[:2], base=8.0))
        self._assert_rows_match()
        self.assertEqual(self.store.coverage()["rows"], 6)

        self.store.upsert_quotes("000001", _quotes(self.dates[:2], base=9.0))
        self.assertEqual(self.store.coverage()["rows"], 6)
        self._assert_rows_match()

    def test_new_trading_day_advances_frozen_line(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.upsert_quotes("000001", _quotes(self.dates))
        self.assertEqual(self.store.coverage()["rows"], 8)
        self.assertEqual(read_base(self.store.conn), (self.dates[-1], 6))

        self.store.upsert_quotes("600519", _quotes(["2026-01-09"]))
        self.assertEqual(read_base(self.store.conn), ("2026-01-09", 8))
        self.assertEqual(self.store.coverage()["rows"], 9)

        self.store.upsert_quotes("000001", _quotes(["2026-01-09"]))
        self.assertEqual(self.store.coverage()["rows"], 10)
        self._assert_rows_match()

    def test_steady_state_reads_never_full_count(self) -> None:
        """缓存建好后，盘中追加 / 回填 / 新日都不该再触发全表 COUNT（那一下线上 26 s）。"""
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.coverage()

        seen: list[str] = []
        self.store.conn.set_trace_callback(lambda sql: seen.append(" ".join(str(sql).split())))
        try:
            self.store.upsert_quotes("000001", _quotes(self.dates[-1:]))
            self.assertEqual(self.store.coverage()["rows"], 5)
            self.store.upsert_quotes("000001", _quotes(self.dates[:1]))
            self.assertEqual(self.store.coverage()["rows"], 6)
            self.store.upsert_quotes("600519", _quotes(["2026-01-09"]))
            self.assertEqual(self.store.coverage()["rows"], 7)
        finally:
            self.store.conn.set_trace_callback(None)
        self.assertTrue(any("quotes_daily" in sql for sql in seen), seen[:5])
        self.assertNotIn("SELECT COUNT(*) FROM quotes_daily", seen)

    def test_legacy_v1_cache_is_dropped(self) -> None:
        self.store.upsert_quotes("600519", _quotes(self.dates))
        self.store.conn.execute(
            "INSERT INTO meta(key, value, updated_at) VALUES('quotes_daily_rows_v1', '2026-01-08|1|999', datetime('now'))"
        )
        self.store.conn.commit()
        self.assertEqual(self.store.coverage()["rows"], 4)
        row = self.store.conn.execute(
            "SELECT value FROM meta WHERE key = 'quotes_daily_rows_v1'"
        ).fetchone()
        self.assertIsNone(row)
        self.assertIsNotNone(read_base(self.store.conn))


_QUOTES_COLUMNS = (
    "trade_date, code, open, high, low, close, volume, amount, "
    "outstanding_share, turnover, source, receipt_id, fetched_at"
)
_QUOTE_PLACEHOLDERS = ",".join("?" * 13)


def _day_iso(day: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=day)).isoformat()


class HotStoreRowCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.full = MarketStore(Path(self.temp.name) / "market.db")
        # conftest 已把 PALACE_MARKET_HOT_DB 指到隔离 tmp。
        self.hot = open_market_hot()

    def tearDown(self) -> None:
        self.full.close()
        self.hot.close()
        self.temp.cleanup()

    def _seed_full(self, start: int, end: int, codes: tuple[str, ...] = ("000001", "600519")) -> None:
        for code in codes:
            self.full.upsert_instruments(
                [{"code": code, "name": f"票{code}", "market": "SZ", "instrument_type": "STOCK"}]
            )
        days = [_day_iso(i) for i in range(start, end)]
        self.full.conn.executemany(
            "INSERT OR IGNORE INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
            [(day, f"{day}T00:00:00") for day in days],
        )
        self.full.conn.executemany(
            f"INSERT OR IGNORE INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
            [
                (day, code, 10.0, 10.5, 9.8, 10.2, 1000, 10000, None, None, "test", None, f"{day}T00:00:00")
                for day in days
                for code in codes
            ],
        )
        self.full.conn.commit()

    def test_incremental_mirror_and_trim_keep_hot_count_exact(self) -> None:
        """热库缓存建好后：新交易日增量镜像 + 裁窗外旧行，数字仍等于真 COUNT。"""
        self._seed_full(0, 800)
        mirror_to_hot(self.full, self.hot)
        self.assertEqual(self.hot.coverage()["rows"], _true_count(self.hot))
        base_before = read_base(self.hot.conn)
        self.assertIsNotNone(base_before)

        self._seed_full(800, 803)
        mirror_recent_to_hot(self.full, self.hot)
        self.assertEqual(self.hot.coverage()["rows"], _true_count(self.hot))
        base_after = read_base(self.hot.conn)
        self.assertEqual(base_after[0], _day_iso(802))
        # 裁掉 3 天 × 2 票、补进 3 天 × 2 票：总数不变，基数线却推进了。
        self.assertEqual(self.hot.coverage()["rows"], 700 * 2)

    def test_full_rebuild_invalidates_then_recounts(self) -> None:
        self._seed_full(0, 800)
        mirror_to_hot(self.full, self.hot)
        self.assertEqual(self.hot.coverage()["rows"], 700 * 2)
        self._seed_full(800, 850, codes=("000001",))
        mirror_to_hot(self.full, self.hot)
        self.assertIsNone(read_base(self.hot.conn))
        self.assertEqual(self.hot.coverage()["rows"], _true_count(self.hot))
        self.assertIsNotNone(read_base(self.hot.conn))

    def test_row_count_key_lives_in_meta_only(self) -> None:
        self._seed_full(0, 5)
        self.full.coverage()
        row = self.full.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (ROW_COUNT_KEY,)
        ).fetchone()
        self.assertRegex(str(row[0]), r"^\d{4}-\d{2}-\d{2}\|\d+$")
