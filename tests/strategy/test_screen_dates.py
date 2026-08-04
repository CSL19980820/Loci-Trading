"""选股交易日窗口解析。"""
from __future__ import annotations

from datetime import date
import unittest

from src.strategy.application.screen_dates import (
    ScreenDateError,
    inclusive_day_span,
    preset_range,
    resolve_screen_window,
    window_label,
)


class ScreenDatesTests(unittest.TestCase):
    def test_resolve_single_and_range(self) -> None:
        self.assertEqual(resolve_screen_window(date="2026-07-28"), ("2026-07-28", "2026-07-28"))
        self.assertEqual(
            resolve_screen_window(start="2026-07-01", end="2026-07-15"),
            ("2026-07-01", "2026-07-15"),
        )
        self.assertEqual(resolve_screen_window(), (None, None))
        self.assertEqual(window_label("2026-07-01", "2026-07-15"), "2026-07-01→2026-07-15")

    def test_rejects_oversize_and_inverted(self) -> None:
        with self.assertRaises(ScreenDateError):
            resolve_screen_window(start="2026-06-01", end="2026-07-15")
        with self.assertRaises(ScreenDateError):
            resolve_screen_window(start="2026-07-20", end="2026-07-10")
        with self.assertRaises(ScreenDateError):
            resolve_screen_window(start="2026-07-01", end=None)
        self.assertEqual(inclusive_day_span("2026-07-01", "2026-07-31"), 31)

    def test_presets(self) -> None:
        today = date(2026, 7, 31)
        self.assertEqual(preset_range("today", today=today), ("2026-07-31", "2026-07-31"))
        self.assertEqual(preset_range("this_week", today=today), ("2026-07-27", "2026-07-31"))
        self.assertEqual(preset_range("last_week", today=today), ("2026-07-20", "2026-07-26"))
        self.assertEqual(preset_range("last_30", today=today), ("2026-07-01", "2026-07-31"))
        self.assertEqual(preset_range("prev_month", today=today), ("2026-06-01", "2026-06-30"))


if __name__ == "__main__":
    unittest.main()
