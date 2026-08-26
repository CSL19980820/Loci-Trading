"""托管行情同步：首次默认开启盘中+日终，日终带 with_factors。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ops.application.ensure_market_sync_jobs import (
    DEFAULT_MARKET_SYNC,
    EOD_HOUR,
    EOD_MINUTE,
    ensure_managed_market_sync_jobs,
)
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import MANAGED_SYNC_EOD, MANAGED_SYNC_INTRADAY


class EnsureMarketSyncJobsTests(unittest.TestCase):
    def test_creates_enabled_jobs_with_factors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                plan = ensure_managed_market_sync_jobs(store)
                self.assertEqual(plan["created"], 2)
                self.assertTrue(plan["enabled_intraday"])
                self.assertTrue(plan["enabled_eod"])
                self.assertEqual(
                    plan["eod_cron"], f"{EOD_MINUTE} {EOD_HOUR} * * mon-fri"
                )

                intraday = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
                eod = store.get_job_by_name(MANAGED_SYNC_EOD)
                assert intraday is not None and eod is not None
                self.assertTrue(intraday["enabled"])
                self.assertTrue(eod["enabled"])
                self.assertTrue(intraday["config"].get("with_factors"))
                self.assertTrue(intraday["config"].get("refresh_instruments_daily"))
                self.assertEqual(eod["config"]["mode"], "today_refresh")
                self.assertTrue(eod["config"].get("with_factors"))
                self.assertTrue(eod["config"].get("refresh_instruments_daily"))

                settings = store.get_setting("market_sync", {})
                self.assertEqual(
                    settings["eod_hour"], DEFAULT_MARKET_SYNC["eod_hour"]
                )
                self.assertEqual(
                    settings["eod_minute"], DEFAULT_MARKET_SYNC["eod_minute"]
                )

                again = ensure_managed_market_sync_jobs(store)
                self.assertEqual(again["created"], 0)
                self.assertEqual(again["updated"], 2)

    def test_legacy_force_is_not_carried_over(self) -> None:
        """遗留 force=true 会让盘中增量每 5 分钟重拉全历史，托管键必须复位。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                ensure_managed_market_sync_jobs(store)
                intraday = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
                eod = store.get_job_by_name(MANAGED_SYNC_EOD)
                assert intraday is not None and eod is not None
                store.update_job(
                    intraday["id"],
                    config={**intraday["config"], "force": True, "workers": 8},
                )
                store.update_job(
                    eod["id"], config={**eod["config"], "force": True, "mode": "full"}
                )

                ensure_managed_market_sync_jobs(store)

                intraday = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
                eod = store.get_job_by_name(MANAGED_SYNC_EOD)
                assert intraday is not None and eod is not None
                self.assertFalse(intraday["config"].get("force"))
                self.assertEqual(intraday["config"]["mode"], "full")
                self.assertFalse(eod["config"].get("force"))
                self.assertEqual(eod["config"]["mode"], "today_refresh")
                # 非托管键仍尊重用户改动
                self.assertEqual(intraday["config"]["workers"], 8)


if __name__ == "__main__":
    unittest.main()
