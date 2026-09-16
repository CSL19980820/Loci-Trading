"""两处无界读取的护栏。

1. `MarketStore.load_panel`：codes / start / end 全空 = 对千万行 `quotes_daily`
        的全表扫描 + 整表进 pandas。现在直接报错，不再让「默认值」等于「扫全库」。
2. `store_hot._copy_quotes_window`：rebuild 时窗口 ≈ 390 万行，原实现在热库写锁内
        `fetchall()` 再 `[tuple(row) for row in rows]` 复制第二份。现在读侧 `fetchmany`
        分批、写侧 `executemany` 分批，**仍在同一个写事务里**——原子性不能拆，见
        `test_copy_quotes_window_stays_atomic_when_a_batch_fails`。
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock
import math
import sqlite3
import tempfile
import tracemalloc
import unittest

import pandas as pd

from src.market.infrastructure import store_hot
from src.market.infrastructure.store import MarketError, MarketStore

_QUOTES_COLUMNS = (
    "trade_date, code, open, high, low, close, volume, amount, "
    "outstanding_share, turnover, source, receipt_id, fetched_at"
)
_QUOTE_PLACEHOLDERS = ",".join("?" * 13)


def _quotes(dates: list[str], base: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "open": [base] * len(dates),
            "high": [base * 1.05] * len(dates),
            "low": [base * 0.95] * len(dates),
            "close": [base] * len(dates),
            "volume": [10_000] * len(dates),
            "amount": [base * 10_000] * len(dates),
            "turnover": [0.01] * len(dates),
        }
    )


def _synthetic_days(count: int) -> list[str]:
    """构造 count 个字典序递增的合法日期串（12 × 28 = 336 天上限）。"""
    return [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(count)]


class LoadPanelBoundedRangeTests(unittest.TestCase):
    """`load_panel` 必须限定范围。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")
        self.dates = [f"2026-01-{day:02d}" for day in range(5, 25)]
        self.store.upsert_quotes("600519", _quotes(self.dates, base=100.0))
        self.store.upsert_quotes("000001", _quotes(self.dates, base=10.0))

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_unbounded_load_panel_is_rejected(self) -> None:
        """三个范围参数全空 = 全库扫，必须报错，而不是「跑得慢一点」。"""
        with self.assertRaises(MarketError) as ctx:
            self.store.load_panel(fields=("close",))
        message = str(ctx.exception)
        for token in ("codes", "start", "end", "quotes_daily"):
            self.assertIn(token, message)

    def test_rejection_happens_before_any_query(self) -> None:
        """护栏要在发 SQL 之前拦下——报完错还是扫了一遍库就白护了。"""
        traced: list[str] = []
        self.store.conn.set_trace_callback(traced.append)
        try:
            with self.assertRaises(MarketError):
                self.store.load_panel(fields=("close",))
        finally:
            self.store.conn.set_trace_callback(None)
        self.assertEqual([sql for sql in traced if "quotes_daily" in sql], [])

    def test_empty_containers_count_as_unbounded(self) -> None:
        """`codes=()` / `start=""` 生成的 where 与不传完全一样，同样拒绝。"""
        with self.assertRaises(MarketError):
            self.store.load_panel(fields=("close",), codes=(), start="", end="")

    def test_unknown_field_still_wins_over_range_guard(self) -> None:
        """字段校验在前：拼错字段名的人该看到字段错误，而不是范围错误。"""
        with self.assertRaises(MarketError) as ctx:
            self.store.load_panel(fields=("close", "not_a_field"))
        self.assertIn("不支持的面板字段", str(ctx.exception))

    def test_codes_only_is_enough(self) -> None:
        panels = self.store.load_panel(
            fields=("close",), codes=("600519",), adjust="none"
        )
        self.assertEqual(list(panels["close"].columns), ["600519"])
        self.assertEqual(len(panels["close"].index), len(self.dates))

    def test_start_only_is_enough(self) -> None:
        panels = self.store.load_panel(
            fields=("close",), start=self.dates[10], adjust="none"
        )
        self.assertEqual(list(panels["close"].index), self.dates[10:])

    def test_end_only_is_enough(self) -> None:
        panels = self.store.load_panel(
            fields=("close",), end=self.dates[3], adjust="none"
        )
        self.assertEqual(list(panels["close"].index), self.dates[:4])

    def test_full_window_still_works(self) -> None:
        panels = self.store.load_panel(
            fields=("close", "volume"),
            codes=("600519", "000001"),
            start=self.dates[2],
            end=self.dates[6],
            adjust="none",
        )
        self.assertEqual(panels["close"].shape, (5, 2))
        self.assertEqual(panels["volume"].shape, (5, 2))

    def test_bounded_but_empty_range_is_not_an_error(self) -> None:
        """有范围、没数据 → 空面板；这与「无范围」是两回事。"""
        panels = self.store.load_panel(fields=("close",), start="2030-01-01")
        self.assertTrue(panels["close"].empty)


