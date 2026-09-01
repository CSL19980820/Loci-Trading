"""托管价格提醒扫描：有规则才挂、幂等、不夺用户开关。

`alert_scan` 是 EXECUTORS 里唯一「有执行器、有 HTTP、有整套冷却/日上限字段，
却没有任何代码给它建过定时任务」的 kind——规则存进去只有人手点扫描才命中。
反过来，一条规则都没有的机器也不该被塞一条每 5 分钟空跑的托管任务。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ops.application.ensure_alert_scan_job import (
    ALERT_SCAN_CRON,
    MANAGED_ALERT_SCAN,
    ensure_managed_alert_scan_job,
)
from src.ops.application.ensure_managed_jobs import ensure_all_managed_jobs
from src.ops.application.jobs.registry import EXECUTORS
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_helpers import JOB_KINDS


def _add_rule(store: OpsStore, *, enabled: bool = True) -> dict:
    return store.upsert_alert_rule(
        {
            "code": "600519",
            "name": "茅台上破",
            "enabled": enabled,
            "condition_group": {
                "op": "and",
                "conditions": [{"type": "price", "op": ">=", "value": 2000}],
            },
        }
    )


class EnsureAlertScanJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(str(Path(self.temp.name) / "ops.db"))

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_kind_is_registered_on_both_sides(self) -> None:
        """两张名单缺一不可：JOB_KINDS 管建、EXECUTORS 管跑。"""
        self.assertIn("alert_scan", JOB_KINDS)
        self.assertIn("alert_scan", EXECUTORS)

    def test_no_rules_creates_nothing(self) -> None:
        """没人用价格提醒的机器不该多一条每 5 分钟空跑的任务。"""
        plan = ensure_managed_alert_scan_job(self.store)
        self.assertEqual(plan["skipped"], "no_alert_rules")
        self.assertEqual(plan["created"], 0)
        self.assertIsNone(self.store.get_job_by_name(MANAGED_ALERT_SCAN))

    def test_disabled_rules_do_not_count(self) -> None:
        _add_rule(self.store, enabled=False)
        plan = ensure_managed_alert_scan_job(self.store)
        self.assertEqual(plan["skipped"], "no_alert_rules")
        self.assertIsNone(self.store.get_job_by_name(MANAGED_ALERT_SCAN))

    def test_creates_job_once_a_rule_exists(self) -> None:
        _add_rule(self.store)
        plan = ensure_managed_alert_scan_job(self.store)
        self.assertEqual(plan, {"created": 1, "updated": 0})

        job = self.store.get_job_by_name(MANAGED_ALERT_SCAN)
        assert job is not None
        self.assertEqual(job["kind"], "alert_scan")
        self.assertEqual(job["cron"], ALERT_SCAN_CRON)
        self.assertTrue(job["enabled"])
        self.assertFalse(job["config"]["dry_run"])

        # cron 必须能被调度器接受，且是 mon-fri（数字 1-5 会整周跳过周一）
        from src.ops.infrastructure.scheduler import validate_cron

        validate_cron(job["cron"])
        self.assertIn("mon-fri", job["cron"])

    def test_second_call_is_idempotent(self) -> None:
        _add_rule(self.store)
        ensure_managed_alert_scan_job(self.store)
        plan = ensure_managed_alert_scan_job(self.store)
        self.assertEqual(plan, {"created": 0, "updated": 1})
        jobs = [
            j for j in self.store.list_jobs() if j["kind"] == "alert_scan"
        ]
        self.assertEqual(len(jobs), 1)

    def test_keeps_user_switch_and_cron(self) -> None:
        """运维页关掉 / 改过频率之后，下次启动不能被 ensure 还原。"""
        _add_rule(self.store)
        ensure_managed_alert_scan_job(self.store)
        job = self.store.get_job_by_name(MANAGED_ALERT_SCAN)
        assert job is not None
        self.store.update_job(
            job["id"],
            enabled=False,
            cron="*/15 9-14 * * mon-fri",
            config={"dry_run": True},
        )

        ensure_managed_alert_scan_job(self.store)

        after = self.store.get_job_by_name(MANAGED_ALERT_SCAN)
        assert after is not None
        self.assertFalse(after["enabled"], "用户关掉的扫描不能被重启复活")
        self.assertEqual(after["cron"], "*/15 9-14 * * mon-fri")
        self.assertTrue(after["config"]["dry_run"])

    def test_existing_job_survives_rules_being_deleted(self) -> None:
        """规则清空只是暂时的；删任务会把用户调过的 cron 一起弄丢。"""
        rule = _add_rule(self.store)
        ensure_managed_alert_scan_job(self.store)
        self.store.delete_alert_rule(rule["id"])

        plan = ensure_managed_alert_scan_job(self.store)

        self.assertEqual(plan, {"created": 0, "updated": 1})
        self.assertIsNotNone(self.store.get_job_by_name(MANAGED_ALERT_SCAN))

    def test_store_without_alert_table_is_not_fatal(self) -> None:
        """收 Any 的 ensure 不该被没有这张表的适配器带崩。"""

        class _Bare:
            def get_job_by_name(self, name: str):
                return None

        plan = ensure_managed_alert_scan_job(_Bare())
        self.assertEqual(plan["skipped"], "no_alert_rules")


class EnsureAllManagedJobsWiringTests(unittest.TestCase):
    """写了 ensure 函数却没挂进 ensure_all_managed_jobs = 白写。"""

    def test_alert_scan_is_mounted_in_startup_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                _add_rule(store)
                ensure_all_managed_jobs(store)

                job = store.get_job_by_name(MANAGED_ALERT_SCAN)
                assert job is not None
                self.assertEqual(job["kind"], "alert_scan")
                self.assertEqual(job["cron"], ALERT_SCAN_CRON)

    def test_startup_without_rules_mounts_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                ensure_all_managed_jobs(store)
                self.assertIsNone(store.get_job_by_name(MANAGED_ALERT_SCAN))

    def test_one_failing_step_does_not_skip_the_rest(self) -> None:
        """候选跟踪原先裸调在保护外：它一炸，后面所有托管任务都不会被确保。"""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            with OpsStore(str(Path(tmp) / "ops.db")) as store:
                with patch.object(
                    OpsStore,
                    "ensure_managed_outcome_job",
                    side_effect=RuntimeError("boom"),
                ):
                    ensure_all_managed_jobs(store)

                from src.ops.infrastructure.store_helpers import (
                    MANAGED_PRUNE,
                    MANAGED_SYNC_EOD,
                )

                self.assertIsNotNone(store.get_job_by_name(MANAGED_SYNC_EOD))
                self.assertIsNotNone(store.get_job_by_name(MANAGED_PRUNE))


if __name__ == "__main__":
    unittest.main()
