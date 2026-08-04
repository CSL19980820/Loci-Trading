"""数据线路适配器层单测 —— 不打真网。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from typing import Any
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    all_adapters,
    enabled_adapter_ids,
    get_adapter,
    list_catalog,
    reset_registry,
)
from src.market.infrastructure.adapters.router import (
    clear_sticky,
    fetch_capital_flow_routed,
    fetch_daily_best,
    fetch_daily_routed,
    fetch_live_quotes_routed,
    fetch_minute_routed,
    fetch_spot_routed,
    probe_lane,
)
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    ProbeResult,
)


def _daily_frame(n: int = 3, *, turnover: float = 0.05) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [f"2026-01-{i:02d}" for i in range(1, n + 1)],
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.5] * n,
            "volume": [1_000_000.0] * n,
            "amount": [10_000_000.0] * n,
            "turnover": [turnover] * n,
            "outstanding_share": [1e9] * n,
        }
    )


def _tencent_spot_line(
    symbol: str = "sh600519",
    *,
    name: str = "贵州茅台",
    code: str = "600519",
    price: float = 1320.0,
    prev: float = 1289.5,
    open_: float = 1299.0,
    high: float = 1320.0,
    low: float = 1289.52,
    lots: float = 531.0,
    amount: float = 6960058121.0,
) -> str:
    fields = [""] * 38
    fields[0] = "1"
    fields[1] = name
    fields[2] = code
    fields[3] = f"{price:.2f}"
    fields[4] = f"{prev:.2f}"
    fields[5] = f"{open_:.2f}"
    fields[30] = "20260728143000"
    fields[31] = f"{price - prev:.2f}"
    fields[32] = f"{(price - prev) / prev * 100:.2f}"
    fields[33] = f"{high:.2f}"
    fields[34] = f"{low:.2f}"
    fields[35] = f"{price:.2f}/{lots:.0f}/{amount:.0f}"
    fields[36] = f"{lots:.0f}"
    fields[37] = f"{amount / 10000:.0f}"
    return f'v_{symbol}="' + "~".join(fields) + '";'


class TencentModuleTests(unittest.TestCase):
    def test_parse_spot_line(self) -> None:
        from src.market import tencent

        row = tencent._parse_spot_row(_tencent_spot_line())
        assert row is not None
        self.assertEqual(row["symbol"], "sh600519")
        self.assertAlmostEqual(row["close"], 1320.0)
        self.assertAlmostEqual(row["volume"], 53100.0)
        self.assertAlmostEqual(row["amount"], 6960058121.0)

    def test_parse_live_row(self) -> None:
        from src.market import tencent

        row = tencent._parse_live_row(_tencent_spot_line())
        assert row is not None
        self.assertEqual(row["source"], "tencent")
        self.assertAlmostEqual(row["price"], 1320.0)

    def test_parse_daily_rows(self) -> None:
        from src.market import tencent

        raw = [["2026-07-28", "1299.000", "1320.000", "1320.000", "1289.520", "531.000"]]
        frame = tencent._parse_daily_rows(raw)
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(float(frame["volume"].iloc[0]), 53100.0)
        self.assertAlmostEqual(float(frame["close"].iloc[0]), 1320.0)

    def test_fetch_spot_mocked(self) -> None:
        from src.market import tencent

        with mock.patch(
            "src.market.infrastructure.tencent._get",
            return_value=_tencent_spot_line(),
        ):
            frame = tencent.fetch_spot(["sh600519"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["symbol"], "sh600519")

    def test_fetch_daily_recent_mocked(self) -> None:
        from src.market import tencent

        payload = (
            '{"code":0,"data":{"sh600519":{"day":'
            '[["2026-07-28","1299.000","1320.000","1320.000","1289.520","531.000"]]'
            "}}}"
        )
        with mock.patch("src.market.infrastructure.tencent._get", return_value=payload):
            frame = tencent.fetch_daily_recent("sh600519", count=5)
        self.assertEqual(len(frame), 1)
        adapter = TencentAdapter()
        out = adapter._normalize_daily(frame)
        self.assertIn("amount", out.columns)

    def test_probe_hist_daily_uses_requested_code(self) -> None:
        adapter = TencentAdapter()
        frame = _daily_frame(1)
        with mock.patch(
            "src.market.infrastructure.tencent.fetch_daily_recent", return_value=frame
        ) as fetch:
            result = adapter.probe(LANE_HIST_DAILY, code="000001")

        self.assertTrue(result.ok)
        fetch.assert_called_once_with("sz000001", count=30)

    def test_adapter_fetch_spot_mocked(self) -> None:
        adapter = TencentAdapter()
        spot = pd.DataFrame(
            [
                {
                    "symbol": "sh600519",
                    "date": pd.Timestamp("2026-07-28").date(),
                    "open": 1299.0,
                    "high": 1320.0,
                    "low": 1289.52,
                    "close": 1320.0,
                    "volume": 53100.0,
                    "amount": 6960058121.0,
                }
            ]
        )
        with mock.patch("src.market.infrastructure.tencent.fetch_spot", return_value=spot):
            frame = adapter.fetch_spot(["600519"])
        self.assertEqual(frame.iloc[0]["code"], "600519")


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