class _SpyCursor:
    """记录 fetchall / fetchmany 用量的游标包装。"""

    def __init__(self, cursor: sqlite3.Cursor, log: dict[str, list[int]]) -> None:
        self._cursor = cursor
        self._log = log

    def fetchall(self) -> list[sqlite3.Row]:
        rows = self._cursor.fetchall()
        self._log.setdefault("fetchall", []).append(len(rows))
        return rows

    def fetchmany(self, size: int = 1) -> list[sqlite3.Row]:
        rows = self._cursor.fetchmany(size)
        self._log.setdefault("fetchmany", []).append(len(rows))
        return rows

    def fetchone(self) -> sqlite3.Row | None:
        return self._cursor.fetchone()

    def __iter__(self):
        return iter(self._cursor)

    def close(self) -> None:
        self._cursor.close()


class _FailingCursor(_SpyCursor):
    """第 fail_at 批 fetchmany 之后抛错，用来验证事务整体回滚。"""

    def __init__(self, cursor, log, fail_at: int) -> None:
        super().__init__(cursor, log)
        self._fail_at = fail_at

    def fetchmany(self, size: int = 1) -> list[sqlite3.Row]:
        rows = super().fetchmany(size)
        if len(self._log.get("fetchmany", [])) >= self._fail_at:
            raise RuntimeError("模拟搬运中途失败")
        return rows


class _ProxyConn:
    """转发到真实连接；只在日 K 窗口 SELECT 上换成 spy 游标。

    sqlite3.Connection 是 C 类型、不能挂属性，只能整条连接包一层。
    """

    def __init__(self, conn: sqlite3.Connection, factory, log) -> None:
        self._conn = conn
        self._factory = factory
        self._log = log

    def execute(self, sql, params=()):
        cursor = self._conn.execute(sql, params)
        if "FROM quotes_daily WHERE trade_date >= ?" in sql and "SELECT trade_date" in sql:
            return self._factory(cursor, self._log)
        return cursor

    def __getattr__(self, name):
        return getattr(self._conn, name)


