"""托管行情库体检:创建、幂等、执行器接线、阈值覆盖。

这个任务是换源后唯一的日常防线。它要是没被注册进 JOB_KINDS / EXECUTORS,
创建时就会抛「未知任务类型」——那种失败在启动期只会写一行 warning,没人看得见。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ops.application.ensure_market_quality_job import (
    MARKET_QUALITY_CRON,
    ensure_managed_market_quality_job,
)
from src.ops.application.jobs.data_quality import _thresholds
from src.ops.application.jobs.registry import EXECUTORS
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import JOB_KINDS, MANAGED_MARKET_QUALITY


class EnsureMarketQualityJobTests(unittest.TestCase):
    def test_kind_is_registered_on_both_sides(self) -> None:
        """两张名单缺一不可:JOB_KINDS 管建、EXECUTORS 管跑。"""
        self.assertIn("data_quality", JOB_KINDS)
        self.assertIn("data_quality", EXECUTORS)

    def test_creates_enabled_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                plan = ensure_managed_market_quality_job(store)
                self.assertEqual(plan, {"created": 1, "updated": 0})
                job = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert job is not None
                self.assertEqual(job["kind"], "data_quality")
                self.assertEqual(job["cron"], MARKET_QUALITY_CRON)
                self.assertTrue(job["enabled"])

    def test_second_call_keeps_user_switch(self) -> None:
        """运维在页面上关掉之后,下次启动不能被 ensure 强行打开。"""
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                ensure_managed_market_quality_job(store)
                job = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert job is not None
                store.update_job(job["id"], enabled=False)

                plan = ensure_managed_market_quality_job(store)
                self.assertEqual(plan, {"created": 0, "updated": 1})
                again = store.get_job_by_name(MANAGED_MARKET_QUALITY)
                assert again is not None
                self.assertFalse(again["enabled"])


class ThresholdOverrideTests(unittest.TestCase):
    def test_config_overrides_apply(self) -> None:
        limits = _thresholds({"max_fabricated_rows": 7, "min_authoritative_ratio": 0.5})
        self.assertEqual(limits.max_fabricated_rows, 7)
        self.assertAlmostEqual(limits.min_authoritative_ratio, 0.5)

    def test_bad_config_falls_back_to_default_instead_of_crashing(self) -> None:
        """配置写错就不体检 = 最需要体检的时候正好没体检。"""
        from src.market import QualityThresholds

        limits = _thresholds({"max_fabricated_rows": "很多"})
        self.assertEqual(
            limits.max_fabricated_rows, QualityThresholds().max_fabricated_rows
        )

    def test_unknown_config_keys_are_ignored(self) -> None:
        limits = _thresholds({"不是阈值": 1})
        self.assertEqual(limits.lookback_days, 90)


if __name__ == "__main__":
    unittest.main()