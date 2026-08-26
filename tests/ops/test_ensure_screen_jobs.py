"""托管选股绑定：默认 15:30；有声明时点的战法按自身 schedule 收敛。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ops.application.ensure_screen_jobs import (
    SCREEN_EOD_HOUR,
    SCREEN_EOD_MINUTE,
    ensure_managed_screen_jobs,
)
from src.ops.infrastructure.store import OpsStore
from src.strategy import all_strategies


class EnsureScreenJobsTests(unittest.TestCase):
    def test_binds_all_strategies_at_default_or_declared_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                plan = ensure_managed_screen_jobs(store)
                managed = [
                    engine
                    for engine in all_strategies()
                    if getattr(engine, "screen_managed_job", True)
                ]
                self.assertEqual(plan["cron"], "30 15 * * mon-fri")
                self.assertEqual(plan["total"], len(managed))
                self.assertGreaterEqual(plan["created"], 1)
                self.assertNotIn("qianlong-tail-v1", plan["slugs"])
                self.assertNotIn("rsi30-dip", plan["slugs"])
                self.assertNotIn("sanyuan-tail-1450", plan["slugs"])
                self.assertNotIn("yangshi-tail-1450", plan["slugs"])
                self.assertIsNone(store.get_job_by_name("screen:sanyuan-tail-1450"))
                self.assertIsNone(store.get_job_by_name("screen:yangshi-tail-1450"))
                for slug in plan["slugs"]:
                    job = store.get_job_by_name(f"screen:{slug}")
                    self.assertIsNotNone(job)
                    assert job is not None
                    self.assertTrue(job["enabled"])
                    cfg = job["config"]
                    self.assertEqual(cfg["schedule"]["mode"], "once")
                    if slug == "sanyuan-tail-v1":
                        self.assertEqual(job["cron"], "30 15 * * mon-fri")
                        self.assertEqual(cfg["schedule"]["run_hour"], SCREEN_EOD_HOUR)
                        self.assertEqual(cfg["schedule"]["run_minute"], SCREEN_EOD_MINUTE)
                        self.assertEqual(cfg["top_n"], 2)
                        self.assertEqual(cfg["hold_days"], 1)
                        self.assertIsNone(cfg["stop_loss_pct"])
                    elif slug == "yangshi-tail-v1":
                        self.assertEqual(job["cron"], "30 15 * * mon-fri")
                        self.assertEqual(cfg["schedule"]["run_hour"], SCREEN_EOD_HOUR)
                        self.assertEqual(cfg["schedule"]["run_minute"], SCREEN_EOD_MINUTE)
                        self.assertEqual(cfg["top_n"], 1)
                        self.assertEqual(cfg["hold_days"], 2)
                        self.assertFalse(cfg.get("force_spot_refresh"))
                    else:
                        self.assertEqual(job["cron"], "30 15 * * mon-fri")
                        self.assertEqual(cfg["schedule"]["run_hour"], SCREEN_EOD_HOUR)
                        self.assertEqual(cfg["schedule"]["run_minute"], SCREEN_EOD_MINUTE)
                        self.assertEqual(cfg["schedule"]["window_end_hour"], SCREEN_EOD_HOUR)
                        self.assertEqual(cfg["schedule"]["window_end_minute"], SCREEN_EOD_MINUTE)

                again = ensure_managed_screen_jobs(store)
                self.assertEqual(again["created"], 0)
                self.assertEqual(again["updated"], again["total"])

                sanyuan = store.get_job_by_name("screen:sanyuan-tail-v1")
                assert sanyuan is not None
                store.update_job(
                    sanyuan["id"],
                    config={**sanyuan["config"], "hold_days": 2},
                )
                ensure_managed_screen_jobs(store)
                converged = store.get_job_by_name("screen:sanyuan-tail-v1")
                assert converged is not None
                self.assertEqual(converged["config"]["hold_days"], 1)

    def test_sanyuan_job_reconverges_to_declared_schedule_and_top_n(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                ensure_managed_screen_jobs(store)
                job = store.get_job_by_name("screen:sanyuan-tail-v1")
                self.assertIsNotNone(job)
                assert job is not None
                store.update_job(
                    job["id"],
                    cron="0 16 * * 1-5",
                    config={
                        **job["config"],
                        "top_n": 5,
                        "schedule": {"mode": "once", "run_hour": 16, "run_minute": 0},
                    },
                )

                plan = ensure_managed_screen_jobs(store)
                updated = store.get_job_by_name("screen:sanyuan-tail-v1")
                self.assertEqual(plan["job_crons"]["sanyuan-tail-v1"], "30 15 * * mon-fri")
                self.assertIsNotNone(updated)
                assert updated is not None
                self.assertEqual(updated["cron"], "30 15 * * mon-fri")
                self.assertEqual(updated["config"]["top_n"], 2)
                self.assertEqual(updated["config"]["schedule"]["run_hour"], SCREEN_EOD_HOUR)
                self.assertEqual(updated["config"]["schedule"]["run_minute"], SCREEN_EOD_MINUTE)

    def test_yangshi_job_reconverges_to_eod_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                ensure_managed_screen_jobs(store)
                job = store.get_job_by_name("screen:yangshi-tail-v1")
                self.assertIsNotNone(job)
                assert job is not None
                store.update_job(
                    job["id"],
                    cron="50 14 * * 1-5",
                    config={
                        **job["config"],
                        "force_spot_refresh": True,
                        "schedule": {"mode": "once", "run_hour": 14, "run_minute": 50},
                    },
                )

                plan = ensure_managed_screen_jobs(store)
                updated = store.get_job_by_name("screen:yangshi-tail-v1")
                self.assertEqual(plan["job_crons"]["yangshi-tail-v1"], "30 15 * * mon-fri")
                self.assertIsNotNone(updated)
                assert updated is not None
                self.assertEqual(updated["cron"], "30 15 * * mon-fri")
                self.assertEqual(updated["config"]["schedule"]["run_hour"], SCREEN_EOD_HOUR)
                self.assertEqual(updated["config"]["schedule"]["run_minute"], SCREEN_EOD_MINUTE)
                self.assertFalse(updated["config"].get("force_spot_refresh"))

    def test_preserves_user_universe_and_custom_schedule_without_engine_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                ensure_managed_screen_jobs(store)
                # qianlong-close-v3 无 screen_schedule 声明，用户改的定时不应被托管对齐冲掉。
                job = store.get_job_by_name("screen:qianlong-close-v3")
                assert job is not None
                store.update_job(
                    job["id"],
                    cron="0 16 * * 1-5",
                    config={
                        **job["config"],
                        "universe": {
                            "preset": "custom",
                            "boards": ["main"],
                            "exclude_st": True,
                        },
                        "schedule": {
                            "mode": "once",
                            "run_hour": 16,
                            "run_minute": 0,
                            "interval_minutes": 10,
                            "window_start_hour": 9,
                            "window_start_minute": 30,
                            "window_end_hour": 16,
                            "window_end_minute": 0,
                        },
                    },
                )
                ensure_managed_screen_jobs(store)
                updated = store.get_job_by_name("screen:qianlong-close-v3")
                assert updated is not None
                self.assertEqual(updated["config"]["universe"]["boards"], ["main"])
                self.assertEqual(updated["config"]["schedule"]["run_hour"], 16)
                self.assertEqual(updated["config"]["schedule"]["run_minute"], 0)
                self.assertEqual(updated["cron"], "0 16 * * mon-fri")

                # 有固定时点的三源：只保留行情范围，时点仍回收敛到战法声明。
                sanyuan = store.get_job_by_name("screen:sanyuan-tail-v1")
                assert sanyuan is not None
                store.update_job(
                    sanyuan["id"],
                    config={
                        **sanyuan["config"],
                        "universe": {
                            "preset": "custom",
                            "boards": ["main"],
                            "exclude_st": True,
                        },
                    },
                )
                ensure_managed_screen_jobs(store)
                sanyuan2 = store.get_job_by_name("screen:sanyuan-tail-v1")
                assert sanyuan2 is not None
                self.assertEqual(sanyuan2["config"]["universe"]["boards"], ["main"])
                self.assertEqual(sanyuan2["config"]["schedule"]["run_hour"], SCREEN_EOD_HOUR)
                self.assertEqual(sanyuan2["cron"], "30 15 * * mon-fri")

    def test_1450_variant_jobs_are_purged_on_startup(self) -> None:
        """14:50 两档已连代码删除：旧库里残留的 screen:*-1450 定时必须被清掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                for slug in ("yangshi-tail-1450", "sanyuan-tail-1450"):
                    store.create_job(
                        name=f"screen:{slug}",
                        kind="screen",
                        cron="50 14 * * mon-fri",
                        config={"strategy": slug},
                        enabled=True,
                    )
                plan = ensure_managed_screen_jobs(store)
                self.assertIn("yangshi-tail-1450", plan["removed_slugs"])
                self.assertIn("sanyuan-tail-1450", plan["removed_slugs"])
                self.assertNotIn("yangshi-tail-1450", plan["slugs"])
                self.assertNotIn("sanyuan-tail-1450", plan["slugs"])
                self.assertIsNone(store.get_job_by_name("screen:yangshi-tail-1450"))
                self.assertIsNone(store.get_job_by_name("screen:sanyuan-tail-1450"))

    def test_removed_strategy_job_is_deleted_from_managed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                store.create_job(
                    name="screen:qianlong-tail-v1",
                    kind="screen",
                    cron="50 14 * * 1-5",
                    config={"strategy": "qianlong-tail-v1"},
                    enabled=True,
                )
                store.create_job(
                    name="screen:rsi30-dip",
                    kind="screen",
                    cron="30 15 * * 1-5",
                    config={"strategy": "rsi30-dip"},
                    enabled=True,
                )
                plan = ensure_managed_screen_jobs(store)
                self.assertIn("qianlong-tail-v1", plan["removed_slugs"])
                self.assertIn("rsi30-dip", plan["removed_slugs"])
                self.assertIsNone(store.get_job_by_name("screen:qianlong-tail-v1"))
                self.assertIsNone(store.get_job_by_name("screen:rsi30-dip"))


if __name__ == "__main__":
    unittest.main()