class HotWindowCopyStreamingTests(unittest.TestCase):
    """`_copy_quotes_window`：分批搬运 + 单事务原子性。"""

    DAYS = 40
    CODES = 25

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.full = MarketStore(Path(self.temp.name) / "market.db")
        self.hot = MarketStore(Path(self.temp.name) / "market_hot.db")
        self.days = _synthetic_days(self.DAYS)
        self.codes = [f"{600000 + i:06d}" for i in range(self.CODES)]
        self.full.conn.executemany(
            "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
            [(day, f"{day}T00:00:00") for day in self.days],
        )
        self.full.conn.executemany(
            f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
            [
                (day, code, 10.0, 10.5, 9.8, 10.2, 1000, 10200.0, None, None, "tdx", None,
                    f"{day}T15:00:00")
                for day in self.days
                for code in self.codes
            ],
        )
        self.full.conn.commit()
        self.total = self.DAYS * self.CODES

    def tearDown(self) -> None:
        self.full.close()
        self.hot.close()
        self.temp.cleanup()

    def _spy(self, factory) -> dict[str, list[int]]:
        """把 full 的连接换成代理，返回 fetch 用量记录。"""
        log: dict[str, list[int]] = {}
        real_conn = self.full.conn
        self.full.conn = _ProxyConn(real_conn, factory, log)
        self.addCleanup(setattr, self.full, "conn", real_conn)
        return log

    def test_copy_uses_fetchmany_batches_not_fetchall(self) -> None:
        """读侧不许再 fetchall：那正是把整个窗口物化两份的那一步。"""
        log = self._spy(_SpyCursor)
        written = store_hot._copy_quotes_window(
            self.full, self.hot, self.days[0], force=True
        )

        self.assertEqual(written, self.total)
        self.assertNotIn("fetchall", log)
        batches = log["fetchmany"]
        self.assertGreaterEqual(len(batches), 2)  # 至少一批数据 + 一次收尾空批
        self.assertEqual(batches[-1], 0)
        self.assertEqual(sum(batches), self.total)

    def test_batch_size_caps_rows_held_at_once(self) -> None:
        """同一时刻活着的行数由批大小封顶，不再由窗口大小决定。"""
        batch = 128
        with mock.patch.object(store_hot, "_COPY_BATCH_ROWS", batch):
            log = self._spy(_SpyCursor)
            written = store_hot._copy_quotes_window(
                self.full, self.hot, self.days[0], force=True
            )

        self.assertEqual(written, self.total)
        self.assertLessEqual(max(log["fetchmany"]), batch)
        self.assertEqual(len(log["fetchmany"]), math.ceil(self.total / batch) + 1)

    def test_copy_writes_every_row_and_column(self) -> None:
        """分批不能丢行、不能错列：逐行逐列与全量库比对。"""
        store_hot._copy_quotes_window(self.full, self.hot, self.days[0], force=True)
        self.assertEqual(
            self.hot.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0],
            self.total,
        )
        self.assertEqual(
            self.hot.conn.execute("SELECT COUNT(*) FROM trading_calendar").fetchone()[0],
            self.DAYS,
        )
        order = f"SELECT {_QUOTES_COLUMNS} FROM quotes_daily ORDER BY trade_date, code"
        left = [tuple(row) for row in self.full.conn.execute(order)]
        right = [tuple(row) for row in self.hot.conn.execute(order)]
        self.assertEqual(left, right)

    def test_partial_window_copy_keeps_older_rows(self) -> None:
        """增量场景：只搬 [start, ∞)，窗口外的旧行不受影响。"""
        store_hot._copy_quotes_window(self.full, self.hot, self.days[0], force=True)
        cut = self.days[self.DAYS - 5]
        written = store_hot._copy_quotes_window(
            self.full, self.hot, cut, force=True
        )
        self.assertEqual(written, 5 * self.CODES)
        self.assertEqual(
            self.hot.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0],
            self.total,
        )

    def test_copy_quotes_window_stays_atomic_when_a_batch_fails(self) -> None:
        """**为什么不能一批一提交**：拆了就有「删完、灌一半」的中间态。

        热库是选股的在线只读库，可用性判据（hot_unusable_reason）只看窗口起点、
        天数与末日，看不出中间少了几百万行。这里模拟第 2 批搬运失败：DELETE 与
        已写入的批必须一起回滚，热库保持上一轮的完整窗口。
        """
        store_hot._copy_quotes_window(self.full, self.hot, self.days[0], force=True)
        before = self.hot.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
        self.assertEqual(before, self.total)

        def failing(cursor, log):
            return _FailingCursor(cursor, log, fail_at=2)

        with mock.patch.object(store_hot, "_COPY_BATCH_ROWS", 100):
            self._spy(failing)
            with self.assertRaises(RuntimeError):
                store_hot._copy_quotes_window(
                    self.full, self.hot, self.days[0], force=True
                )

        after = self.hot.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
        self.assertEqual(after, before, "写事务未回滚：热库出现了残缺窗口")

    def test_copy_runs_in_exactly_one_write_transaction(self) -> None:
        """搬运只开一次热库写事务（回执重灌是既有的第二个事务）。"""
        opened: list[str] = []
        real_transaction = self.hot._transaction

        def counting_transaction():
            opened.append("tx")
            return real_transaction()

        self.hot._transaction = counting_transaction  # type: ignore[method-assign]
        try:
            store_hot._copy_quotes_window(
                self.full, self.hot, self.days[0], force=True
            )
        finally:
            self.hot._transaction = real_transaction  # type: ignore[method-assign]
        self.assertEqual(len(opened), 2, "copy 一次 + 回执一次；多出来的是被拆开的事务")


