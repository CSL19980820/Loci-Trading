"""情报配方与配额分池测试。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from src.intel.application.daily_recipe import (
    estimate_daily_calls,
    intraday_runs_from_cron,
    structured_budget_alert,
)
from src.intel.infrastructure.quota import (
    McpQuotaError,
    acquire_quota,
    clear_quota_reservations,
    quota_limits,
    record_quota_call,
)

#: 三条托管情报任务在 `ops/application/ensure_intel_jobs.py` 里的真实配置。
MANAGED_PHASE_PARAMS = {
    "open": {"theme_top_n": 150, "screener_count": 12},
    "intraday": {"theme_top_n": 120, "stock_flow_top_n": 120},
    "close": {"theme_top_n": 200, "stock_flow_top_n": 240, "screener_count": 16},
}
MANAGED_INTRADAY_CRON = "*/15 9-14 * * mon-fri"


class DailyRecipeEstimateTests(unittest.TestCase):
    def test_managed_setup_stays_inside_structured_budget(self) -> None:
        """按托管任务的真实配置 + 真实 cron 估，必须压在 structured 3000 以内。"""
        row = estimate_daily_calls(
            intraday_cron=MANAGED_INTRADAY_CRON,
            phase_params=MANAGED_PHASE_PARAMS,
        )
        self.assertEqual(row["intraday_runs"], 24, "轮次要从 cron 推，不是写死 20")
        self.assertLessEqual(row["estimated_total"], 3000)
        self.assertTrue(row["within_budget"])
        self.assertIsNone(structured_budget_alert(row))
        self.assertEqual(row["structured_budget"], 3000)
        self.assertEqual(row["skill_reserve"], 2000)

    def test_intraday_theme_cap_is_what_keeps_it_under_budget(self) -> None:
        """把盘中题材上限放回 120，就会超预算并给出中文告警（不静默截断）。"""
        params = dict(MANAGED_PHASE_PARAMS)
        params["intraday"] = {**params["intraday"], "intraday_theme_top_n": 120}
        row = estimate_daily_calls(
            intraday_cron=MANAGED_INTRADAY_CRON,
            phase_params=params,
        )
        self.assertGreater(row["estimated_total"], 3000)
        self.assertFalse(row["within_budget"])
        alert = structured_budget_alert(row)
        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertIn("intraday_theme_top_n", alert["message"])
        self.assertIn("不会自动少拿数据", alert["message"])
        self.assertEqual(alert["over_by"], row["estimated_total"] - 3000)

    def test_intraday_runs_follow_the_cron(self) -> None:
        self.assertEqual(intraday_runs_from_cron(MANAGED_INTRADAY_CRON), 24)
        self.assertEqual(intraday_runs_from_cron("*/30 9-14 * * mon-fri"), 12)
        self.assertEqual(intraday_runs_from_cron("0,30 9-11,13-14 * * mon-fri"), 10)
        # 解析不了就退回托管 cron 的轮数，绝不返回一个更乐观的数字
        self.assertEqual(intraday_runs_from_cron("看不懂"), 24)

    def test_pools_follow_the_caller_not_a_hardcoded_string(self) -> None:
        """分池按「谁发起的」：情报配方 structured，tape/盯盘 skill，且都可参数化。"""
        from src.market.domain.tape import TapeRequest
        from src.market.infrastructure.tape.wudao_provider import tape_quota_pool
        from src.ops.application.jobs.intel_fetch import resolve_pool

        self.assertEqual(resolve_pool(None), "structured")
        self.assertEqual(resolve_pool("skill"), "skill")
        self.assertEqual(resolve_pool("不存在的池"), "structured")
        self.assertEqual(tape_quota_pool(TapeRequest(lane="market_emotion")), "skill")
        self.assertEqual(
            tape_quota_pool(
                TapeRequest(lane="market_emotion", context={"quota_pool": "structured"})
            ),
            "structured",
        )


class McpQuotaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.ops_path = os.path.join(self.temp.name, "ops.db")
        self.env = patch.dict(
            os.environ,
            {
                "PALACE_OPS_DB": self.ops_path,
                "LOCI_MCP_QUOTA_STRUCTURED": "3",
                "LOCI_MCP_QUOTA_SKILL": "2",
                "LOCI_MCP_QUOTA_DAILY": "5",
                "LOCI_MCP_RATE_PER_MIN": "100",
            },
        )
        self.env.start()
        clear_quota_reservations()

    def tearDown(self) -> None:
        clear_quota_reservations()
        self.env.stop()
        self.temp.cleanup()

    def test_structured_pool_blocks_after_budget(self) -> None:
        acquire_quota("structured")
        record_quota_call("structured")
        acquire_quota("structured")
        record_quota_call("structured")
        acquire_quota("structured")
        record_quota_call("structured")
        with self.assertRaisesRegex(Exception, "结构化采集"):
            acquire_quota("structured")

    def test_skill_pool_isolated_from_structured(self) -> None:
        for _ in range(3):
            acquire_quota("structured")
            record_quota_call("structured")
        acquire_quota("skill")
        record_quota_call("skill")
        snap = quota_limits()
        self.assertEqual(snap.structured, 3)
        self.assertEqual(snap.skill, 2)

    def test_minute_limit_waits_for_a_slot_instead_of_failing(self) -> None:
        """每分钟名额是本地节流器，撞上应排队。

        判失败会把情报 Job 刷红（`stats.failed>0`），Skill 侧更糟：取数失败按红线
        要走失败关闭，一次限流就能把结论改成空仓。
        """
        with (
            patch.dict(os.environ, {"LOCI_MCP_RATE_PER_MIN": "2"}),
            patch("src.intel.infrastructure.quota._MINUTE_WINDOW_SECONDS", 0.4),
        ):
            for _ in range(2):
                acquire_quota("structured")
                record_quota_call("structured")
            started = time.monotonic()
            acquire_quota("structured")
            record_quota_call("structured")
            waited = time.monotonic() - started
        self.assertGreater(waited, 0.05, "第三次应当等到名额腾出，而不是立刻放行")
        self.assertLess(waited, 5.0, "等待应当在一个窗口内结束")

    def test_minute_wait_gives_up_instead_of_hanging_forever(self) -> None:
        """名额迟迟不腾出时要报错退出，不能把调度线程永久挂住。"""
        with (
            patch.dict(os.environ, {"LOCI_MCP_RATE_PER_MIN": "1"}),
            patch("src.intel.infrastructure.quota._MINUTE_WINDOW_SECONDS", 30.0),
            patch("src.intel.infrastructure.quota._MINUTE_WAIT_MAX_SECONDS", 0.2),
        ):
            acquire_quota("structured")
            record_quota_call("structured")
            with self.assertRaisesRegex(McpQuotaError, "等待超时"):
                acquire_quota("structured")

    def test_daily_pool_exhaustion_still_fails_fast(self) -> None:
        """日配额用尽是"今天真没了"，必须立刻抛，不能被当成限流去排队等。"""
        for _ in range(3):
            acquire_quota("structured")
            record_quota_call("structured")
        started = time.monotonic()
        with self.assertRaisesRegex(McpQuotaError, "结构化采集"):
            acquire_quota("structured")
        self.assertLess(time.monotonic() - started, 1.0, "日配额用尽不应进入等待")

    def test_concurrent_acquire_cannot_oversell_the_pool(self) -> None:
        """并发扫描（题材成分是 4 线程并行）不得靠"记账在调用之后"绕过配额。"""
        for _ in range(2):
            acquire_quota("structured")
            record_quota_call("structured")

        start = threading.Barrier(4)

        def attempt() -> bool:
            start.wait(timeout=5)
            try:
                acquire_quota("structured")
            except McpQuotaError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=4) as pool:
            granted = sum(pool.map(lambda _: attempt(), range(4)))

        self.assertEqual(granted, 1, "剩余 1 次配额只能发给一个调用方")
