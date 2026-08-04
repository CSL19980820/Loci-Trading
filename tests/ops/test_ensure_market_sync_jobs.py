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
                    plan["eod_cron"], f"{EOD_MINUTE} {EOD_HOUR} * * 1-5"
                )

                intraday = store.get_job_by_name(MANAGED_SYNC_INTRADAY)
                eod = store.get_job_by_name(MANAGED_SYNC_EOD)
                assert intraday is not None and eod is not None
                self.assertTrue(intraday["enabled"])
                self.assertTrue(eod["enabled"])
                self.assertTrue(intraday["config"].get("with_factors"))
                self.assertEqual(eod["config"]["mode"], "today_refresh")
                self.assertTrue(eod["config"].get("with_factors"))

                settings = store.get_setting("market_sync", {})
                self.assertEqual(
                    settings["eod_hour"], DEFAULT_MARKET_SYNC["eod_hour"]
                )

                again = ensure_managed_market_sync_jobs(store)
                self.assertEqual(again["created"], 0)
                self.assertEqual(again["updated"], 2)


if __name__ == "__main__":
    unittest.main()
