from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.api.skills import build_skills_router
from src.ops.application import skill_runs
from src.ops.application.jobs import JobContext, JobError
from src.ops.application.skill_runtime import drive_skill_run
from src.ops.infrastructure.store import OpsError


class SkillRunClaimTests(unittest.TestCase):
    def test_waiting_user_reply_is_claimed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(skill_runs, "skill_runs_dir", return_value=root):
                state = skill_runs.create_run(skill="demo", provider="local")
                state["status"] = "waiting_user"
                state["pending_ask"] = {"prompt": "继续吗？"}
                skill_runs.save_run(state)

                with ThreadPoolExecutor(max_workers=2) as executor:
                    claimed = list(
                        executor.map(
                            lambda _: skill_runs.claim_user_reply(state["id"], "继续"),
                            range(2),
                        )
                    )

                self.assertEqual(sum(item is not None for item in claimed), 1)
                current = skill_runs.load_run(state["id"])
                self.assertIsNotNone(current)
                self.assertEqual(current["status"], "running")
                events = skill_runs.list_events(state["id"])
                self.assertEqual(
                    [event["type"] for event in events].count("user_reply"),
                    1,
                )


class SkillRunLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skill-runs"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _assert_errored(self, run_id: str, message: str) -> None:
        current = skill_runs.load_run(run_id)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current["status"], "error")
        self.assertIn(message, current["error"])
        events = skill_runs.list_events(run_id)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn(message, events[-1]["message"])

    def test_missing_store_preflight_is_persisted_as_error(self) -> None:
        with patch.object(skill_runs, "skill_runs_dir", return_value=self.root):
            state = skill_runs.create_run(skill="demo", provider="provider")

            with self.assertRaisesRegex(JobError, "缺少运维库连接"):
                drive_skill_run(state["id"], context=JobContext())

            self._assert_errored(state["id"], "缺少运维库连接")

    def test_missing_skill_preflight_is_persisted_as_error(self) -> None:
        with patch.object(skill_runs, "skill_runs_dir", return_value=self.root):
            state = skill_runs.create_run(skill="missing", provider="provider")

            with patch("src.ops.application.skills.resolve_skill", return_value=None):
                with self.assertRaisesRegex(JobError, "未安装的技能"):
                    drive_skill_run(state["id"], context=JobContext(ops_store=object()))

            self._assert_errored(state["id"], "未安装的技能")

    def test_sync_api_provider_preflight_is_error_and_returns_422(self) -> None:
        app = FastAPI()
        app.include_router(
            build_skills_router(
                write_dependency=lambda: None,
                ops_db=str(Path(self.temp.name) / "ops.db"),
            )
        )
        skill = {"slug": "demo", "enabled": True}

        with (
            patch.object(skill_runs, "skill_runs_dir", return_value=self.root),
            patch("src.ops.application.skills.resolve_skill", return_value=skill),
            patch("src.ai.resolve_config", side_effect=OpsError("未配置的供应商：missing")),
            patch.object(skill_runs, "new_run_id", return_value="SR-preflight"),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/skills/demo/runs",
                    json={"provider": "missing", "background": False},
                )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], "未配置的供应商：missing")
            self._assert_errored("SR-preflight", "未配置的供应商：missing")


if __name__ == "__main__":
    unittest.main()
