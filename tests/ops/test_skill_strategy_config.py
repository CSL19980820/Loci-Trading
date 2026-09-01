"""专属战法 Skill 配置：调度归系统，Skill 只声明信号。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.ops.infrastructure.store import OpsStore


class StrategySkillDetectionTests(unittest.TestCase):
    def test_detects_by_strategy_flag_or_signals(self) -> None:
        from src.ops.application.skill_strategy_config import (
            declared_signals,
            is_strategy_skill,
            signal_engine_of,
        )

        skill = {
            "slug": "dragon-return",
            "metadata": {
                "strategy_skill": True,
                "signal_engine": "dragon_return",
                "signals": ["buy_hint", "sell_hint"],
            },
        }
        self.assertTrue(is_strategy_skill(skill))
        self.assertEqual(signal_engine_of(skill), "dragon_return")
        self.assertEqual(declared_signals(skill), ["buy_hint", "sell_hint"])

    def test_plain_skill_is_not_a_strategy_skill(self) -> None:
        from src.ops.application.skill_strategy_config import is_strategy_skill

        self.assertFalse(is_strategy_skill({"slug": "notes", "metadata": {}}))

    def test_engine_falls_back_to_slug(self) -> None:
        from src.ops.application.skill_strategy_config import signal_engine_of

        self.assertEqual(
            signal_engine_of({"slug": "theme-leader-rotation", "metadata": {"signals": ["buy_hint"]}}),
            "theme-leader-rotation",
        )


class SkillStrategyConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.ops_path = f"{self.temp.name}/ops.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unbound_returns_system_defaults(self) -> None:
        from src.ops.application.skill_strategy_config import (
            DEFAULT_SCREEN_SCHEDULE,
            DEFAULT_WATCH_SCHEDULE,
            get_strategy_config,
        )

        with OpsStore(self.ops_path) as store:
            cfg = get_strategy_config(store, "dragon-return")

        self.assertFalse(cfg["screen_bound"])
        self.assertFalse(cfg["watch_bound"])
        self.assertEqual(cfg["screen_schedule_mode"], "off")
        self.assertEqual(cfg["screen_run_hour"], DEFAULT_SCREEN_SCHEDULE["run_hour"])
        self.assertEqual(cfg["screen_run_minute"], DEFAULT_SCREEN_SCHEDULE["run_minute"])
        self.assertEqual(
            cfg["watch_interval_minutes"], DEFAULT_WATCH_SCHEDULE["interval_minutes"]
        )

    def test_save_creates_screen_and_watch_jobs(self) -> None:
        from src.ops.api.schemas import SkillStrategyConfig
        from src.ops.application.skill_strategy_config import save_strategy_config

        payload = SkillStrategyConfig(
            provider="demo",
            screen_schedule_mode="once",
            screen_run_hour=15,
            screen_run_minute=40,
            watch_schedule_mode="interval",
            watch_interval_minutes=10,
        )
        with OpsStore(self.ops_path) as store:
            saved = save_strategy_config(store, "dragon-return", payload)
            screen = store.get_job_by_name("skill:dragon-return")
            watch = store.get_job_by_name("监测·龙回头")

        self.assertEqual(screen["kind"], "skill")
        self.assertEqual(watch["kind"], "skill_watch")
        self.assertEqual(watch["config"]["skill"], "dragon-return")
        self.assertEqual(screen["cron"], "40 15 * * mon-fri")
        self.assertEqual(watch["cron"], "*/10 9-14 * * mon-fri")
        self.assertEqual(watch["config"]["schedule"]["window_start_minute"], 20)
        self.assertEqual(len(watch["config"]["schedule"]["sessions"]), 2)
        self.assertTrue(saved["screen_bound"])
        self.assertTrue(saved["watch_bound"])
        self.assertEqual(saved["provider"], "demo")

    def test_turning_a_lane_off_deletes_that_job_only(self) -> None:
        from src.ops.api.schemas import SkillStrategyConfig
        from src.ops.application.skill_strategy_config import save_strategy_config

        with OpsStore(self.ops_path) as store:
            save_strategy_config(
                store,
                "dragon-return",
                SkillStrategyConfig(
                    provider="demo",
                    screen_schedule_mode="once",
                    watch_schedule_mode="interval",
                ),
            )
            saved = save_strategy_config(
                store,
                "dragon-return",
                SkillStrategyConfig(
                    provider="demo",
                    screen_schedule_mode="once",
                    watch_schedule_mode="off",
                ),
            )
            self.assertIsNotNone(store.get_job_by_name("skill:dragon-return"))
            self.assertIsNone(store.get_job_by_name("监测·龙回头"))
            self.assertIsNone(store.get_job_by_name("监测·dragon-return"))
        self.assertTrue(saved["screen_bound"])
        self.assertFalse(saved["watch_bound"])

    def test_enabling_without_provider_is_rejected(self) -> None:
        from src.ops.api.schemas import SkillStrategyConfig
        from src.ops.application.skill_strategy_config import save_strategy_config
        from src.ops.infrastructure.store import OpsError

        with OpsStore(self.ops_path) as store, self.assertRaisesRegex(OpsError, "LLM"):
            save_strategy_config(
                store,
                "dragon-return",
                SkillStrategyConfig(provider="", screen_schedule_mode="once"),
            )

    def test_deterministic_watch_without_provider_is_allowed(self) -> None:
        from src.ops.api.schemas import SkillStrategyConfig
        from src.ops.application.skill_strategy_config import save_strategy_config

        with OpsStore(self.ops_path) as store:
            saved = save_strategy_config(
                store,
                "dragon-return",
                SkillStrategyConfig(
                    provider="",
                    screen_schedule_mode="off",
                    watch_schedule_mode="interval",
                    watch_use_ai=False,
                ),
            )
            watch = store.get_job_by_name("监测·龙回头")

        self.assertTrue(saved["watch_bound"])
        self.assertFalse(saved["watch_use_ai"])
        self.assertEqual(watch["config"]["provider"], "")

    def test_save_renames_legacy_english_watch_job(self) -> None:
        from src.ops.api.schemas import SkillStrategyConfig
        from src.ops.application.skill_strategy_config import save_strategy_config

        with OpsStore(self.ops_path) as store:
            store.create_job(
                name="监测·dragon-return",
                kind="skill_watch",
                cron="*/10 9-14 * * 1-5",
                config={"skill": "dragon-return", "push_wecom": True},
                enabled=True,
            )
            save_strategy_config(
                store,
                "dragon-return",
                SkillStrategyConfig(
                    provider="",
                    screen_schedule_mode="off",
                    watch_schedule_mode="interval",
                ),
            )
            self.assertIsNone(store.get_job_by_name("监测·dragon-return"))
            watch = store.get_job_by_name("监测·龙回头")
            self.assertIsNotNone(watch)
            self.assertEqual(watch["config"]["skill"], "dragon-return")


def test_engine_registry_declares_watch_capabilities_and_push_policy() -> None:
    from src.ops.application.skill_strategy_config import default_watch_push_wecom
    from src.ops.application.skill_watch.engine_registry import (
        ENGINE_REGISTRY,
        engine_spec,
        engine_target,
        eod_rescan_skill_for,
    )

    dragon = engine_spec("dragon-return")
    leader = engine_spec("market-leader-map")
    assert dragon is not None and leader is not None
    assert dragon.needs_market_store and dragon.uses_market_gate
    assert dragon.emits_observe and dragon.eod_rescan
    assert leader.needs_market_store and leader.uses_market_gate
    assert not leader.eod_rescan
    assert eod_rescan_skill_for("market-leader-map") == "dragon-return"
    assert eod_rescan_skill_for("dragon-return") == "dragon-return"
    assert eod_rescan_skill_for("limit-up-momentum") is None
    assert engine_target("dragon-return") == "dragon_return:scan_dragon_return"
    assert "dragon-return" in ENGINE_REGISTRY
    assert default_watch_push_wecom("dragon-return") is True

    # 龙池已退役：注册表不得再有它，否则残留任务会被重新调度
    assert engine_spec("dragon-pool") is None
    assert engine_target("dragon-pool") is None
    assert "dragon-pool" not in ENGINE_REGISTRY
    assert default_watch_push_wecom("market-leader-map") is False
    assert default_watch_push_wecom("limit-up-momentum") is False
    assert default_watch_push_wecom("theme-leader-rotation") is False


def test_satellite_skill_watch_never_pushes(tmp_path: Path) -> None:
    from src.ops.application.jobs.notify import _maybe_push_wecom

    with OpsStore(tmp_path / "ops.db") as store:
        job = {
            "id": "JOB-x",
            "name": "监测·龙头地图",
            "kind": "skill_watch",
            "config": {"skill": "market-leader-map", "push_wecom": True},
        }
        with patch("src.ops.application.notify_dispatch.dispatch_text") as dispatch:
            outcome = _maybe_push_wecom(
                store=store,
                job=job,
                status="success",
                result={"slug": "market-leader-map", "summary": "🛑空仓"},
            )

    assert outcome == {
        "push_skipped": True,
        "reason": "satellite_watch_no_push",
        "slug": "market-leader-map",
    }
    dispatch.assert_not_called()
