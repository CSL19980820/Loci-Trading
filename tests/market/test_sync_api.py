"""市场同步 HTTP 契约：同步完成语义、执行闸门与错误恢复。"""
from __future__ import annotations

from pathlib import Path
import tempfile
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

    def test_returns_completed_report(self) -> None:
        with patch(
            "src.ops.application.jobs.execute_sync",
            return_value={"total": 1, "succeeded": 1, "failed": 0},
        ) as execute_sync:
            response = self.client.post("/api/market/sync", json={"codes": ["600519"]})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["succeeded"], 1)
        self.assertEqual(execute_sync.call_count, 1)

    def test_duplicate_run_reports_skipped_not_conflict(self) -> None:
        """已有同步在跑时返回 200 + status=skipped，不再报 409。

        去重本身没丢，只是搬了家：唯一的并发闸门是 ``execute_sync`` 占的
        ``ops.market_gate`` sync 写槽（HTTP / bootstrap / CLI / 调度四入口共用）。
        HTTP 层过去再叠一层进程锁 + 409，等于同一件事判两次，还把「排队」
        说成冲突错误——用户看到的就是「老是报冲突」。
        """
        from src.ops.application.jobs import JobSkipped

        with patch(
            "src.ops.application.jobs.execute_sync",
            side_effect=JobSkipped("行情库正被占用（同步任务（sync:01）），本轮跳过"),
        ):
            duplicate = self.client.post("/api/market/sync", json={"codes": ["600519"]})

        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        body = duplicate.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "skipped")
        self.assertTrue(body["skipped"])
        self.assertIn("未重复启动", body["detail"])
        self.assertIn("本轮跳过", body["reason"])

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

        # 409 已撤：并发闸门只在 market_gate 一处，排队不是冲突错误。
        self.assertEqual(set(responses), {"200", "422", "502"})
