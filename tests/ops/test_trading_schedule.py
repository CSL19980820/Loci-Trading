"""交易日调度合成与预览单测。"""
from __future__ import annotations

import unittest
from datetime import datetime

from src.ops.application.trading_schedule import (
    TradingScheduleError,
    compose_trading_cron,
    preview_trading_runs,
)


class ComposeCronTests(unittest.TestCase):
    def test_off_is_empty(self) -> None:
        self.assertEqual(compose_trading_cron("off"), "")

    def test_once(self) -> None:
        self.assertEqual(
            compose_trading_cron("once", run_hour=15, run_minute=30),
            "30 15 * * mon-fri",
        )
        self.assertEqual(compose_trading_cron("once"), "30 15 * * mon-fri")

    def test_interval(self) -> None:
        self.assertEqual(
            compose_trading_cron(
                "interval",
                interval_minutes=10,
                window_start_hour=9,
                window_end_hour=14,
            ),
            "*/10 9-14 * * mon-fri",
        )

    def test_bad_interval(self) -> None:
        with self.assertRaises(TradingScheduleError):
            compose_trading_cron("interval", interval_minutes=7)

    def test_interval_rejects_reversed_minute_window(self) -> None:
        with self.assertRaises(TradingScheduleError):
            compose_trading_cron(
                "interval",
                window_start_hour=14,
                window_start_minute=51,
                window_end_hour=14,
                window_end_minute=50,
            )


class PreviewRunsTests(unittest.TestCase):
    def test_once_full_datetime(self) -> None:
        now = datetime(2026, 7, 30, 10, 0)  # Thursday
        runs = preview_trading_runs(
            "once", now=now, run_hour=15, run_minute=30, limit=1
        )
        self.assertEqual(runs, ["2026-07-30 15:30"])

    def test_interval_five_slots_respect_minute_window(self) -> None:
        """预览显示开头若干槽 + 当天末档，避免误以为结束于 14:00。"""
        now = datetime(2026, 7, 30, 9, 0)
        runs = preview_trading_runs(
            "interval",
            now=now,
            interval_minutes=10,
            window_start_hour=9,
            window_start_minute=30,
            window_end_hour=14,
            window_end_minute=50,
            limit=5,
        )
        self.assertEqual(
            runs,
            [
                "2026-07-30 09:30",
                "2026-07-30 09:40",
                "2026-07-30 09:50",
                "2026-07-30 10:00",
                "2026-07-30 14:50",
            ],
        )

    def test_interval_preview_skips_between_split_sessions(self) -> None:
        runs = preview_trading_runs(
            "interval",
            now=datetime(2026, 7, 30, 11, 40),
            interval_minutes=10,
            window_start_hour=9,
            window_start_minute=20,
            window_end_hour=14,
            window_end_minute=50,
            sessions=[
                {"start_hour": 9, "start_minute": 20, "end_hour": 11, "end_minute": 30},
                {"start_hour": 13, "start_minute": 0, "end_hour": 14, "end_minute": 50},
            ],
            limit=5,
        )

        self.assertEqual(
            runs,
            [
                "2026-07-30 13:00",
                "2026-07-30 13:10",
                "2026-07-30 13:20",
                "2026-07-30 13:30",
                "2026-07-30 14:50",
            ],
        )


if __name__ == "__main__":
    unittest.main()
