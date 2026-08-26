from __future__ import annotations

import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.app.main import create_app

SKILL_MANIFEST = """---
name: 测试技能
slug: test-skill
version: 0.1.0
description: 用于接口测试
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



class QuantApiJobsAndProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        # 让 router 用临时库，不碰工作区里的真实数据。
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ["PALACE_SKILL_ROOT"] = str(base / "skills")
        (base / "skills").mkdir(parents=True, exist_ok=True)
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        app = create_app(base / "palace.db", base / "no-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()


    def test_universe_stats_endpoint(self) -> None:
        response = self.client.get("/api/universe/stats")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["bse_blocked"])
        self.assertIn("by_board", body)

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
        self.assertNotIn("default_cron", body)
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
        before = {job["id"] for job in self.client.get("/api/jobs").json()}
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

        after_create = {job["id"] for job in self.client.get("/api/jobs").json()}
        self.assertIn(job_id, after_create)
        self.assertEqual(len(after_create - before), 1)
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}").status_code, 200)
        after_delete = {job["id"] for job in self.client.get("/api/jobs").json()}
        self.assertNotIn(job_id, after_delete)
        self.assertEqual(after_delete, before)

    def test_wecom_settings_validation_and_market_sync_upsert(self) -> None:
        bad = self.client.put("/api/ops/settings/wecom", json={"url": "http://evil.example/x"})
        self.assertEqual(bad.status_code, 422)

        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef1234567890"
        saved = self.client.put("/api/ops/settings/wecom", json={"url": url})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()["configured"])
        self.assertIn("****7890", saved.json()["url_masked"])

        got = self.client.get("/api/ops/settings/wecom")
        self.assertTrue(got.json()["configured"])
        self.assertIn("screen_template", got.json())
        self.assertEqual(got.json()["screen_template"]["preset"], "default")

        tpl = self.client.put(
            "/api/ops/settings/wecom",
            json={
                "screen_template": {
                    "preset": "compact",
                    "quant_tag": "量化",
                    "skills_tag": "skills",
                    "max_picks": 10,
                }
            },
        )
        self.assertEqual(tpl.status_code, 200, tpl.text)
        self.assertEqual(tpl.json()["screen_template"]["preset"], "compact")
        self.assertNotIn("选股如下", tpl.json()["preview"])

        sync = self.client.put(
            "/api/ops/market-sync",
            json={
                "enabled_intraday": True,
                "interval_minutes": 5,
                "enabled_eod": True,
                "eod_hour": 16,
                "eod_minute": 0,
                "workers": 4,
                "push_wecom_on_fail": False,
            },
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        body = sync.json()
        self.assertTrue(body["enabled_intraday"])
        self.assertEqual(body["interval_minutes"], 5)
        jobs = {job["name"]: job for job in self.client.get("/api/jobs").json()}
        self.assertIn("行情盘中增量", jobs)
        self.assertIn("行情日终重刷", jobs)
        self.assertEqual(jobs["行情盘中增量"]["cron"], "*/5 9-14 * * mon-fri")
        self.assertEqual(jobs["行情日终重刷"]["cron"], "0 16 * * mon-fri")
        self.assertEqual(jobs["行情日终重刷"]["config"]["mode"], "today_refresh")

        notify = self.client.post(
            "/api/jobs",
            json={"name": "触价推送", "kind": "notify", "cron": "", "config": {"template": "alerts"}},
        )
        self.assertEqual(notify.status_code, 201, notify.text)
        self.assertEqual(notify.json()["kind"], "notify")

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

    def test_schedule_status_computes_next_run_without_scheduler(self) -> None:
        """调度器未开时仍按 cron 推算下次触发，详情页不能永远是「—」。"""
        created = self.client.post(
            "/api/jobs",
            json={
                "name": "盘中增量测",
                "kind": "sync",
                "cron": "*/5 9-14 * * 1-5",
                "enabled": True,
            },
        ).json()
        body = self.client.get("/api/jobs/schedule").json()
        self.assertFalse(body["running"])
        hit = next(item for item in body["jobs"] if item["id"] == created["id"])
        self.assertTrue(hit["next_run_at"])

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

    def test_provider_saves_without_master_key(self) -> None:
        """本机明文落库：不再要求 PALACE_AI_MASTER_KEY。"""
        import os

        os.environ.pop("PALACE_AI_MASTER_KEY", None)
        response = self.client.post(
            "/api/providers",
            json={
                "name": "plain-p",
                "base_url": "https://example.com/v1",
                "api_key": "sk-plain-xyz9",
                "validate_key": False,
                "discover_models": False,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["key_last4"], "****xyz9")
        self.assertNotIn("sk-plain-xyz9", response.text)

    def test_provider_round_trip_never_exposes_the_key(self) -> None:
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
        self.assertEqual(body["models"], ["some/model"])
        self.assertEqual(body["model_catalog"][0]["id"], "some/model")
        self.assertEqual(body["model_catalog"][0]["source"], "manual")

        listed = self.client.get("/api/providers")
        self.assertNotIn("sk-super-secret", listed.text)
        self.assertTrue(listed.json()[0]["has_key"])

        updated = self.client.put(
            "/api/providers/openrouter/models",
            json={
                "default_model": "some/model",
                "models": [
                    {
                        "id": "some/model",
                        "name": "Some",
                        "enabled": True,
                        "context_window": 65536,
                        "max_output_tokens": 4096,
                        "source": "manual",
                    },
                    {
                        "id": "other/model",
                        "enabled": False,
                        "source": "manual",
                    },
                ],
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        ubody = updated.json()
        self.assertEqual(ubody["models"], ["some/model"])
        self.assertEqual(ubody["model_catalog"][0]["context_window"], 65536)
        self.assertFalse(ubody["model_catalog"][1]["enabled"])

        self.assertEqual(self.client.delete("/api/providers/openrouter").status_code, 200)

    def test_provider_errors_and_probe_preview_redact_current_api_key(self) -> None:
        from types import SimpleNamespace

        from src.ai.infrastructure.client import ChatResponse
        from src.ops import OpsError

        secret = "sk-super-secret-1234"
        with patch(
            "src.ai.infrastructure.providers.save_provider",
            side_effect=OpsError(f"x-api-key: {secret}; Bearer {secret}"),
        ):
            failed = self.client.post(
                "/api/providers",
                json={"name": "demo", "base_url": "https://example.com/v1", "api_key": secret},
            )
        self.assertEqual(failed.status_code, 422)
        self.assertNotIn(secret, failed.text)

        provider = SimpleNamespace(name="demo", model="m", api_key=secret)
        with patch("src.ai.resolve_config", return_value=provider), patch(
            "src.ai.infrastructure.client.validate",
            return_value=ChatResponse(text=f'{{"api_key":"{secret}"}}'),
        ):
            tested = self.client.post("/api/providers/demo/test")
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertNotIn(secret, tested.text)
        self.assertIn("[REDACTED]", tested.json()["preview"])

    def test_deleting_unknown_provider_is_404(self) -> None:
        self.assertEqual(self.client.delete("/api/providers/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
