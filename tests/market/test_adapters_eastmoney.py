"""东财适配器：现货批量、分钟线与资金流 lane。

从 `test_adapters_vendor.py` 拆出（原 670 行）；腾讯与新浪用例仍在原文件。
"""
from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.registry import reset_registry
from src.market.infrastructure.adapters.router import fetch_minute_routed
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_CAPITAL_FLOW,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
)


def _spot_em_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "最新价": 1800.0,
                "今开": 1790.0,
                "最高": 1810.0,
                "最低": 1785.0,
                "昨收": 1795.0,
                "成交量": 10000.0,
                "成交额": 1.8e7,
                "涨跌幅": 0.28,
                "涨跌额": 5.0,
            },
            {
                "代码": "000001",
                "名称": "平安银行",
                "最新价": 10.5,
                "今开": 10.4,
                "最高": 10.6,
                "最低": 10.3,
                "昨收": 10.4,
                "成交量": 500000.0,
                "成交额": 5.25e6,
                "涨跌幅": 0.96,
                "涨跌额": 0.1,
            },
        ]
    )


class EastmoneySpotMinuteCapitalTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_registry()

    def test_fetch_spot_filters_codes(self) -> None:
        adapter = EastmoneyAdapter()
        with mock.patch.object(
            adapter, "_fetch_spot_em", return_value=_spot_em_frame()
        ):
            out = adapter.fetch_spot(["600519", "999999"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["code"], "600519")
        for col in ("open", "high", "low", "close", "volume", "amount", "date"):
            self.assertIn(col, out.columns)

    def test_fetch_live_quotes_rich_fields(self) -> None:
        adapter = EastmoneyAdapter()
        with mock.patch.object(
            adapter, "_fetch_spot_em", return_value=_spot_em_frame()
        ):
            rows = adapter.fetch_live_quotes(["600519"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["code"], "600519")
        self.assertEqual(row["name"], "贵州茅台")
        self.assertEqual(row["price"], 1800.0)
        self.assertEqual(row["prev_close"], 1795.0)
        self.assertEqual(row["source"], "eastmoney")
        # 东财现价成交量为手，管线应 ×100 成股
        self.assertAlmostEqual(float(row["volume"]), 1_000_000.0)

    def test_live_quotes_drop_rows_without_a_usable_price(self) -> None:
        """停牌行在东财现价表里是 NaN；NaN 出接口就是非法 JSON。"""
        raw = _spot_em_frame()
        raw.loc[raw["代码"] == "600519", "最新价"] = float("nan")
        adapter = EastmoneyAdapter()
        with mock.patch.object(adapter, "_fetch_spot_em", return_value=raw):
            rows = adapter.fetch_live_quotes(["600519", "000001"])

        self.assertEqual([row["code"] for row in rows], ["000001"])

    def test_fetch_minute_normalizes(self) -> None:
        raw = pd.DataFrame(
            {
                "datetime": ["2026-07-28 09:31:00", "2026-07-28 09:32:00"],
                "open": [10.0, 10.1],
                "close": [10.05, 10.2],
                "high": [10.1, 10.25],
                "low": [9.95, 10.05],
                "volume": [1000.0, 1200.0],
                "amount": [10050.0, 12240.0],
                "avg_price": [10.02, 10.15],
            }
        )
        adapter = EastmoneyAdapter()
        with mock.patch(
            "src.market.infrastructure.eastmoney_minute.fetch_minute_bars",
            return_value=raw,
        ) as mocked:
            out = adapter.fetch_minute("600519", period="1", days=1)
        mocked.assert_called_once_with(
            "600519", period="1", days=1, trade_date=None
        )
        self.assertEqual(len(out), 2)
        self.assertIn("datetime", out.columns)
        self.assertAlmostEqual(float(out["close"].iloc[0]), 10.05)

    def test_fetch_minute_trade_date_window(self) -> None:
        raw = pd.DataFrame(
            {
                "datetime": ["2026-07-28 09:31:00"],
                "open": [10.0],
                "close": [10.05],
                "high": [10.1],
                "low": [9.95],
                "volume": [1000.0],
                "amount": [10050.0],
                "avg_price": [10.02],
            }
        )
        adapter = EastmoneyAdapter()
        with mock.patch(
            "src.market.infrastructure.eastmoney_minute.fetch_minute_bars",
            return_value=raw,
        ) as mocked:
            out = adapter.fetch_minute(
                "600519", period="1", trade_date="2026-07-28"
            )
        mocked.assert_called_once_with(
            "600519", period="1", days=1, trade_date="2026-07-28"
        )
        self.assertEqual(len(out), 1)
        self.assertTrue(str(out["datetime"].iloc[0]).startswith("2026-07-28"))

    def test_sina_fetch_minute_trade_date(self) -> None:
        raw = pd.DataFrame(
            {
                "datetime": ["2026-07-28 09:31:00", "2026-07-29 09:31:00"],
                "open": [10.0, 11.0],
                "high": [10.1, 11.2],
                "low": [9.9, 10.9],
                "close": [10.05, 11.1],
                "volume": [1000.0, 1200.0],
                "amount": [10050.0, 13320.0],
                "avg_price": [10.05, 11.1],
            }
        )
        adapter = SinaAdapter()
        with mock.patch(
            "src.market.sina.fetch_minute", return_value=raw.iloc[:1].copy()
        ) as mocked:
            out = adapter.fetch_minute(
                "301201", period="1", trade_date="2026-07-28"
            )
        mocked.assert_called_once_with(
            "sz301201", period="1", days=1, trade_date="2026-07-28"
        )
        self.assertEqual(len(out), 1)
        self.assertTrue(str(out["datetime"].iloc[0]).startswith("2026-07-28"))

    def test_minute_route_falls_back_to_sina(self) -> None:
        """东财分钟线挂掉时，应落到新浪备源。"""

        class EmFail(MarketAdapter):
            meta = AdapterMeta(
                id="eastmoney",
                label="东财",
                lanes=(LANE_MINUTE,),
            )

            def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
                raise AdapterError("unused")

            def fetch_minute(
                self,
                code: str,
                *,
                period: str = "1",
                days: int = 1,
                trade_date: str | None = None,
            ) -> pd.DataFrame:
                raise AdapterError("东财断连")

        class SinaOk(MarketAdapter):
            meta = AdapterMeta(
                id="sina",
                label="新浪",
                lanes=(LANE_MINUTE,),
            )

            def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
                raise AdapterError("unused")

            def fetch_minute(
                self,
                code: str,
                *,
                period: str = "1",
                days: int = 1,
                trade_date: str | None = None,
            ) -> pd.DataFrame:
                return pd.DataFrame(
                    {
                        "datetime": ["2026-07-31 09:31:00"],
                        "open": [27.5],
                        "high": [27.6],
                        "low": [27.4],
                        "close": [27.55],
                        "volume": [1000.0],
                        "amount": [27550.0],
                        "avg_price": [27.55],
                    }
                )

        reset_registry([EmFail(), SinaOk()])
        frame, source = fetch_minute_routed("301201", period="1", days=1)
        self.assertEqual(source, "sina")
        self.assertEqual(len(frame), 1)

    def test_fetch_capital_flow_normalizes(self) -> None:
        raw = pd.DataFrame(
            {
                "日期": ["2026-07-25", "2026-07-28"],
                "收盘价": [10.0, 10.5],
                "涨跌幅": [1.0, 5.0],
                "主力净流入-净额": [1e6, 2e6],
                "主力净流入-净占比": [5.0, 8.0],
            }
        )
        adapter = EastmoneyAdapter()
        with mock.patch(
            "src.market.infrastructure.adapters.eastmoney_adapter._import_akshare"
        ) as mocked:
            mocked.return_value.stock_individual_fund_flow.return_value = raw
            out = adapter.fetch_capital_flow("600519")
        self.assertEqual(len(out), 2)
        self.assertIn("date", out.columns)
        self.assertIn("main_net_inflow", out.columns)
        self.assertAlmostEqual(float(out["main_net_inflow"].iloc[1]), 2e6)

    def test_probe_spot_batch_mocked(self) -> None:
        adapter = EastmoneyAdapter()
        with mock.patch.object(
            adapter, "_fetch_spot_em", return_value=_spot_em_frame()
        ):
            result = adapter.probe(LANE_SPOT_BATCH)
        self.assertTrue(result.ok)
        self.assertEqual(result.lane, LANE_SPOT_BATCH)
        self.assertEqual(result.rows, 1)

    def test_probe_minute_and_capital_mocked(self) -> None:
        adapter = EastmoneyAdapter()
        minute_raw = pd.DataFrame(
            {
                "datetime": ["2026-07-28 09:31:00"],
                "open": [10.0],
                "close": [10.05],
                "high": [10.1],
                "low": [9.95],
                "volume": [1000.0],
                "amount": [10050.0],
                "avg_price": [10.05],
            }
        )
        capital_raw = pd.DataFrame(
            {
                "日期": ["2026-07-28"],
                "收盘价": [10.5],
                "涨跌幅": [5.0],
                "主力净流入-净额": [2e6],
                "主力净流入-净占比": [8.0],
            }
        )
        with mock.patch(
            "src.market.infrastructure.eastmoney_minute.fetch_minute_bars",
            return_value=minute_raw,
        ), mock.patch(
            "src.market.infrastructure.adapters.eastmoney_adapter._import_akshare"
        ) as mocked:
            mocked.return_value.stock_individual_fund_flow.return_value = capital_raw
            min_result = adapter.probe(LANE_MINUTE)
            cap_result = adapter.probe(LANE_CAPITAL_FLOW)
        self.assertTrue(min_result.ok)
        self.assertTrue(cap_result.ok)


if __name__ == "__main__":
    unittest.main()