class HotWindowCopyPeakMemoryTests(unittest.TestCase):
    """合成库上实测：峰值内存必须与窗口大小解耦。"""

    DAYS = 200
    CODES = 300

    @staticmethod
    def _legacy_copy(full: MarketStore, hot: MarketStore, start_date: str) -> int:
        """改前实现（留在测试里做对照）：锁内 fetchall + 整体再复制一份。"""
        with hot._transaction() as cursor:
            cursor.execute("DELETE FROM quotes_daily WHERE trade_date >= ?", (start_date,))
            cursor.execute(
                "DELETE FROM trading_calendar WHERE trade_date >= ?", (start_date,)
            )
            rows = full.conn.execute(store_hot._QUOTES_SELECT_SQL, (start_date,)).fetchall()
            if rows:
                cursor.executemany(
                    store_hot._QUOTES_UPSERT_SQL, [tuple(row) for row in rows]
                )
            cal_rows = full.conn.execute(
                "SELECT trade_date, updated_at FROM trading_calendar WHERE trade_date >= ?",
                (start_date,),
            ).fetchall()
            if cal_rows:
                cursor.executemany(
                    "INSERT OR REPLACE INTO trading_calendar VALUES(?,?)",
                    [tuple(row) for row in cal_rows],
                )
        store_hot._replace_linked_receipts(full, hot, start_date)
        return len(rows)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.full = MarketStore(Path(self.temp.name) / "market.db")
        self.days = _synthetic_days(self.DAYS)
        codes = [f"{600000 + i:06d}" for i in range(self.CODES)]
        self.full.conn.executemany(
            "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
            [(day, f"{day}T00:00:00") for day in self.days],
        )
        self.full.conn.executemany(
            f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
            [
                (day, code, 10.0, 10.5, 9.8, 10.2, 100000, 1020000.0, 1.0e9, 0.01,
                    "tdx", None, f"{day}T15:00:00")
                for day in self.days
                for code in codes
            ],
        )
        self.full.conn.commit()
        self.total = self.DAYS * self.CODES

    def tearDown(self) -> None:
        self.full.close()
        self.temp.cleanup()

    def _measure(self, name: str, fn) -> int:
        hot = MarketStore(Path(self.temp.name) / f"hot_{name}.db")
        tracemalloc.start()
        try:
            written = fn(self.full, hot, self.days[0])
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            hot.close()
        self.assertEqual(written, self.total)
        return peak

    def test_peak_memory_is_bounded_by_batch_not_by_window(self) -> None:
        """改前峰值 ∝ 窗口行数，改后 ∝ 批大小。差一个数量级以上才算改到位。"""
        legacy_peak = self._measure("legacy", self._legacy_copy)
        streamed_peak = self._measure("streamed", store_hot._copy_quotes_window)
        print(
            f"\n[{self.total} 行] 峰值内存 改前 {legacy_peak / 1e6:.2f} MB"
            f" → 改后 {streamed_peak / 1e6:.2f} MB"
            f"（{legacy_peak / max(streamed_peak, 1):.1f}×）"
        )
        self.assertLess(streamed_peak * 5, legacy_peak)
        # 批大小 5000 行 × 13 列的绝对上限是几 MB 量级，与窗口行数无关。
        self.assertLess(streamed_peak, 32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
