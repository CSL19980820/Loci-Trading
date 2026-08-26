"""通达信历史分时回退：只测解析与路由边界，不打真实行情网。"""
from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters import fetch_minute_routed
from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.registry import reset_registry
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tdx_adapter import TdxAdapter
from src.market.infrastructure.tdx_minute import TdxMinuteError, fetch_minute_bars


def _tdx_rows() -> list[dict[str, float]]:
    return [
        {"price": 4.0 + index / 1000.0, "vol": float(index + 1)}
        for index in range(240)
    ]


class TdxMinuteTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_fetches_historical_day_with_fixed_trading_time_axis(self) -> None:
        client = mock.Mock()
        client.get_history_minute_time_data.return_value = _tdx_rows()

        with mock.patch(
            "src.market.infrastructure.tdx_minute._open_client",
            return_value=client,
        ):
            out = fetch_minute_bars(
                "300071", period="1", trade_date="2026-07-06"
            )

        self.assertEqual(len(out), 240)
        self.assertEqual(out.iloc[0]["datetime"], "2026-07-06 09:31")
        self.assertEqual(out.iloc[-1]["datetime"], "2026-07-06 15:00")
        self.assertAlmostEqual(float(out.iloc[0]["close"]), 4.0)
        self.assertAlmostEqual(float(out.iloc[-1]["volume"]), 240.0)
        client.get_history_minute_time_data.assert_called_once_with(
            0, "300071", 20260706
        )

    def test_rejects_an_unusable_history_response(self) -> None:
        client = mock.Mock()
        client.get_history_minute_time_data.return_value = []

        with mock.patch(
            "src.market.infrastructure.tdx_minute._open_client",
            return_value=client,
        ):
            with self.assertRaisesRegex(TdxMinuteError, "2026-07-06"):
                fetch_minute_bars(
                    "300071", period="1", trade_date="2026-07-06"
                )

    def test_rejects_an_all_zero_price_day(self) -> None:
        """停牌日 TDX 照样回 240 行，价格全 0；当成有数据会画出 0 元分时。"""
        client = mock.Mock()
        client.get_history_minute_time_data.return_value = [
            {"price": 0.0, "vol": 0.0} for _ in range(240)
        ]

        with mock.patch(
            "src.market.infrastructure.tdx_minute._open_client",
            return_value=client,
        ):
            with self.assertRaisesRegex(TdxMinuteError, "2026-07-06"):
                fetch_minute_bars("300071", period="1", trade_date="2026-07-06")

    def test_router_reaches_tdx_after_web_sources_fail(self) -> None:
        fallback = pd.DataFrame(
            {
                "datetime": ["2026-07-06 09:31"],
                "close": [3.97],
                "volume": [66880.0],
            }
        )
        with mock.patch.object(
            EastmoneyAdapter,
            "fetch_minute",
            side_effect=AdapterError("东财断连"),
        ), mock.patch.object(
            SinaAdapter,
            "fetch_minute",
            side_effect=AdapterError("新浪无历史数据"),
        ), mock.patch.object(
            TdxAdapter,
            "fetch_minute",
            return_value=fallback,
        ):
            frame, source = fetch_minute_routed(
                "300071",
                period="1",
                trade_date="2026-07-06",
                adapter_ids=["eastmoney", "sina", "tdx"],
            )

        self.assertEqual(source, "tdx")
        self.assertEqual(frame.to_dict("records"), fallback.to_dict("records"))


if __name__ == "__main__":
    unittest.main()
