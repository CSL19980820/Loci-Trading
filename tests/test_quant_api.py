from __future__ import annotations

import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from src.palace_api import create_app

SKILL_MANIFEST = """---
name: 测试技能
slug: test-skill
version: 0.1.0
description: 用于接口测试
schedule: "0 16 * * 1-5"
---

请按步骤执行。
"""


def _skill_zip(extra: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_MANIFEST)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


class QuantApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        # 让 router 用临时库，不碰工作区里的真实数据。
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        app = create_app(base / "palace.db", base / "no-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    # ---- 能力探测 -------------------------------------------------

    def test_capabilities_reports_what_is_available(self) -> None:
        body = self.client.get("/api/capabilities").json()
        for key in ("market", "strategies", "backtest", "skills", "scheduler", "llm"):
            self.assertIn(key, body)
        self.assertIsInstance(body["missing"], list)

    # ---- 策略 -----------------------------------------------------

    def test_lists_registered_strategies_with_entry_timing(self) -> None:
        """入场时点必须出现在接口里：前端和回测都要靠它才知道怎么用信号。"""
        items = self.client.get("/api/strategies").json()
        slugs = {item["slug"] for item in items}
        self.assertIn("qianlong-auction", slugs)
        for item in items:
            self.assertIn(item["entry_timing"], ("open", "next_open"))
            self.assertIn("params", item)

    def test_screen_on_empty_market_reports_clearly(self) -> None:
        """行情仓是空的时候要给可读的 422，而不是 500。"""
        response = self.client.post(
            "/api/strategies/screen", json={"strategy": "qianlong-auction"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("行情", response.json()["detail"])

    def test_unknown_strategy_is_422(self) -> None:
        response = self.client.post("/api/strategies/screen", json={"strategy": "nope"})
        self.assertEqual(response.status_code, 422)

    def test_extra_field_is_rejected(self) -> None:
        """与账本写入同样的严格校验：多字段就 422，不静默忽略。"""
        response = self.client.post(
            "/api/strategies/screen",
            json={"strategy": "qianlong-auction", "unknown": 1},
        )
        self.assertEqual(response.status_code, 422)

    def test_backtest_validates_ranges(self) -> None:
        for payload, field in (
            ({"strategy": "x", "hold_days": 0}, "hold_days"),
            ({"strategy": "x", "stop_loss_pct": 5.0}, "stop_loss_pct"),
            ({"strategy": "x", "benchmark": "abc"}, "benchmark"),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.client.post("/api/backtest", json=payload).status_code, 422)

    # ---- 技能包 ---------------------------------------------------

    def test_install_list_and_remove_skill(self) -> None:
        response = self.client.post(
            "/api/skills", files={"file": ("skill.zip", _skill_zip(), "application/zip")}
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["slug"], "test-skill")
        self.assertEqual(body["default_cron"], "0 16 * * 1-5")
        # 列表接口不该把完整指令正文吐出来，那可能很长。
        self.assertNotIn("instructions", body)

        listed = self.client.get("/api/skills").json()
        self.assertEqual([item["slug"] for item in listed], ["test-skill"])

        detail = self.client.get("/api/skills/test-skill").json()
        self.assertIn("请按步骤执行", detail["instructions"])

        self.assertEqual(self.client.delete("/api/skills/test-skill").status_code, 200)
        self.assertEqual(self.client.get("/api/skills").json(), [])

    def test_rejects_non_zip_upload(self) -> None:
        response = self.client.post(
            "/api/skills", files={"file": ("evil.sh", b"rm -rf /", "text/plain")}
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_zip_slip_through_the_api(self) -> None:
        """安全检查必须在 HTTP 这一层也生效，不能只在 CLI 上把关。"""
        payload = _skill_zip({"../../evil.md": "pwned"})
        response = self.client.post(
            "/api/skills", files={"file": ("skill.zip", payload, "application/zip")}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Zip Slip", response.json()["detail"])

    def test_missing_skill_is_404(self) -> None:
        self.assertEqual(self.client.get("/api/skills/nope").status_code, 404)
        self.assertEqual(self.client.delete("/api/skills/nope").status_code, 404)

    # ---- 任务 -----------------------------------------------------

    def test_job_lifecycle(self) -> None:
        created = self.client.post(
            "/api/jobs",
            json={
                "name": "盘后同步", "kind": "sync", "cron": "35 15 * * 1-5",
                "config": {"limit": 100},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        job_id = created.json()["id"]
        self.assertEqual(created.json()["config"]["limit"], 100)

        patched = self.client.patch(f"/api/jobs/{job_id}", json={"enabled": False})
        self.assertEqual(patched.status_code, 200)
        self.assertFalse(patched.json()["enabled"])

        self.assertEqual(len(self.client.get("/api/jobs").json()), 1)
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/jobs").json(), [])

    def test_invalid_cron_is_rejected_at_creation(self) -> None:
        """写错的 cron 必须当场拒绝，不能等到它安静地永不触发。"""
        response = self.client.post(
            "/api/jobs", json={"name": "bad", "kind": "sync", "cron": "35 15 * *"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("5 个字段", response.json()["detail"])

    def test_duplicate_job_name_is_422(self) -> None:
        payload = {"name": "dup", "kind": "sync"}
        self.assertEqual(self.client.post("/api/jobs", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/api/jobs", json=payload).status_code, 422)

    def test_unknown_job_kind_is_rejected_by_schema(self) -> None:
        response = self.client.post("/api/jobs", json={"name": "x", "kind": "mystery"})
        self.assertEqual(response.status_code, 422)

    def test_running_a_failing_job_records_it_instead_of_500(self) -> None:
        """任务失败是业务结果，不是服务器错误。"""
        created = self.client.post(
            "/api/jobs", json={"name": "s", "kind": "skill", "config": {}}
        ).json()
        outcome = self.client.post(f"/api/jobs/{created['id']}/run")
        self.assertEqual(outcome.status_code, 200)
        self.assertEqual(outcome.json()["status"], "failed")

        runs = self.client.get("/api/jobs/runs").json()
        self.assertEqual(runs[0]["status"], "failed")
        self.assertTrue(runs[0]["error_text"])

    def test_missing_job_run_is_404(self) -> None:
        self.assertEqual(self.client.post("/api/jobs/JOB-nope/run").status_code, 404)

    def test_schedule_status_is_reported_even_when_disabled(self) -> None:
        """"我的定时任务到底装上没有"必须能直接问出来，而不是等到点看结果。"""
        body = self.client.get("/api/jobs/schedule").json()
        self.assertFalse(body["running"])
        self.assertIn("reason", body)

    # ---- 供应商 ---------------------------------------------------

    def test_provider_list_starts_empty(self) -> None:
        self.assertEqual(self.client.get("/api/providers").json(), [])

    def test_provider_requires_valid_base_url(self) -> None:
        response = self.client.post(
            "/api/providers",
            json={"name": "p", "base_url": "not-a-url", "api_key": "sk-x",
                  "validate_key": False, "discover_models": False},
        )
        self.assertEqual(response.status_code, 422)

    def test_provider_without_master_key_fails_cleanly(self) -> None:
        """没配主密钥就存 Key，必须给出可操作的提示而不是 500。"""
        import os

        os.environ.pop("PALACE_AI_MASTER_KEY", None)
        response = self.client.post(
            "/api/providers",
            json={"name": "p", "base_url": "https://example.com/v1", "api_key": "sk-x",
                  "validate_key": False, "discover_models": False},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("PALACE_AI_MASTER_KEY", response.json()["detail"])

    def test_provider_round_trip_never_exposes_the_key(self) -> None:
        import os

        from src.ai.crypto import generate_master_key

        os.environ["PALACE_AI_MASTER_KEY"] = generate_master_key()
        try:
            created = self.client.post(
                "/api/providers",
                json={
                    "name": "openrouter", "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-super-secret-1234", "model": "some/model",
                    "validate_key": False, "discover_models": False,
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            body = created.json()
            self.assertEqual(body["key_last4"], "****1234")
            self.assertNotIn("encrypted_key", body)
            self.assertNotIn("sk-super-secret", created.text)

            listed = self.client.get("/api/providers")
            self.assertNotIn("sk-super-secret", listed.text)
            self.assertTrue(listed.json()[0]["has_key"])

            self.assertEqual(self.client.delete("/api/providers/openrouter").status_code, 200)
        finally:
            os.environ.pop("PALACE_AI_MASTER_KEY", None)

    def test_deleting_unknown_provider_is_404(self) -> None:
        self.assertEqual(self.client.delete("/api/providers/nope").status_code, 404)


class ProductionAuthTests(unittest.TestCase):
    """新增的写接口必须和账本写入走同一道门，不能开旁路。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        app = create_app(
            base / "palace.db", base / "no-static",
            environment="production", allowed_hosts=["testserver"],
            write_token="test-token", auth_username="admin",
            auth_password="pw", session_secret="secret",
        )
        self.client = TestClient(app, base_url="https://testserver")

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_write_endpoints_reject_anonymous_callers(self) -> None:
        for method, path, kwargs in (
            ("post", "/api/jobs", {"json": {"name": "x", "kind": "sync"}}),
            ("post", "/api/skills", {"files": {"file": ("s.zip", _skill_zip(), "application/zip")}}),
            ("post", "/api/market/sync", {"json": {}}),
            ("delete", "/api/providers/x", {}),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 401, f"{path} 未鉴权就放行了")

    def test_agent_bearer_token_is_accepted(self) -> None:
        response = self.client.post(
            "/api/jobs",
            json={"name": "x", "kind": "sync"},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_read_endpoints_also_require_auth_in_production(self) -> None:
        self.assertEqual(self.client.get("/api/strategies").status_code, 401)
        self.assertEqual(self.client.get("/api/capabilities").status_code, 401)


if __name__ == "__main__":
    unittest.main()


class AnalysisEndpointTests(unittest.TestCase):
    """横向对比与退出扫描是分钟级任务，必须异步——同步返回会被网关掐断。

    这里只验接口契约，不真跑分析：真跑一轮要几十秒，且后台线程会持着
    SQLite 连接，临时目录清不掉。用 patch 把执行本身换成空操作。
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        self.client = TestClient(create_app(base / "palace.db", base / "no-static"))
        self._patch = patch("src.ops.run_job", return_value={"status": "success"})
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.client.close()
        # 后台线程会持着 SQLite 连接；不等它收工，Windows 上删不掉临时目录。
        for thread in threading.enumerate():
            if thread.name.startswith("analysis-"):
                thread.join(timeout=10)
        self.temp.cleanup()

    def test_returns_202_with_a_pollable_job_id(self) -> None:
        response = self.client.post("/api/analysis/compare", json={"holds": [1]})
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertTrue(body["job_id"])
        self.assertIn("job_id=", body["poll"])

    def test_optimize_requires_a_strategy(self) -> None:
        response = self.client.post("/api/analysis/optimize", json={"holds": [1]})
        self.assertEqual(response.status_code, 422)
        self.assertIn("strategy", response.json()["detail"])

    def test_unknown_kind_is_rejected_by_the_path_schema(self) -> None:
        self.assertEqual(self.client.post("/api/analysis/mystery", json={}).status_code, 422)

    def test_extra_field_is_rejected(self) -> None:
        response = self.client.post("/api/analysis/compare", json={"nope": 1})
        self.assertEqual(response.status_code, 422)

    def test_repeated_triggers_reuse_one_job_record(self) -> None:
        """一次性分析不该在任务表里积累一堆同类型僵尸任务。"""
        first = self.client.post("/api/analysis/compare", json={"holds": [1]}).json()
        second = self.client.post("/api/analysis/compare", json={"holds": [3]}).json()
        self.assertEqual(first["job_id"], second["job_id"])

    def test_analysis_job_is_created_disabled(self) -> None:
        """即时分析不该被调度器捡去定时跑。"""
        body = self.client.post("/api/analysis/compare", json={"holds": [1]}).json()
        jobs = {job["id"]: job for job in self.client.get("/api/jobs").json()}
        self.assertFalse(jobs[body["job_id"]]["enabled"])
        self.assertEqual(jobs[body["job_id"]]["cron"], "")
