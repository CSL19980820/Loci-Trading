"""托管任务的幂等确保不得覆盖用户在运维页改过的开关 / cron / 配置。

`ensure_all_managed_jobs` 每次应用启动都会跑一遍。若它强行回写默认值，
用户关掉的任务会在下次重启自己复活，改过的参数会被静默还原。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ops.application.ensure_intel_jobs import (
    MANAGED_INTEL_INTRADAY,
    MANAGED_INTEL_OPEN,
    ensure_managed_intel_jobs,
)
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import MANAGED_OUTCOME_TRACK


class ManagedJobSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(str(Path(self.temp.name) / "ops.db"))

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_intel_jobs_keep_user_switch_and_cron(self) -> None:
        created = ensure_managed_intel_jobs(self.store)
        self.assertEqual(len(created["created"]), 3)

        job = self.store.get_job_by_name(MANAGED_INTEL_INTRADAY)
        assert job is not None
        self.store.update_job(
            job["id"],
            enabled=False,
            cron="*/30 9-14 * * mon-fri",
            config={**job["config"], "theme_top_n": 60},
        )

        ensure_managed_intel_jobs(self.store)

        after = self.store.get_job_by_name(MANAGED_INTEL_INTRADAY)
        assert after is not None
        self.assertFalse(after["enabled"], "用户关掉的情报任务不能被重启复活")
        self.assertEqual(after["cron"], "*/30 9-14 * * mon-fri")
        self.assertEqual(after["config"]["theme_top_n"], 60)
        # 托管键仍会补齐
        self.assertEqual(after["config"]["phase"], "intraday")
        self.assertEqual(after["config"]["server"], "wudao")

        untouched = self.store.get_job_by_name(MANAGED_INTEL_OPEN)
        assert untouched is not None
        self.assertTrue(untouched["enabled"])

    def test_outcome_job_keeps_user_tuned_config(self) -> None:
        job_id = self.store.ensure_managed_outcome_job()
        self.store.update_job(job_id, config={"limit": 50, "max_age_trading_days": 20})

        self.store.ensure_managed_outcome_job()

        job = self.store.get_job(job_id)
        assert job is not None
        self.assertEqual(job["config"]["limit"], 50)
        self.assertEqual(job["config"]["max_age_trading_days"], 20)
        # 缺失的托管键补齐，不整体覆盖
        self.assertEqual(job["config"]["benchmark"], "000300")

    def test_outcome_job_keeps_user_switch_off(self) -> None:
        job_id = self.store.ensure_managed_outcome_job()
        self.store.update_job(job_id, enabled=False)

        self.store.ensure_managed_outcome_job()

        job = self.store.get_job(job_id)
        assert job is not None
        self.assertFalse(job["enabled"])
        self.assertEqual(job["name"], MANAGED_OUTCOME_TRACK)


if __name__ == "__main__":
    unittest.main()
