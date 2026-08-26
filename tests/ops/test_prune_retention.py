"""prune 保留策略：不许删掉正在跑的运行槽，也不许把历史清空。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ops.application.jobs import JobContext
from src.ops.application.jobs.prune import execute_prune
from src.ops.infrastructure.store import OpsStore


class PruneRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(str(Path(self.temp.name) / "ops.db"))
        self.job_id = self.store.create_job(name="同步", kind="sync")
        self.job = self.store.get_job(self.job_id)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _finished_runs(self, count: int) -> list[str]:
        ids: list[str] = []
        for _ in range(count):
            run_id = self.store.start_run(self.job, trigger="manual")
            self.store.finish_run(run_id, status="success", result={}, duration_ms=1)
            ids.append(run_id)
        return ids

    def test_running_run_survives_prune(self) -> None:
        running = self.store.start_run(self.job, trigger="manual")
        self._finished_runs(3)

        removed = self.store.prune_runs(keep_per_job=1)

        self.assertGreater(removed, 0)
        alive = self.store.get_run(running)
        assert alive is not None
        self.assertEqual(alive["status"], "running")
        # 运行槽还在，任务收尾才不会撞 "任务运行不存在或已被删除"
        self.store.finish_run(running, status="success", result={}, duration_ms=1)

    def test_keep_zero_still_leaves_latest_run(self) -> None:
        self._finished_runs(3)

        self.store.prune_runs(keep_per_job=0)

        self.assertEqual(len(self.store.list_runs(job_id=self.job_id)), 1)

    def test_execute_prune_clamps_keep_and_reports_applied_value(self) -> None:
        self._finished_runs(3)
        context = JobContext(ops_store=self.store)

        payload = execute_prune({"keep_per_job": 0, "leader_role_keep_days": 0}, context)

        self.assertEqual(payload["keep_per_job"], 1)
        self.assertEqual(payload["removed"], 2)
        self.assertEqual(len(self.store.list_runs(job_id=self.job_id)), 1)


if __name__ == "__main__":
    unittest.main()
