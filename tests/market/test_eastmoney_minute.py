"""东财分钟线直连解析 —— mock HTTP。"""
from __future__ import annotations

import unittest
from unittest import mock

from src.market.infrastructure.eastmoney_minute import (
    EastmoneyMinuteError,
    fetch_minute_bars,
)


def _json_response(payload: dict) -> mock.Mock:
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = payload
    return response


class EastmoneyMinuteTests(unittest.TestCase):
    def test_kline_trade_date_parses_and_filters(self) -> None:
        payload = {
            "data": {
                "klines": [
                    # 量=手、额=元 → VWAP=额/(量*100)
                    "2026-06-18 09:31,10.00,10.05,10.10,9.95,1000,1005000.00,0,0,0,0",
                    "2026-06-18 09:32,10.05,10.20,10.25,10.05,1200,1224000.00,0,0,0,0",
                    "2026-07-31 09:31,11.00,11.10,11.20,10.90,900,999000.00,0,0,0,0",
                ]
            }
        }
        with mock.patch(
            "src.market.infrastructure.http_client.market_get",
            return_value=_json_response(payload),
        ):
            out = fetch_minute_bars("000001", period="1", trade_date="2026-06-18")
        self.assertEqual(len(out), 2)
        self.assertTrue(str(out["datetime"].iloc[0]).startswith("2026-06-18"))
        self.assertAlmostEqual(float(out["close"].iloc[1]), 10.20)
        self.assertIn("avg_price", out.columns)
        # kline 量单位为手：1000 手 × 约 10.05 元 → 额 10050，VWAP≈10.05（非 100×）
        self.assertAlmostEqual(float(out["avg_price"].iloc[0]), 10.05, places=2)
        self.assertAlmostEqual(float(out["avg_price"].iloc[1]), 10.20, places=2)

    def test_trends_avg_sanitized_when_scaled_100x(self) -> None:
        trends = _json_response(
            {
                "data": {
                    "trends": [
                        "2026-07-31 09:30,4.00,4.10,4.20,3.90,100,41000.00,410.00",
                        "2026-07-31 09:31,4.10,4.21,4.21,4.00,200,84200.00,421.00",
                    ]
                }
            }
        )
        with mock.patch(
            "src.market.infrastructure.http_client.market_get",
            return_value=trends,
        ):
            # 该用例验证均价字段清洗，不应依赖运行当天是否仍在样本日期附近。
            out = fetch_minute_bars("600000", period="1", trade_date="2026-07-31")
        self.assertAlmostEqual(float(out["avg_price"].iloc[-1]), 4.21, places=2)

    def test_trends_fallback_when_kline_hosts_miss_day(self) -> None:
        empty_kline = _json_response({"data": {"klines": []}})
        trends = _json_response(
            {
                "data": {
                    "trends": [
                        "2026-07-31 09:30,11.50,11.50,11.50,11.50,100,1150.00,11.50",
                        "2026-07-31 09:31,11.50,11.46,11.50,11.38,200,2292.00,11.48",
                    ]
                }
            }
        )
        # 两主机 kline 皆空 → trends；trends 不含目标日 → 失败说明含「近窗」。
        with mock.patch(
            "src.market.infrastructure.http_client.market_get",
            side_effect=[empty_kline, empty_kline, trends],
        ):
            with self.assertRaisesRegex(EastmoneyMinuteError, "近窗"):
                fetch_minute_bars("000001", period="1", trade_date="2026-06-18")
