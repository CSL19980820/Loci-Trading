"""选股交易日窗口解析。"""
from __future__ import annotations

import unittest

from src.strategy.application.screen_dates import (
    ScreenDateError,
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


if __name__ == "__main__":
    unittest.main()
