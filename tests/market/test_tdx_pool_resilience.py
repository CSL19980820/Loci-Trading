"""主源整池不可用时必须**快速失败**，让路由立刻换源。

回归两次真实事故：

1. 排序结果落盘缓存（TTL 6 小时）钉住的服务器一起挂掉后，旧实现在 TTL 内
   每次都失败且永不重探——整条主源静默全废 6 小时。
2. 加了「全池重探」自愈之后，整池真的挂掉时每一票要走完 38 台 × 4s 超时
   两轮，实测单票 308s，全市场同步根本跑不完。
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from src.market.infrastructure import tdx_daily


class _DeadApi:
    """TCP 连得上、协议不回话——被限流时服务端就是这个表现。"""

    attempts = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def connect(self, _host, _port, time_out=None):
        type(self).attempts += 1
        raise TimeoutError("timed out")


class TdxPoolResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        tdx_daily.reset_servers()
        _DeadApi.attempts = 0

    def tearDown(self) -> None:
        tdx_daily.reset_servers()

    def test_single_attempt_is_bounded_by_host_budget(self) -> None:
        """整池挂掉时不许走完全池：38 台 × 4s 会把每一票拖成两分钟。"""
        with patch.object(tdx_daily, "_api_class", return_value=_DeadApi), patch.object(
            tdx_daily, "rank_servers", return_value=list(tdx_daily._SERVERS)
        ), patch.object(tdx_daily, "_drop_cache"):
            with self.assertRaises(tdx_daily.TdxDailyError):
                tdx_daily._connection()
        # 两轮（缓存名单 + 全池重探），每轮最多 budget 台。
        self.assertLessEqual(_DeadApi.attempts, tdx_daily._CONNECT_HOST_BUDGET * 2)
        self.assertLess(_DeadApi.attempts, len(tdx_daily._SERVERS))

    def test_pool_down_cooldown_fails_fast_without_reconnecting(self) -> None:
        """判死之后进冷却：冷却期内一次 socket 都不许再建。"""
        with patch.object(tdx_daily, "_api_class", return_value=_DeadApi), patch.object(
            tdx_daily, "rank_servers", return_value=list(tdx_daily._SERVERS)
        ), patch.object(tdx_daily, "_drop_cache"):
            with self.assertRaises(tdx_daily.TdxDailyError):
                tdx_daily._connection()
            first_round = _DeadApi.attempts
            began = time.perf_counter()
            for _ in range(5):
                with self.assertRaises(tdx_daily.TdxDailyError):
                    tdx_daily._connection()
            elapsed = time.perf_counter() - began
        self.assertEqual(_DeadApi.attempts, first_round, "冷却期内不该再建连")
        self.assertLess(elapsed, 1.0, "冷却期内必须立刻失败")

    def test_reset_clears_cooldown(self) -> None:
        tdx_daily._mark_pool_down()
        self.assertTrue(tdx_daily._pool_down())
        tdx_daily.reset_servers()
        self.assertFalse(tdx_daily._pool_down())

    def test_recovery_clears_cooldown(self) -> None:
        """源恢复后要立刻回到主源，不能被自己的冷却挡住。"""

        class _LiveApi(_DeadApi):
            def connect(self, _host, _port, time_out=None):
                return True

        tdx_daily._mark_pool_down()
        tdx_daily._clear_pool_down()
        with patch.object(tdx_daily, "_api_class", return_value=_LiveApi):
            self.assertIsNotNone(tdx_daily._connection())
        self.assertFalse(tdx_daily._pool_down())


if __name__ == "__main__":
    unittest.main()