"""盘后定点任务启动补跑。"""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.ops.application.eod_catchup import (
    jobs_due_for_eod_catchup,
    last_run_covers_slot,
    parse_once_cron,
    slot_for_day,
)

_TZ = ZoneInfo("Asia/Shanghai")


class EodCatchupTests(unittest.TestCase):
    def test_parse_once_cron(self) -> None:
        self.assertEqual(parse_once_cron("30 15 * * 1-5"), (15, 30))
        self.assertIsNone(parse_once_cron("*/5 9-14 * * 1-5"))

    def test_due_when_never_ran_after_slot(self) -> None:
        jobs = [
            {
                "id": "j1",
                "name": "screen:qianlong-close-v3",
                "kind": "screen",
                "cron": "30 15 * * 1-5",
                "enabled": True,
                "last_run_at": "",
            }
        ]
        now = datetime(2026, 8, 1, 1, 0, tzinfo=_TZ)
        due = jobs_due_for_eod_catchup(
            jobs, last_trading_day="2026-07-31", now=now
        )
        self.assertEqual([j["name"] for j in due], ["screen:qianlong-close-v3"])

    def test_skip_when_already_ran_after_slot(self) -> None:
        slot = slot_for_day("2026-07-31", 15, 30)
        self.assertTrue(last_run_covers_slot("2026-07-31T15:31:00+08:00", slot))
        jobs = [
            {
                "id": "j1",
                "name": "screen:qianlong-close-v3",
                "kind": "screen",
                "cron": "30 15 * * 1-5",
                "enabled": True,
                "last_run_at": "2026-07-31T15:31:00+08:00",
            }
        ]
        now = datetime(2026, 8, 1, 1, 0, tzinfo=_TZ)
        due = jobs_due_for_eod_catchup(
            jobs, last_trading_day="2026-07-31", now=now
        )
        self.assertEqual(due, [])

    def test_skip_when_sqlite_utc_naive_covers_shanghai_slot(self) -> None:
        """ops.db datetime('now') 是 UTC；15:31 上海 = 07:31 UTC。"""
        slot = slot_for_day("2026-08-03", 15, 30)
        self.assertTrue(last_run_covers_slot("2026-08-03 07:31:14", slot))
        jobs = [
            {
                "id": "j1",
                "name": "screen:qianlong-close-v3",
                "kind": "screen",
                "cron": "30 15 * * 1-5",
                "enabled": True,
                "last_run_at": "2026-08-03 07:31:14",
            }
        ]
        now = datetime(2026, 8, 3, 16, 0, tzinfo=_TZ)
        due = jobs_due_for_eod_catchup(
            jobs, last_trading_day="2026-08-03", now=now
        )
        self.assertEqual(due, [])

    def test_local_naive_afternoon_also_covers_slot(self) -> None:
        """若库里写的是上海本地钟点 naive，也应视为已覆盖。"""
        slot = slot_for_day("2026-08-03", 15, 30)
        self.assertTrue(last_run_covers_slot("2026-08-03 15:41:00", slot))

    def test_skip_before_slot_on_trading_day(self) -> None:
        jobs = [
            {
                "id": "j1",
                "name": "screen:qianlong-close-v3",
                "kind": "screen",
                "cron": "30 15 * * 1-5",
                "enabled": True,
                "last_run_at": "",
            }
        ]
        now = datetime(2026, 7, 31, 14, 0, tzinfo=_TZ)
        due = jobs_due_for_eod_catchup(
            jobs, last_trading_day="2026-07-31", now=now
        )
        self.assertEqual(due, [])


if __name__ == "__main__":
    unittest.main()
