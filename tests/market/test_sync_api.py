"""市场同步 HTTP 契约：同步完成语义、执行闸门与错误恢复。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app.main import create_app


class MarketSyncApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        self.client = TestClient(create_app(base / "palace.db", base / "no-static"))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_returns_completed_report_and_rejects_duplicate_run(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls = 0
        calls_lock = threading.Lock()

        def fake_execute_sync(*_args, **_kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
                call_number = calls
            if call_number == 1:
                started.set()
                self.assertTrue(release.wait(timeout=3))
            return {"total": 1, "succeeded": 1, "failed": 0}

        with patch("src.ops.application.jobs.execute_sync", side_effect=fake_execute_sync):
            with ThreadPoolExecutor(max_workers=1) as executor:
                first_future = executor.submit(
                    self.client.post, "/api/market/sync", json={"codes": ["600519"]}
                )
                self.assertTrue(started.wait(timeout=3))
                duplicate = self.client.post(
                    "/api/market/sync", json={"codes": ["600519"]}
                )
                release.set()
                first = first_future.result(timeout=3)

        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["succeeded"], 1)
        self.assertEqual(calls, 1)

    def test_validation_fails_before_execution(self) -> None:
        with patch("src.ops.application.jobs.execute_sync") as execute_sync:
            response = self.client.post("/api/market/sync", json={"workers": 0})

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"][0]["loc"], ["body", "workers"])
        execute_sync.assert_not_called()

    def test_releases_gate_after_execution_error(self) -> None:
        from src.ops.application.jobs import JobError

        with patch(
            "src.ops.application.jobs.execute_sync",
            side_effect=[JobError("没有可同步的标的"), {"total": 1, "succeeded": 1}],
        ) as execute_sync:
            failed = self.client.post("/api/market/sync", json={"codes": ["600519"]})
            retried = self.client.post("/api/market/sync", json={"codes": ["600519"]})

        self.assertEqual(failed.status_code, 422, failed.text)
        self.assertEqual(failed.json(), {"detail": "没有可同步的标的"})
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(execute_sync.call_count, 2)

    def test_openapi_lists_runtime_error_statuses(self) -> None:
        responses = self.client.app.openapi()["paths"]["/api/market/sync"]["post"]["responses"]

        self.assertEqual(set(responses), {"200", "409", "422", "502"})
