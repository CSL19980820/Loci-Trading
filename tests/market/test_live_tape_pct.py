"""托盘/顶栏持仓应展示今日涨跌，而非成本浮盈。"""
from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from unittest.mock import patch


class LiveTapePctSemanticsTests(unittest.TestCase):
    def test_live_source_failure_is_visible_in_tape_error(self) -> None:
        from src.market.infrastructure.adapters import AdapterError
        from src.market.infrastructure.live_tape import build_live_tape

        with patch(
            "src.market.infrastructure.adapters.fetch_live_quotes_routed",
            side_effect=AdapterError("all live sources failed"),
        ):
            tape = build_live_tape(use_cache=False)

        self.assertIn("all live sources failed", tape["error"])
        self.assertEqual(tape["source"], "none")
        self.assertTrue(all(item["ok"] is False for item in tape["indices"]))

    def test_invalid_position_code_does_not_break_live_tape(self) -> None:
        from src.market.infrastructure.live_tape import build_live_tape

        quotes = [
            {
                "code": "000001",
                "name": "上证指数",
                "price": 3000.0,
                "pct": -0.9,
                "change": -27.0,
                "prev_close": 3027.0,
                "source": "test",
            },
            {
                "code": "300293",
                "name": "蓝英装备",
                "price": 15.53,
                "pct": 2.98,
                "change": 0.45,
                "prev_close": 15.08,
                "source": "test",
            },
        ]

        with patch(
            "src.market.infrastructure.live_tape.fetch_live_quotes",
            return_value=quotes,
        ) as fetch:
            tape = build_live_tape(
                position_codes=[
                    {"code": "not-a-code", "name": "坏数据", "shares": 100},
                    {"code": "300293", "name": "蓝英装备", "shares": 1000},
                ],
                use_cache=False,
            )

        requested_codes = fetch.call_args.args[0]
        self.assertNotIn("not-a-code", requested_codes)
        self.assertEqual([item["code"] for item in tape["positions"]], ["300293"])
        self.assertAlmostEqual(float(tape["positions"][0]["pct"]), 2.98)
        self.assertTrue(tape["indices"][0]["ok"])

    def test_live_tape_cache_is_scoped_to_position_specs(self) -> None:
        from src.market.infrastructure.live_tape import build_live_tape

        with patch(
            "src.market.infrastructure.live_tape.fetch_live_quotes",
            return_value=[],
        ) as fetch:
            first = build_live_tape(
                position_codes=[{"code": "300293", "name": "蓝英装备", "shares": 100}],
                use_cache=False,
            )
            second = build_live_tape(
                position_codes=[{"code": "600519", "name": "贵州茅台", "shares": 100}],
                use_cache=True,
            )

        self.assertEqual([item["code"] for item in first["positions"]], ["300293"])
        self.assertEqual([item["code"] for item in second["positions"]], ["600519"])
        self.assertEqual(fetch.call_count, 2)

    def test_same_live_tape_cache_key_uses_single_flight(self) -> None:
        from src.market.infrastructure.live_tape import build_live_tape

        started = threading.Event()
        release = threading.Event()
        calls = 0

        def fetch(_codes, *, instrument_types=None):
            nonlocal calls
            _ = instrument_types
            calls += 1
            started.set()
            release.wait(timeout=5)
            return []

        try:
            with patch(
                "src.market.infrastructure.live_tape.fetch_live_quotes",
                side_effect=fetch,
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(
                        build_live_tape, extra_codes=["123456"], use_cache=True
                    )
                    self.assertTrue(started.wait(timeout=1))
                    second = pool.submit(
                        build_live_tape, extra_codes=["123456"], use_cache=True
                    )
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline and calls < 2:
                        time.sleep(0.01)
                    release.set()
                    first.result(timeout=2)
                    second.result(timeout=2)
            self.assertEqual(calls, 1)
        finally:
            release.set()

    def test_equivalent_code_formats_share_single_flight(self) -> None:
        from src.market.infrastructure.live_tape import build_live_tape

        started = threading.Event()
        release = threading.Event()
        calls = 0

        def fetch(_codes, *, instrument_types=None):
            nonlocal calls
            _ = instrument_types
            calls += 1
            started.set()
            release.wait(timeout=5)
            return []

        try:
            with patch(
                "src.market.infrastructure.live_tape.fetch_live_quotes",
                side_effect=fetch,
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(
                        build_live_tape, extra_codes=["sh123456"], use_cache=True
                    )
                    self.assertTrue(started.wait(timeout=1))
                    second = pool.submit(
                        build_live_tape, extra_codes=["123456"], use_cache=True
                    )
                    time.sleep(0.05)
                    release.set()
                    first.result(timeout=2)
                    second.result(timeout=2)
            self.assertEqual(calls, 1)
        finally:
            release.set()

    def test_single_flight_wakes_waiters_after_unexpected_failure(self) -> None:
        from src.market.infrastructure.live_tape import build_live_tape

        started = threading.Event()
        release = threading.Event()
        calls = 0

        def fail_build(**_kwargs):
            nonlocal calls
            calls += 1
            started.set()
            release.wait(timeout=5)
            raise RuntimeError("组装失败")

        try:
            with patch(
                "src.market.infrastructure.live_tape._build_live_tape_uncached",
                side_effect=fail_build,
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(
                        build_live_tape, extra_codes=["123457"], use_cache=False
                    )
                    self.assertTrue(started.wait(timeout=1))
                    second = pool.submit(
                        build_live_tape, extra_codes=["123457"], use_cache=False
                    )
                    release.set()
                    with self.assertRaisesRegex(RuntimeError, "组装失败"):
                        first.result(timeout=2)
                    with self.assertRaisesRegex(RuntimeError, "组装失败"):
                        second.result(timeout=2)
            self.assertEqual(calls, 1)

            with patch(
                "src.market.infrastructure.live_tape._build_live_tape_uncached",
                return_value={"title": "retry"},
            ) as retry:
                result = build_live_tape(extra_codes=["123457"], use_cache=False)
            self.assertEqual(result["title"], "retry")
            retry.assert_called_once()
        finally:
            release.set()

    def test_build_live_tape_title_uses_day_pct_not_cost_pnl(self) -> None:
        from src.market.infrastructure.live_tape import build_live_tape

        quotes = [
            {
                "code": "000001",
                "name": "上证指数",
                "price": 3000.0,
                "pct": -0.9,
                "change": -27.0,
                "prev_close": 3027.0,
                "source": "test",
            },
            {
                "code": "300293",
                "name": "蓝英装备",
                "price": 15.53,
                "pct": 2.98,  # 今日涨（红）
                "change": 0.45,
                "prev_close": 15.08,
                "source": "test",
            },
        ]

        with patch(
            "src.market.infrastructure.live_tape.fetch_live_quotes",
            return_value=quotes,
        ):
            tape = build_live_tape(
                position_codes=[
                    {"code": "300293", "name": "蓝英装备", "shares": 1000, "cost": 15.56}
                ],
                use_cache=False,
            )

        pos = tape["positions"][0]
        self.assertAlmostEqual(float(pos["pct"]), 2.98)
        # 成本略高 → 浮亏约 -0.2%，绝不能冒充今日涨跌
        self.assertLess(float(pos["pnl_pct"]), 0)
        self.assertRegex(tape["title"], r"仓\+3\.0%")

    def test_format_tray_title_puts_bag_first_and_sorts_by_day_pct(self) -> None:
        from src.market.infrastructure.live_tape import (
            TRAY_TITLE_MAX,
            format_tray_title,
        )

        text = format_tray_title(
            {
                "as_of": "2026-07-30 11:00:12",
                "indices": [
                    {"label": "上证", "pct": -0.9, "ok": True},
                    {"label": "深证", "pct": -3.3, "ok": True},
                    {"label": "创业", "pct": -5.3, "ok": True},
                    {"label": "科创", "pct": -5.5, "ok": True},
                ],
                "positions": [
                    {
                        "name": "蓝英装备",
                        "pct": 0.2,
                        "ok": True,
                        "market_value": 100,
                    },
                    {
                        "name": "红板科技",
                        "pct": -10.1,
                        "ok": True,
                        "market_value": 100,
                    },
                    {
                        "name": "大连电瓷",
                        "pct": 1.0,
                        "ok": True,
                        "market_value": 100,
                    },
                ],
            }
        )
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("仓 "))
        self.assertIn("11:00", lines[0])
        self.assertIn("仓 -3.0%", lines[0])  # (0.2-10.1+1.0)/3
        # 持仓按今日涨跌升序：红板在前（名截到 4 字）
        body = "\n".join(lines)
        self.assertLess(body.index("红板科技"), body.index("蓝英装备"))
        self.assertLess(body.index("蓝英装备"), body.index("大连电瓷"))
        self.assertIn("▼红板科技", body)
        self.assertLessEqual(len(text), TRAY_TITLE_MAX)
        self.assertNotIn("pnl", body.lower())

    def test_format_tray_title_stays_within_windows_tip_limit(self) -> None:
        from src.market.infrastructure.live_tape import (
            TRAY_TITLE_MAX,
            format_tray_title,
        )

        positions = [
            {
                "name": f"测试股票{i}",
                "pct": float(i) - 4,
                "ok": True,
                "market_value": 100,
            }
            for i in range(8)
        ]
        text = format_tray_title(
            {
                "as_of": "2026-07-31 11:00:00",
                "indices": [
                    {"label": "上证", "pct": 1.0, "ok": True},
                    {"label": "深证", "pct": 2.0, "ok": True},
                    {"label": "创业", "pct": 3.0, "ok": True},
                    {"label": "科创", "pct": 4.0, "ok": True},
                ],
                "positions": positions,
            }
        )
        self.assertLessEqual(len(text), TRAY_TITLE_MAX)
        self.assertTrue(text.startswith("仓 "))


if __name__ == "__main__":
    unittest.main()
