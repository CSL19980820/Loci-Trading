"""指数伪代码必须走 TDX 的指数协议，不能串成同号个股。

这是一次真实数据事故的回归：``get_security_bars`` 问 ``000905`` 不会报错，
它安静地返回**深市同号股票**的行情（收盘 8.54），而中证 500 当天是 7717。
这批值曾被写进生产库的基准指数，1.2 万行——基准一歪，所有相对收益都错。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.market.infrastructure import tdx_daily


class _FakeApi:
    """记下调用了哪套协议、哪个市场，返回可区分的值。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    @staticmethod
    def _bar(close: float) -> dict:
        return {
            "datetime": "2026-08-24 15:00",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "vol": 100.0,
            "amount": 1000.0,
        }

    def get_security_bars(self, _cat, market, code, _start, _count):
        self.calls.append(("security", market, code))
        return [self._bar(8.54)]

    def get_index_bars(self, _cat, market, code, _start, _count):
        self.calls.append(("index", market, code))
        return [self._bar(7717.09)]


class TdxIndexRoutingTests(unittest.TestCase):
    def _fetch(self, instrument_type: str):
        api = _FakeApi()
        with patch.object(tdx_daily, "_connection", return_value=api):
            frame = tdx_daily.fetch_daily_bars(
                "000905", bars=1, instrument_type=instrument_type
            )
        return api, frame

    def test_index_uses_index_protocol_on_shanghai_market(self) -> None:
        api, frame = self._fetch("INDEX")
        self.assertEqual(api.calls, [("index", 1, "000905")])
        self.assertAlmostEqual(float(frame["close"].iloc[-1]), 7717.09, places=2)

    def test_stock_still_uses_security_protocol(self) -> None:
        api, frame = self._fetch("STOCK")
        # 000905 在深市确实有一只同号个股，股票口径必须仍问 security。
        self.assertEqual(api.calls, [("security", 0, "000905")])
        self.assertAlmostEqual(float(frame["close"].iloc[-1]), 8.54, places=2)

    def test_default_is_stock_not_index(self) -> None:
        """不传类型时按股票处理：指数必须由调用方显式声明，不能靠猜。"""
        api = _FakeApi()
        with patch.object(tdx_daily, "_connection", return_value=api):
            tdx_daily.fetch_daily_bars("000905", bars=1)
        self.assertEqual(api.calls[0][0], "security")

    def test_batch_honours_per_code_instrument_type(self) -> None:
        """批量路径同样不能把指数当个股问——全市场同步走的就是它。"""
        api = _FakeApi()
        with patch.object(tdx_daily, "_connection", return_value=api):
            frames = tdx_daily.fetch_daily_many(
                ["000905", "600519"],
                bars=1,
                workers=1,
                instrument_types={"000905": "INDEX"},
            )
        kinds = {code: kind for kind, _market, code in api.calls}
        self.assertEqual(kinds["000905"], "index")
        self.assertEqual(kinds["600519"], "security")
        self.assertAlmostEqual(float(frames["000905"]["close"].iloc[-1]), 7717.09, places=2)


if __name__ == "__main__":
    unittest.main()