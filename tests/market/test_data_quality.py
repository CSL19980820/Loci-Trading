"""行情库体检:阈值判据与中文告警。

体检是换源之后唯一的日常防线,它自己不能出错——判据写反会让泡坏的库看起来全绿。
"""
from __future__ import annotations

import sqlite3
import unittest

from src.market.application.data_quality import (
    Finding,
    QualityThresholds,
    build_alert,
    inspect_market_data,
)


class _FakeStore:
    """只提供 ``conn``——体检只读 SQL,不该碰 store 的其它面。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


def _build_db(rows: list[tuple], *, instruments: list[tuple] | None = None,
            watermarks: list[tuple] | None = None) -> _FakeStore:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE quotes_daily (code TEXT, trade_date TEXT, close REAL,"
        " volume REAL, amount REAL, source TEXT, receipt_id TEXT)"
    )
    conn.executemany("INSERT INTO quotes_daily VALUES (?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE TABLE trading_calendar (trade_date TEXT)")
    days = sorted({r[1] for r in rows})
    conn.executemany("INSERT INTO trading_calendar VALUES (?)", [(d,) for d in days])
    conn.execute("CREATE TABLE instruments (code TEXT, status TEXT)")
    conn.executemany("INSERT INTO instruments VALUES (?,?)", instruments or [])
    conn.execute(
        "CREATE TABLE ingest_watermark (code TEXT, source TEXT, status TEXT,"
        " last_trade_date TEXT)"
    )
    conn.executemany(
        "INSERT INTO ingest_watermark VALUES (?,?,?,?)", watermarks or []
    )
    return _FakeStore(conn)


def _healthy_rows(count: int = 20) -> list[tuple]:
    """tdx 源 + 真实成交额(amount != close*volume)+ 有回执。"""
    return [
        ("%06d" % i, "2026-08-24", 10.0, 1000.0, 12345.0, "tdx", "r%d" % i)
        for i in range(count)
    ]


LOOSE = QualityThresholds(min_last_day_rows=1, min_authoritative_ratio=0.95)


class AuthoritativeRatioTests(unittest.TestCase):
    def test_all_tdx_is_ok(self) -> None:
        store = _build_db(_healthy_rows())
        report = inspect_market_data(store, thresholds=LOOSE)
        self.assertFalse(report["blocked"])
        self.assertEqual(report["alert"], "")

    def test_fallback_majority_blocks(self) -> None:
        """主源长期失联 = 库在靠回退源续命,必须阻断,不能只是提醒。"""
        rows = _healthy_rows(5) + [
            ("9%05d" % i, "2026-08-24", 10.0, 1000.0, 12345.0, "tencent", "r")
            for i in range(95)
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        self.assertTrue(report["blocked"])
        finding = next(f for f in report["findings"] if f["key"] == "authoritative_ratio")
        self.assertEqual(finding["level"], "block")
        self.assertIn("通达信", finding["message"])
        self.assertIn("resync_market_authoritative", finding["remediation"])


class FabricatedAmountTests(unittest.TestCase):
    def test_synth_amount_on_tdx_is_not_flagged(self) -> None:
        """关键判据:通达信给的是真实成交额,即使数值恰好相等也不算合成。"""
        rows = [
            ("%06d" % i, "2026-08-24", 10.0, 1000.0, 10000.0, "tdx", "r")
            for i in range(50)
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "fabricated_amount")
        self.assertEqual(finding["level"], "ok")
        self.assertEqual(finding["observed"]["rows"], 0)

    def test_synth_amount_on_tencent_is_flagged(self) -> None:
        rows = _healthy_rows(90) + [
            ("9%05d" % i, "2026-08-24", 10.0, 1000.0, 10000.0, "tencent", "r")
            for i in range(5)
        ]
        limits = QualityThresholds(min_last_day_rows=1, max_fabricated_rows=2)
        report = inspect_market_data(_build_db(rows), thresholds=limits)
        finding = next(f for f in report["findings"] if f["key"] == "fabricated_amount")
        self.assertEqual(finding["level"], "warn")
        self.assertEqual(finding["observed"]["rows"], 5)
        self.assertIn("close×volume", finding["message"])


class IndexSanityTests(unittest.TestCase):
    def test_index_串成个股_blocks(self) -> None:
        """中证 500 该 7717,串成同号个股会返回 8.54——这是真出过的事故。"""
        rows = _healthy_rows(10) + [
            ("000905", "2026-08-24", 8.54, 1000.0, 12345.0, "tdx", "r"),
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        self.assertTrue(report["blocked"])
        finding = next(f for f in report["findings"] if f["key"] == "index_sanity")
        self.assertEqual(finding["level"], "block")
        self.assertIn("get_index_bars", finding["message"])

    def test_real_index_level_is_ok(self) -> None:
        rows = _healthy_rows(10) + [
            ("000905", "2026-08-24", 7717.0, 1000.0, 12345.0, "tdx", "r"),
        ]
        report = inspect_market_data(_build_db(rows), thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "index_sanity")
        self.assertEqual(finding["level"], "ok")


class WatermarkTests(unittest.TestCase):
    def test_delisted_non_tdx_watermark_is_explained(self) -> None:
        """退市票通达信取不到是正常的,不该天天报警。"""
        store = _build_db(
            _healthy_rows(10),
            instruments=[("920305", "delisted")],
            watermarks=[("920305", "sina", "ok", "2026-07-29")],
        )
        report = inspect_market_data(store, thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "watermark_source")
        self.assertEqual(finding["level"], "ok")

    def test_active_non_tdx_watermark_warns(self) -> None:
        store = _build_db(
            _healthy_rows(10),
            instruments=[("600519", "listed")],
            watermarks=[("600519", "tencent", "ok", "2026-07-29")],
        )
        report = inspect_market_data(store, thresholds=LOOSE)
        finding = next(f for f in report["findings"] if f["key"] == "watermark_source")
        self.assertEqual(finding["level"], "warn")


class AlertTests(unittest.TestCase):
    def test_all_green_is_silent(self) -> None:
        """没事就别打扰人——全绿必须是空串,否则告警会被当噪音忽略。"""
        self.assertEqual(build_alert([Finding("a", "ok", "fine")]), "")

    def test_alert_carries_level_and_remediation(self) -> None:
        text = build_alert([
            Finding("a", "block", "主源没了", remediation="去看连通性"),
            Finding("b", "warn", "有点脏"),
            Finding("c", "ok", "没事"),
        ])
        self.assertIn("【阻断】主源没了", text)
        self.assertIn("处理：去看连通性", text)
        self.assertIn("【提醒】有点脏", text)
        self.assertNotIn("没事", text)


if __name__ == "__main__":
    unittest.main()