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
            "30 15 * * 1-5",
        )
        self.assertEqual(compose_trading_cron("once"), "30 15 * * 1-5")

    def test_interval(self) -> None:
        self.assertEqual(
            compose_trading_cron(
                "interval",
                interval_minutes=10,
                window_start_hour=9,
                window_end_hour=14,
            ),
            "*/10 9-14 * * 1-5",
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
        """预览只显示完整时分窗口内、且能被 cron 真正触发的槽位。"""
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
                "2026-07-30 10:10",
            ],
        )


if __name__ == "__main__":
    unittest.main()
