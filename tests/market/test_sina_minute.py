"""新浪分钟线直连 —— mock HTTP，不打真网。"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from src.market.infrastructure import sina


class SinaMinuteTests(unittest.TestCase):
    def test_fetch_minute_parses_jsonp_and_filters_trade_date(self) -> None:
        payload = [
            {
                "day": "2026-07-28 09:31:00",
                "open": "10.000",
                "high": "10.100",
                "low": "9.900",
                "close": "10.050",
                "volume": "1000",
                "amount": "10050.0000",
            },
            {
                "day": "2026-07-29 09:31:00",
                "open": "11.000",
                "high": "11.200",
                "low": "10.900",
                "close": "11.100",
                "volume": "1200",
                "amount": "13320.0000",
            },
        ]
        body = f"=({json.dumps(payload)});"
        response = mock.Mock(status_code=200, text=body)
        with mock.patch(
            "src.market.infrastructure.http_client.market_get", return_value=response
        ) as get:
            out = sina.fetch_minute(
                "sz301201", period="1", trade_date="2026-07-28"
            )
        self.assertEqual(get.call_args.kwargs["params"]["symbol"], "sz301201")
        self.assertEqual(get.call_args.kwargs["params"]["scale"], "1")
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out["datetime"].iloc[0]), "2026-07-28 09:31:00")
        self.assertAlmostEqual(float(out["avg_price"].iloc[0]), 10.05)

    def test_fetch_minute_sanitizes_100x_dirty_avg(self) -> None:
        # 量按「手」误算时 额/量 ≈ 100× 现价，应回正到价格附近。
        payload = [
            {
                "day": "2026-07-28 09:31:00",
                "open": "10.000",
                "high": "10.100",
                "low": "9.900",
                "close": "10.050",
                "volume": "10",
                "amount": "10050.0000",
            },
        ]
        body = f"=({json.dumps(payload)});"
        response = mock.Mock(status_code=200, text=body)
        with mock.patch(
            "src.market.infrastructure.http_client.market_get", return_value=response
        ):
            out = sina.fetch_minute(
                "sz301201", period="1", trade_date="2026-07-28"
            )
        self.assertAlmostEqual(float(out["avg_price"].iloc[0]), 10.05)

    def test_fetch_minute_rejects_bad_period(self) -> None:
        with self.assertRaises(sina.SinaFetchError):
            sina.fetch_minute("sz301201", period="3")
