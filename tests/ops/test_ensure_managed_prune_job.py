"""托管运维清理：首次创建，二次调用不改 enabled。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ops.application.ensure_managed_prune_job import (
    DEFAULT_PRUNE_CONFIG,
    PRUNE_CRON,
    ensure_managed_prune_job,
)
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import MANAGED_PRUNE


class EnsureManagedPruneJobTests(unittest.TestCase):
    def test_creates_enabled_job_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                plan = ensure_managed_prune_job(store)
                self.assertEqual(plan["created"], 1)
                self.assertEqual(plan["updated"], 0)

                job = store.get_job_by_name(MANAGED_PRUNE)
                assert job is not None
                self.assertEqual(job["kind"], "prune")
                self.assertEqual(job["cron"], PRUNE_CRON)
                self.assertTrue(job["enabled"])
                self.assertEqual(job["config"]["keep_per_job"], DEFAULT_PRUNE_CONFIG["keep_per_job"])
                self.assertEqual(
                    job["config"]["leader_role_keep_days"],
                    DEFAULT_PRUNE_CONFIG["leader_role_keep_days"],
                )

    def test_second_call_does_not_force_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                ensure_managed_prune_job(store)
                job = store.get_job_by_name(MANAGED_PRUNE)
                assert job is not None
                store.update_job(job["id"], enabled=False)

                again = ensure_managed_prune_job(store)
                self.assertEqual(again["created"], 0)
                self.assertEqual(again["updated"], 1)

                refreshed = store.get_job_by_name(MANAGED_PRUNE)
                assert refreshed is not None
                self.assertFalse(refreshed["enabled"])


if __name__ == "__main__":
    unittest.main()
