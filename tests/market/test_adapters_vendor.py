"""腾讯 / 新浪适配器：分页、批量诚实性与现货成交量单位。

东财用例在 `test_adapters_eastmoney.py`。
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.types import LANE_HIST_DAILY


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


def _tencent_daily_row(day: str) -> list[str]:
    return [day, "10.00", "10.50", "11.00", "9.00", "100"]


def _tencent_daily_payload(symbol: str, rows: list[list[Any]]) -> str:
    import json

    return json.dumps({"code": 0, "data": {symbol: {"day": rows}}})


class TencentPagingTests(unittest.TestCase):
    """全历史分页：截断 = 静默丢历史，死循环 = 同步永远跑不完。"""

    def test_paging_does_not_stop_because_a_page_had_unparsable_rows(self) -> None:
        from src.market import tencent

        page_one = [
            _tencent_daily_row("2026-01-05"),
            ["2026-01-06", "脏行"],  # 源侧脏行：解析要丢，但这一页仍是满的
            _tencent_daily_row("2026-01-07"),
            _tencent_daily_row("2026-01-08"),
        ]
        page_two = [_tencent_daily_row("2026-01-01"), _tencent_daily_row("2026-01-02")]
        calls: list[str] = []

        def fake_get(url: str, *, params: Any = None, session: Any = None) -> str:
            calls.append(str((params or {}).get("param", "")))
            rows = page_one if len(calls) == 1 else page_two
            return _tencent_daily_payload("sh600519", rows)

        with mock.patch.object(tencent, "DAILY_PAGE_SIZE", 4), mock.patch(
            "src.market.infrastructure.tencent._get", side_effect=fake_get
        ):
            frame = tencent.fetch_daily("sh600519")

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(frame), 5)
        self.assertEqual(str(frame["date"].min()), "2026-01-01")

    def test_paging_stops_when_the_source_ignores_the_end_date(self) -> None:
        from src.market import tencent

        page = [_tencent_daily_row("2026-01-05"), _tencent_daily_row("2026-01-06")]
        calls: list[str] = []

        def fake_get(url: str, *, params: Any = None, session: Any = None) -> str:
            calls.append(str((params or {}).get("param", "")))
            if len(calls) > 5:
                raise AssertionError("翻页没有终止条件，会一直拿同一页")
            return _tencent_daily_payload("sh600519", page)

        with mock.patch.object(tencent, "DAILY_PAGE_SIZE", 2), mock.patch(
            "src.market.infrastructure.tencent._get", side_effect=fake_get
        ):
            frame = tencent.fetch_daily("sh600519")

        self.assertLessEqual(len(calls), 2)
        self.assertEqual(len(frame), 2)


class LiveBatchHonestyTests(unittest.TestCase):
    """全批失败必须报网络原因，别返回空表让上层说成「行情为空」。"""

    def test_tencent_live_raises_the_real_cause_when_every_batch_fails(self) -> None:
        from src.market import tencent

        with mock.patch(
            "src.market.infrastructure.tencent._get",
            side_effect=tencent.TencentFetchError("请求失败：ReadTimeout"),
        ):
            with self.assertRaisesRegex(tencent.TencentFetchError, "ReadTimeout"):
                tencent.fetch_live_hq(["sh600519"])

    def test_sina_live_raises_the_real_cause_when_every_batch_fails(self) -> None:
        from src.market import sina

        with mock.patch(
            "src.market.infrastructure.sina._get",
            side_effect=sina.SinaFetchError("返回 456"),
        ):
            with self.assertRaisesRegex(sina.SinaFetchError, "456"):
                sina.fetch_live_hq(["sz000001"])

    def test_partial_batch_failure_still_returns_what_arrived(self) -> None:
        from src.market import tencent

        calls: list[int] = []

        def flaky(url: str, *, session: Any = None) -> str:
            calls.append(1)
            if len(calls) == 1:
                raise tencent.TencentFetchError("请求失败：ReadTimeout")
            return _tencent_spot_line()

        with mock.patch.object(tencent, "SPOT_BATCH_SIZE", 1), mock.patch(
            "src.market.infrastructure.tencent._get", side_effect=flaky
        ):
            rows = tencent.fetch_live_hq(["sh600519", "sz000001"])

        self.assertEqual(len(rows), 1)


class SinaSpotTests(unittest.TestCase):
    @staticmethod
    def _line(*, price: float, volume: float, amount: float) -> str:
        fields = [""] * 34
        fields[0] = "平安银行"
        fields[1] = "11.000"
        fields[2] = "11.200"
        fields[3] = f"{price:.3f}"
        fields[4] = "11.300"
        fields[5] = "10.900"
        fields[8] = f"{volume:.0f}"
        fields[9] = f"{amount:.3f}"
        fields[30] = "2026-07-28"
        fields[31] = "15:00:00"
        return 'var hq_str_sz000001="' + ",".join(fields) + '";'

    def test_zero_trade_row_is_not_written_as_a_bar(self) -> None:
        """停牌只回昨收、零成交；当成当日 K 线会凭空多出一个交易日。"""
        from src.market import sina

        with mock.patch(
            "src.market.infrastructure.sina._get",
            return_value=self._line(price=11.2, volume=0.0, amount=0.0),
        ):
            frame = sina.fetch_spot(["sz000001"])

        self.assertTrue(frame.empty)

    def test_traded_row_still_becomes_a_bar(self) -> None:
        from src.market import sina

        with mock.patch(
            "src.market.infrastructure.sina._get",
            return_value=self._line(price=11.2, volume=1000.0, amount=11200.0),
        ):
            frame = sina.fetch_spot(["sz000001"])

        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(float(frame.iloc[0]["volume"]), 1000.0)


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

    def test_spot_line_without_any_trade_is_not_a_bar(self) -> None:
        """停牌只有昨收、零成交：写进日线表就是凭空多出一个交易日。"""
        from src.market import tencent

        self.assertIsNone(
            tencent._parse_spot_row(_tencent_spot_line(lots=0.0, amount=0.0))
        )
        # 有成交的正常行不受影响
        self.assertIsNotNone(tencent._parse_spot_row(_tencent_spot_line()))

    def test_declares_its_amount_as_an_estimate(self) -> None:
        """腾讯日 K 没有成交额，close×volume 只是估算，必须自报。"""
        self.assertIn("amount", TencentAdapter.meta.estimated_fields)

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


class TencentSpotVolumeUnitTests(unittest.TestCase):
    """现价成交量单位：与日 K 同口径，科创板源侧已是「股」。

    夹具 ``fixtures/tencent/qt_spot_boards.txt`` 是 2026-08-11 盘中录制的真实
    ``qt.gtimg.cn`` 报文。判据不看板块表，而看物理自洽：``成交额 ≈ 成交量 × 现价``。
    多乘 100 会让这个比值掉到 0.01。
    """

    @staticmethod
    def _lines() -> list[str]:
        from pathlib import Path

        raw = (
            Path(__file__).parent / "fixtures" / "tencent" / "qt_spot_boards.txt"
        ).read_text(encoding="utf-8")
        return [chunk for chunk in raw.split(";") if "~" in chunk]

    def test_spot_volume_is_consistent_with_amount_on_every_board(self) -> None:
        from src.market import tencent

        seen: set[str] = set()
        for line in self._lines():
            row = tencent._parse_spot_row(line)
            assert row is not None, line[:40]
            seen.add(row["symbol"])
            implied = row["amount"] / (row["volume"] * row["close"])
            self.assertAlmostEqual(implied, 1.0, delta=0.05, msg=row["symbol"])
        self.assertIn("sh688981", seen)  # 科创板必须在样本里
        self.assertIn("sh600519", seen)

    def test_live_volume_uses_the_same_scale(self) -> None:
        from src.market import tencent

        for line in self._lines():
            row = tencent._parse_live_row(line)
            assert row is not None, line[:40]
            implied = row["amount"] / (row["volume"] * row["price"])
            self.assertAlmostEqual(implied, 1.0, delta=0.05, msg=row["symbol"])

    def test_star_board_is_not_multiplied_by_a_hundred(self) -> None:
        from src.market import tencent

        rows = {
            row["symbol"]: row
            for row in (tencent._parse_spot_row(line) for line in self._lines())
            if row
        }
        star = rows["sh688981"]
        main = rows["sh600519"]
        # 源侧第 36 列：科创板是股，主板是手
        self.assertAlmostEqual(star["volume"], 37_175_996.0)
        self.assertAlmostEqual(main["volume"], 27_073.0 * 100.0)
