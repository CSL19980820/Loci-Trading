"""东财整表的瞬时重试 —— 不打真网。

背景：全市场截面是盯盘大屏与信号预设的**唯一**数据源
(``market/application/watchlist.py:default_cross_section``)。生产日志里连续
数小时刷 ``东财全市场截面失败：ConnectionError: RemoteDisconnected``，而旧代码
一次都不重试，于是每次对端掐连接，大屏就整片空白 —— 用户报的「动不动就连接中断」。
"""
from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter


def _frame() -> pd.DataFrame:
    return pd.DataFrame([{"代码": "600519", "名称": "贵州茅台", "最新价": 1800.0}])


class EastmoneySpotRetryTests(unittest.TestCase):
    """只重试瞬时连接类错误；业务错与空表不重试。"""

    def setUp(self) -> None:
        self.adapter = EastmoneyAdapter()
        # 真睡 0.4s 会拖慢用例集；这里要断言的是「重试了」，不是「睡够了」
        patcher = mock.patch(
            "src.market.infrastructure.adapters.eastmoney_adapter.time.sleep"
        )
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_transient_connection_error_retries_once_and_succeeds(self) -> None:
        """RemoteDisconnected 这类瞬时错重发一次就该成 —— 大屏不该因此空一帧。"""
        calls = [ConnectionError("RemoteDisconnected"), _frame()]

        def _flaky() -> pd.DataFrame:
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(self.adapter, "_fetch_spot_em", side_effect=_flaky):
            raw = self.adapter._load_spot_raw(who="全市场截面")

        self.assertFalse(raw.empty)
        # 两次都被消费掉，才证明真的重试了
        self.assertEqual(calls, [])
        self.sleep.assert_called_once()

    def test_persistent_connection_error_still_raises_adapter_error(self) -> None:
        """一直连不上就照实抛；重试不是无限兜底。"""
        with mock.patch.object(
            self.adapter, "_fetch_spot_em", side_effect=ConnectionError("boom")
        ) as fetch:
            with self.assertRaises(AdapterError) as ctx:
                self.adapter._load_spot_raw(who="全市场截面")

        self.assertEqual(fetch.call_count, 2)
        self.assertIn("全市场截面", str(ctx.exception))

    def test_business_error_is_not_retried(self) -> None:
        """解析失败这类重试解决不了，重试只会把一次失败拖成两倍延迟。"""
        with mock.patch.object(
            self.adapter, "_fetch_spot_em", side_effect=ValueError("字段缺失")
        ) as fetch:
            with self.assertRaises(AdapterError):
                self.adapter._load_spot_raw(who="全市场截面")

        self.assertEqual(fetch.call_count, 1)
        self.sleep.assert_not_called()

    def test_empty_frame_is_not_retried(self) -> None:
        """空表是业务态，不是连接抖动。"""
        with mock.patch.object(
            self.adapter, "_fetch_spot_em", return_value=pd.DataFrame()
        ) as fetch:
            with self.assertRaises(AdapterError):
                self.adapter._load_spot_raw(who="全市场截面")

        self.assertEqual(fetch.call_count, 1)
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
