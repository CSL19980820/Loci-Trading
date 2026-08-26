"""东财行业图:失败冷却(src.market.infrastructure.em_industry)。

行业名是证券列表刷新路上的**锦上添花**,却曾是最贵的一步:端点挂掉时
akshare 内部 requests 要重试到超时才放弃,实测每次白等 19-22 秒。磁盘缓存
只在「成功取到过一次」之后才挡得住——全新机器 + 端点故障正好两头落空,
于是每一次刷新都要重付这 20 秒。
"""
from __future__ import annotations

import unittest
from unittest import mock

from src.market.infrastructure import em_industry as sources


class EmIndustryCooldownTests(unittest.TestCase):
    def setUp(self) -> None:
        sources._note_em_industry_result(ok=True)
        self.addCleanup(sources._note_em_industry_result, ok=True)
        patcher = mock.patch.object(
            sources, "_em_industry_cache_path", return_value=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_call_skips_remote_after_failure(self) -> None:
        """失败一次之后就别再等一遍超时——这是这段代码存在的全部理由。"""
        with mock.patch.object(
            sources, "_fetch_em_industry_remote", return_value={}
        ) as remote:
            self.assertEqual(sources.fetch_em_industry_map(), {})
            self.assertEqual(sources.fetch_em_industry_map(), {})
            self.assertEqual(remote.call_count, 1)

    def test_success_leaves_no_cooldown(self) -> None:
        """成功不该留惩罚期:下次到点了就得正常再取。"""
        with mock.patch.object(
            sources, "_fetch_em_industry_remote", return_value={"600519": "白酒"}
        ) as remote:
            self.assertEqual(sources.fetch_em_industry_map(), {"600519": "白酒"})
            self.assertEqual(sources.fetch_em_industry_map(), {"600519": "白酒"})
            self.assertEqual(remote.call_count, 2)
        self.assertEqual(sources._em_industry_in_cooldown(), 0.0)

    def test_cooldown_expires(self) -> None:
        """冷却是「稍后再试」,不是「永久放弃」。"""
        with mock.patch.dict(
            "os.environ", {sources._EM_INDUSTRY_COOLDOWN_ENV: "0"}
        ):
            with mock.patch.object(
                sources, "_fetch_em_industry_remote", return_value={}
            ) as remote:
                sources.fetch_em_industry_map()
                sources.fetch_em_industry_map()
                self.assertEqual(remote.call_count, 2)

    def test_stale_cache_still_wins_over_empty(self) -> None:
        """冷却期内也要兑现旧缓存,不能因为跳过远端就把全市场行业清空。"""
        stale = {"600519": "白酒"}
        with mock.patch.object(
            sources, "_read_em_industry_cache", return_value=(stale, 1e9)
        ):
            with mock.patch.object(
                sources, "_fetch_em_industry_remote", return_value={}
            ) as remote:
                self.assertEqual(sources.fetch_em_industry_map(), stale)
                self.assertEqual(sources.fetch_em_industry_map(), stale)
                self.assertEqual(remote.call_count, 1)

    def test_bad_cooldown_env_falls_back_to_default(self) -> None:
        with mock.patch.dict(
            "os.environ", {sources._EM_INDUSTRY_COOLDOWN_ENV: "一会儿"}
        ):
            self.assertEqual(
                sources._em_industry_cooldown_seconds(),
                sources._EM_INDUSTRY_FAIL_COOLDOWN_SEC,
            )


if __name__ == "__main__":
    unittest.main()
