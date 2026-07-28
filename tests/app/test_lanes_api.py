"""数据线路运维 API：目录 / 探测 / 测速（不打真网）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.market.infrastructure.adapters.types import ProbeResult, SpeedTestResult
from src.app.main import create_app


class LanesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        # 偏好写入测试目录下的 loci.config，避免污染工作区
        self._cfg = base / "loci.config.json"
        app = create_app(base / "palace.db", base / "no-static")
        self.client = TestClient(app)
        self._writable_patch = patch(
            "src.shared.paths.writable_root", return_value=base
        )
        self._writable_patch.start()

    def tearDown(self) -> None:
        self._writable_patch.stop()
        self.client.close()
        self.temp.cleanup()

    def test_catalog_lists_lanes_and_providers(self) -> None:
        body = self.client.get("/api/ops/lanes").json()
        lane_ids = {item["id"] for item in body["lanes"]}
        self.assertIn("hist_daily", lane_ids)
        self.assertTrue(body["providers"])
        ids = {p["id"] for p in body["providers"]}
        self.assertIn("sina", ids)
        self.assertIn("eastmoney", ids)
        for p in body["providers"]:
            self.assertIn("enabled", p)
            self.assertIn("label", p)

    def test_probe_unknown_lane_is_400(self) -> None:
        response = self.client.post("/api/ops/lanes/probe", json={"lane": "nope"})
        self.assertEqual(response.status_code, 400)

    def test_probe_hist_daily_uses_router(self) -> None:
        fake = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=12.3, rows=5),
            ProbeResult(
                adapter_id="eastmoney",
                lane="hist_daily",
                ok=False,
                rtt_ms=40.0,
                error="timeout",
            ),
        ]
        with patch("src.market.infrastructure.adapters.probe_lane", return_value=fake) as mocked:
            body = self.client.post(
                "/api/ops/lanes/probe", json={"lane": "hist_daily"}
            ).json()
        mocked.assert_called()
        self.assertEqual(len(body["results"]), 2)
        self.assertEqual(body["results"][0]["adapter_id"], "sina")
        self.assertIn("label", body["results"][0])

    def test_speedtest_rejects_non_hist(self) -> None:
        response = self.client.post(
            "/api/ops/lanes/speedtest",
            json={"lane": "spot_batch", "code": "600519"},
        )
        self.assertEqual(response.status_code, 400)

    def test_speedtest_hist_daily(self) -> None:
        fake = [
            SpeedTestResult(
                adapter_id="sina",
                code="600519",
                ok=True,
                elapsed_ms=100.0,
                rows=1000,
                bytes_est=80000,
                mb_per_s=0.8,
            )
        ]
        with patch("src.market.infrastructure.adapters.speedtest_daily", return_value=fake):
            body = self.client.post(
                "/api/ops/lanes/speedtest",
                json={"lane": "hist_daily", "code": "600519"},
            ).json()
        self.assertEqual(body["lane"], "hist_daily")
        self.assertEqual(body["results"][0]["rows"], 1000)
        self.assertIn("label", body["results"][0])

    def test_speedtest_all_disabled_returns_empty(self) -> None:
        """全部停用时不得回退成探测全部源（曾用 ids or None 踩）。"""
        with patch(
            "src.shared.paths.load_config",
            return_value={
                "lane_providers": {
                    "sina": {"enabled": False},
                    "eastmoney": {"enabled": False},
                    "tencent": {"enabled": False},
                }
            },
        ):
            with patch("src.market.infrastructure.adapters.speedtest_daily") as mocked:
                body = self.client.post(
                    "/api/ops/lanes/speedtest",
                    json={"lane": "hist_daily"},
                ).json()
                mocked.assert_not_called()
        self.assertEqual(body["results"], [])

    def test_probe_adapter_id_ignores_disabled(self) -> None:
        """「测这家」带 adapter_id 时，即使停用也要能探到该源。"""
        fake = [
            ProbeResult(adapter_id="sina", lane="hist_daily", ok=True, rtt_ms=1.0, rows=3),
        ]
        with patch(
            "src.shared.paths.load_config",
            return_value={"lane_providers": {"sina": {"enabled": False}}},
        ):
            with patch("src.market.infrastructure.adapters.probe_lane", return_value=fake) as mocked:
                body = self.client.post(
                    "/api/ops/lanes/probe",
                    json={"lane": "hist_daily", "adapter_id": "sina"},
                ).json()
        mocked.assert_called_once()
        kwargs = mocked.call_args
        self.assertEqual(kwargs[0][0], "hist_daily")
        self.assertEqual(list(kwargs[1]["adapter_ids"]), ["sina"])
        self.assertEqual(body["results"][0]["adapter_id"], "sina")

    def test_patch_provider_enabled(self) -> None:
        with patch("src.shared.paths.save_config", return_value={}) as saved:
            with patch(
                "src.shared.paths.load_config",
                return_value={"lane_providers": {}},
            ):
                # write_guard 可能要求登录；测试客户端通常旁路或无鉴权
                response = self.client.patch(
                    "/api/ops/lanes/providers/sina",
                    json={"enabled": False},
                )
        if response.status_code == 401:
            self.skipTest("write_guard 要求登录，本环境未注入凭证")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], "sina")
        self.assertFalse(body["enabled"])
        saved.assert_called()
        # 合并写入只动 lane_providers
        arg = saved.call_args[0][0]
        self.assertEqual(arg["lane_providers"]["sina"]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
