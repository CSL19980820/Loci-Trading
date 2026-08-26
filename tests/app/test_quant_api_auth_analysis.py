"""组合根：生产鉴权、分析端点与同步判定。

从 `test_quant_api.py` 拆出（原 616 行）；主 HTTP 契约用例仍在原文件。
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.app.main import create_app

from tests.app.quant_api_fixtures import _skill_zip


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
            write_token="test-token-0123456789abcdef0123456789abcdef",
            auth_username="admin",
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

    def test_sync_screen_candidate_writes_use_write_guard(self) -> None:
        """默认入库的同步选股必须在计算和持久化前经过写守卫。"""
        from src.strategy.api.router import build_strategy_router

        def reject_write() -> None:
            raise HTTPException(status_code=401, detail="write access denied")

        app = FastAPI()
        app.include_router(build_strategy_router(write_dependency=reject_write))
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch(
                "src.strategy.api.router.market_store",
                side_effect=AssertionError("写守卫应在选股前拒绝请求"),
            ),
            patch("src.strategy.api.router.should_sync_today", return_value=False),
        ):
            for method, path, kwargs in (
                ("post", "/api/strategies/screen", {"json": {"strategy": "qianlong-close-v3"}}),
                ("get", "/api/screen/today?strategy=qianlong-close-v3", {}),
            ):
                with self.subTest(path=path):
                    response = getattr(client, method)(path, **kwargs)
                    self.assertEqual(response.status_code, 401, response.text)

    def test_agent_bearer_token_is_accepted(self) -> None:
        response = self.client.post(
            "/api/jobs",
            json={"name": "x", "kind": "sync"},
            headers={
                "Authorization": (
                    "Bearer test-token-0123456789abcdef0123456789abcdef"
                )
            },
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

    def test_analysis_uses_a_run_snapshot_and_returns_that_run_id(self) -> None:
        calls: list[tuple[object, str | None]] = []

        def fake_run_job(_store, job, **kwargs):
            calls.append((job, kwargs.get("run_id")))
            return {"status": "success"}

        with patch("src.ops.run_job", side_effect=fake_run_job):
            first = self.client.post(
                "/api/analysis/compare", json={"holds": [1]}
            ).json()
            second = self.client.post(
                "/api/analysis/compare", json={"holds": [3]}
            ).json()
            for thread in list(threading.enumerate()):
                if thread.name.startswith("analysis-"):
                    thread.join(timeout=5)

        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertIn(f"run_id={first['run_id']}", first["poll"])
        self.assertIn(f"run_id={second['run_id']}", second["poll"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(isinstance(job, dict) for job, _ in calls))
        self.assertEqual(
            {int(job["config"]["holds"][0]) for job, _ in calls},
            {1, 3},
        )
        self.assertEqual(
            {run_id for _, run_id in calls},
            {first["run_id"], second["run_id"]},
        )

    def test_analysis_thread_start_failure_marks_run_failed(self) -> None:
        """任务槽已落库后若线程无法启动，不能留下永远 running 的历史。"""
        with patch("src.strategy.api.router.threading.Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("no thread slots")
            response = self.client.post("/api/analysis/compare", json={"holds": [1]})

        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("no thread slots", response.json()["detail"])

        from src.ops import OpsStore
        import os

        with OpsStore(os.environ["PALACE_OPS_DB"]) as store:
            job = store.get_job_by_name("[即时] compare")
            self.assertIsNotNone(job)
            runs = store.list_runs(job_id=job["id"], limit=10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("no thread slots", runs[0]["error_text"])


class ShouldSyncTodayTests(unittest.TestCase):
    def test_uses_explicit_market_db_not_default_path(self) -> None:
        """线上 PALACE_MARKET_DB 与默认 data/market.db 不是同一个库。"""
        from src.shared.api_deps import should_sync_today

        with tempfile.TemporaryDirectory() as tmp:
            market_db = Path(tmp) / "prod-market.db"
            seen: list[str | None] = []

            class FakeStore:
                def __init__(self, path: str | None) -> None:
                    seen.append(None if path is None else str(path))

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def list_instruments(self):
                    return []

                def coverage(self):
                    return {"last_date": ""}

            with patch("src.market.MarketStore", FakeStore):
                self.assertTrue(should_sync_today(str(market_db)))
            self.assertEqual(seen, [str(market_db)])
