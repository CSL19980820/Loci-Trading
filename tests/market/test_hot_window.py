"""读写双库：热库窗口镜像 + review 注入热库 store。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from src.market import (
    HOT_WINDOW_TRADING_DAYS,
    MarketStore,
    hot_unusable_reason,
    hot_window_shallow,
    mirror_recent_to_hot,
    mirror_to_hot,
    open_market_hot,
)
from src.review.application.alerts import latest_closes
from src.review.application.capacity import check_capacity

_QUOTES_COLUMNS = (
    "trade_date, code, open, high, low, close, volume, amount, "
    "outstanding_share, turnover, source, receipt_id, fetched_at"
)
_QUOTE_PLACEHOLDERS = ",".join("?" * 13)


def _day_iso(day: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=day)).isoformat()


class HotWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.full = MarketStore(Path(self.temp.name) / "market.db")
        # conftest 已把 PALACE_MARKET_HOT_DB 指到隔离 tmp。
        self.hot = open_market_hot()

    def tearDown(self) -> None:
        self.full.close()
        self.hot.close()
        self.temp.cleanup()

    def _seed(self, days: int = 800) -> None:
        codes = ("000001", "600519")
        for code in codes:
            self.full.upsert_instruments(
                [
                    {
                        "code": code,
                        "name": f"票{code}",
                        "market": "SZ",
                        "instrument_type": "STOCK",
                    }
                ]
            )
        cal_rows = [(day, f"{day}T00:00:00") for day in (_day_iso(i) for i in range(days))]
        quote_rows = [
            (day, code, 10.0, 10.5, 9.8, 10.2, 1000, 10000, None, None, "test", None, f"{day}T00:00:00")
            for i in range(days)
            for day in [_day_iso(i)]
            for code in codes
        ]
        self.full.conn.executemany(
            "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
            cal_rows,
        )
        self.full.conn.executemany(
            f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
            quote_rows,
        )
        self.full.conn.commit()

    def _append_full_days(self, start_i: int, end_i: int) -> None:
        """向全量库追加 [start_i, end_i) 交易日（含日历与 000001 日 K）。"""
        for i in range(start_i, end_i):
            day = _day_iso(i)
            self.full.conn.execute(
                "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
                (day, f"{day}T00:00:00"),
            )
            self.full.conn.execute(
                f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
                (day, "000001", 10.0, 10.5, 9.8, 10.2, 1000, 10000, None, None, "test", None, f"{day}T00:00:00"),
            )
        self.full.conn.commit()

    def _hot_calendar_days(self) -> list[str]:
        return [
            str(row[0])
            for row in self.hot.conn.execute(
                "SELECT trade_date FROM trading_calendar ORDER BY trade_date"
            ).fetchall()
        ]

    def test_mirror_to_hot_keeps_recent_window_only(self) -> None:
        """800 交易日全量 → 热库只保留近 700 交易日窗口，instruments 全量。"""
        self._seed(800)
        payload = mirror_to_hot(self.full, self.hot)
        self.assertEqual(payload["mode"], "rebuild")
        hot_days = self._hot_calendar_days()
        self.assertEqual(len(hot_days), HOT_WINDOW_TRADING_DAYS)
        self.assertEqual(hot_days[0], _day_iso(800 - HOT_WINDOW_TRADING_DAYS))
        self.assertEqual(hot_days[-1], _day_iso(799))
        hot_quotes = int(
            self.hot.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
        )
        self.assertEqual(hot_quotes, HOT_WINDOW_TRADING_DAYS * 2)
        self.assertLess(hot_quotes, 800 * 2)
        hot_codes = {
            str(row["code"])
            for row in self.hot.conn.execute("SELECT code FROM instruments").fetchall()
        }
        self.assertEqual(hot_codes, {"000001", "600519"})

    def test_mirror_recent_to_hot_picks_up_new_trade_days(self) -> None:
        """全量库补新交易日 → 增量镜像后热库末日同步推进。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        self._append_full_days(800, 803)
        payload = mirror_recent_to_hot(self.full, self.hot)
        self.assertEqual(payload["mode"], "incremental")
        hot_max = self.hot.conn.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0]
        self.assertEqual(str(hot_max), _day_iso(802))

    def test_calendar_advance_trims_outside_window(self) -> None:
        """日历推进后 rebuild / incremental 都必须裁掉窗外旧行。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        old_start = _day_iso(800 - HOT_WINDOW_TRADING_DAYS)
        self.assertEqual(self._hot_calendar_days()[0], old_start)

        # 全量再推进 10 个交易日 → 窗口起点应前移 10 天。
        self._append_full_days(800, 810)
        expected_start = _day_iso(810 - HOT_WINDOW_TRADING_DAYS)
        self.assertNotEqual(expected_start, old_start)

        payload_inc = mirror_recent_to_hot(self.full, self.hot)
        self.assertEqual(payload_inc["mode"], "incremental")
        hot_days = self._hot_calendar_days()
        self.assertEqual(len(hot_days), HOT_WINDOW_TRADING_DAYS)
        self.assertEqual(hot_days[0], expected_start)
        self.assertEqual(hot_days[-1], _day_iso(809))
        before = int(
            self.hot.conn.execute(
                "SELECT COUNT(*) FROM quotes_daily WHERE trade_date < ?",
                (expected_start,),
            ).fetchone()[0]
        )
        self.assertEqual(before, 0)

        # rebuild 同样裁窗外。
        payload_rb = mirror_to_hot(self.full, self.hot)
        self.assertEqual(payload_rb["mode"], "rebuild")
        hot_days = self._hot_calendar_days()
        self.assertEqual(len(hot_days), HOT_WINDOW_TRADING_DAYS)
        self.assertEqual(hot_days[0], expected_start)
        before = int(
            self.hot.conn.execute(
                "SELECT COUNT(*) FROM quotes_daily WHERE trade_date < ?",
                (expected_start,),
            ).fetchone()[0]
        )
        self.assertEqual(before, 0)

    def test_shallow_hot_escalates_recent_mirror_to_rebuild(self) -> None:
        """热库只有近端几天时，mirror_recent 必须升级为全窗 rebuild。"""
        self._seed(800)
        # 只灌近 20 日，模拟「从未全量重建、只靠增量」的浅热库。
        self.hot.conn.executemany(
            "INSERT INTO trading_calendar(trade_date, updated_at) VALUES(?, ?)",
            [(day, f"{day}T00:00:00") for day in (_day_iso(i) for i in range(780, 800))],
        )
        self.hot.conn.executemany(
            f"INSERT INTO quotes_daily({_QUOTES_COLUMNS}) VALUES({_QUOTE_PLACEHOLDERS})",
            [
                (day, code, 10.0, 10.5, 9.8, 10.2, 1000, 10000, None, None, "test", None, f"{day}T00:00:00")
                for day in (_day_iso(i) for i in range(780, 800))
                for code in ("000001", "600519")
            ],
        )
        self.hot.conn.commit()
        self.assertEqual(len(self._hot_calendar_days()), 20)
        self.assertTrue(str(self._hot_calendar_days()[0]) > _day_iso(800 - HOT_WINDOW_TRADING_DAYS))
        payload = mirror_recent_to_hot(self.full, self.hot)
        self.assertEqual(payload["mode"], "rebuild")
        self.assertEqual(len(self._hot_calendar_days()), HOT_WINDOW_TRADING_DAYS)
        self.assertEqual(self._hot_calendar_days()[0], _day_iso(800 - HOT_WINDOW_TRADING_DAYS))

    def _hot_instrument_names(self) -> dict[str, str]:
        return {
            str(row["code"]): str(row["name"])
            for row in self.hot.conn.execute("SELECT code, name FROM instruments").fetchall()
        }

    def test_unchanged_small_tables_are_not_rewritten_every_mirror(self) -> None:
        """选股热路径每次都会调增量镜像；小表没变就不该整表重灌。

        用「手动改脏热库副本」证明跳过确实发生：revision 未变时那处改动会被保留。
        """
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        self.hot.conn.execute("UPDATE instruments SET name = '哨兵' WHERE code = '000001'")
        self.hot.conn.commit()

        self._append_full_days(800, 801)
        mirror_recent_to_hot(self.full, self.hot)

        self.assertEqual(self._hot_instrument_names()["000001"], "哨兵")

    def test_changed_instruments_invalidate_the_mirror(self) -> None:
        """全量库改了标的名 → revision 变 → 下次增量镜像必须重灌，不能吃陈旧值。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        self.hot.conn.execute("UPDATE instruments SET name = '哨兵' WHERE code = '000001'")
        self.hot.conn.commit()

        self.full.upsert_instruments(
            [{"code": "000001", "name": "改名后", "market": "SZ", "instrument_type": "STOCK"}]
        )
        mirror_recent_to_hot(self.full, self.hot)

        self.assertEqual(self._hot_instrument_names()["000001"], "改名后")

    def test_full_rebuild_always_recopies_small_tables(self) -> None:
        """全量重建是「热库损坏时重跑即可」的修复路径，不能被脏检查跳过。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        self.hot.conn.execute("DELETE FROM instruments")
        self.hot.conn.commit()

        mirror_to_hot(self.full, self.hot)

        self.assertEqual(set(self._hot_instrument_names()), {"000001", "600519"})

    def test_fresh_mirror_is_usable_for_screening(self) -> None:
        """刚镜像完的热库：窗口够深且末日对齐 → 允许选股读热库。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        self.assertEqual(hot_unusable_reason(self.full, self.hot), "")

    def test_deep_but_stale_hot_is_rejected(self) -> None:
        """窗口够深却落后一个交易日 → 必须拒绝，否则会静默用陈旧面板选股。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        # 全量库推进一天但不镜像，模拟当日 spot 已落全量、热库尚未跟上。
        self._append_full_days(800, 801)

        # 窗口深度检查看不出这种落后——这正是本用例要锁住的盲区。
        self.assertFalse(hot_window_shallow(self.full, self.hot))
        reason = hot_unusable_reason(self.full, self.hot)
        self.assertIn("落后", reason)
        self.assertIn(_day_iso(800), reason)

    def test_shallow_hot_is_rejected(self) -> None:
        """空热库（从未镜像）→ 以窗口偏浅为由拒绝。"""
        self._seed(800)
        self.assertEqual(hot_unusable_reason(self.full, self.hot), "热库窗口偏浅")

    def test_review_reads_injected_hot_store(self) -> None:
        """alerts / capacity 吃注入的 market store；此处注入热库，结果正确。"""
        self._seed(800)
        mirror_to_hot(self.full, self.hot)
        closes = latest_closes(self.hot, ["000001", "600519"])
        self.assertEqual(closes, {"000001": 10.2, "600519": 10.2})
        limited = check_capacity(
            [{"code": "000001", "name": "票000001"}],
            self.hot,
            position_size_yuan=100_000,
        )
        self.assertEqual(limited[0]["capacity"], "limited")
        ok = check_capacity(
            [{"code": "000001", "name": "票000001"}],
            self.hot,
            position_size_yuan=100,
        )
        self.assertEqual(ok[0]["capacity"], "ok")

    def test_degradation_when_hot_empty(self) -> None:
        """热库未镜像（空）→ latest_closes 空 dict、capacity 保持 ok。"""
        closes = latest_closes(self.hot, ["000001"])
        self.assertEqual(closes, {})
        annotated = check_capacity(
            [{"code": "000001", "name": "票000001"}],
            self.hot,
            position_size_yuan=100_000,
        )
        self.assertEqual(annotated[0]["capacity"], "ok")


if __name__ == "__main__":
    unittest.main()
